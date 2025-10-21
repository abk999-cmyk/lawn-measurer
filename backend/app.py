# -*- coding: utf-8 -*-
import os
import sys
import uuid
import json
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from lawn_analyzer import analyze_lawn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload
app.config['OUTPUT_DIR'] = os.getenv('OUTPUT_DIR', 'outputs')
app.config['MODEL_PATH'] = os.getenv('MODEL_PATH', 'model_19class.pth')

# Ensure directories exist
os.makedirs(app.config['OUTPUT_DIR'], exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'tif', 'tiff', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_uuid(job_id):
    """Validate that job_id is a valid UUID"""
    try:
        uuid.UUID(job_id)
        return True
    except ValueError:
        return False

def validate_filename(filename):
    """Validate filename has no path traversal"""
    return '..' not in filename and '/' not in filename and '\\' not in filename

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "message": "Lawn segmentation API is running"})

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    Analyze lawn from uploaded image and GeoJSON polygon
    
    Expects multipart/form-data with:
    - image: image file
    - geojson: JSON string with polygon coordinates
    - address: address string (optional)
    """
    try:
        logger.info("Received analysis request")
        
        # Validate request
        if 'image' not in request.files:
            logger.error("No image file in request")
            return jsonify({"error": "No image file provided"}), 400
        
        if 'geojson' not in request.form:
            logger.error("No geojson in request")
            return jsonify({"error": "No GeoJSON provided"}), 400
        
        image_file = request.files['image']
        geojson_str = request.form['geojson']
        address = request.form.get('address', 'Unknown Location')
        
        # Validate image file
        if image_file.filename == '':
            logger.error("Empty filename")
            return jsonify({"error": "No selected file"}), 400
        
        if not allowed_file(image_file.filename):
            logger.error(f"Invalid file type: {image_file.filename}")
            return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, tif, tiff, webp"}), 400
        
        # Parse GeoJSON
        try:
            geojson_data = json.loads(geojson_str)
            if 'type' not in geojson_data or 'features' not in geojson_data:
                raise ValueError("Invalid GeoJSON structure")
            if len(geojson_data['features']) == 0:
                raise ValueError("No features in GeoJSON")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            return jsonify({"error": f"Invalid GeoJSON: {str(e)}"}), 400
        except ValueError as e:
            logger.error(f"Invalid GeoJSON: {e}")
            return jsonify({"error": str(e)}), 400
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(app.config['OUTPUT_DIR'], job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        logger.info(f"Created job {job_id} for address: {address}")
        
        # Save uploaded image
        filename = secure_filename(image_file.filename)
        image_path = os.path.join(job_dir, f"input_{filename}")
        image_file.save(image_path)
        logger.info(f"Saved input image: {image_path}")
        
        # Run analysis
        logger.info("Starting lawn analysis...")
        result = analyze_lawn(
            image_path=image_path,
            geojson_payload=geojson_data,
            address=address,
            output_dir=job_dir,
            model_path=app.config['MODEL_PATH']
        )
        
        if not result['success']:
            logger.error(f"Analysis failed: {result['message']}")
            return jsonify({
                "error": result['message'],
                "job_id": job_id
            }), 500
        
        # Build response with relative URLs
        metrics = result['metrics']
        variant_name = metrics.get('variant_used', 't1-0.26-0.10-0.14')
        
        response = {
            "job_id": job_id,
            "status": "success",
            "message": result['message'],
            "results": {
                "best_overlay_url": f"/api/results/{job_id}/best_overlay.png",
                "front_back_sides_url": f"/api/results/{job_id}/overlay_front_back_sides_{variant_name}.png",
                "metrics": metrics
            }
        }
        
        logger.info(f"Analysis complete for job {job_id}")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/api/results/<job_id>/<filename>', methods=['GET'])
def get_result(job_id, filename):
    """
    Serve result files for a job
    
    Args:
        job_id: UUID of the analysis job
        filename: Name of the file to serve
    """
    try:
        # Validate job_id
        if not validate_uuid(job_id):
            logger.error(f"Invalid job_id: {job_id}")
            return jsonify({"error": "Invalid job ID"}), 400
        
        # Validate filename (security check)
        if not validate_filename(filename):
            logger.error(f"Invalid filename: {filename}")
            return jsonify({"error": "Invalid filename"}), 400
        
        # Check if directory exists
        job_dir = os.path.join(app.config['OUTPUT_DIR'], job_id)
        if not os.path.exists(job_dir):
            logger.error(f"Job directory not found: {job_id}")
            return jsonify({"error": "Job not found"}), 404
        
        # Check if file exists
        file_path = os.path.join(job_dir, filename)
        if not os.path.exists(file_path):
            logger.error(f"File not found: {filename} in job {job_id}")
            return jsonify({"error": "File not found"}), 404
        
        logger.info(f"Serving file: {filename} for job {job_id}")
        return send_from_directory(job_dir, filename)
        
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error serving file: {str(e)}"}), 500

@app.route('/api/results/<job_id>', methods=['GET'])
def list_results(job_id):
    """
    List all result files for a job
    
    Args:
        job_id: UUID of the analysis job
    """
    try:
        # Validate job_id
        if not validate_uuid(job_id):
            return jsonify({"error": "Invalid job ID"}), 400
        
        # Check if directory exists
        job_dir = os.path.join(app.config['OUTPUT_DIR'], job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
        # List all files
        files = [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
        
        return jsonify({
            "job_id": job_id,
            "files": files
        }), 200
        
    except Exception as e:
        logger.error(f"Error listing results: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error listing results: {str(e)}"}), 500

@app.errorhandler(413)
def too_large(e):
    """Handle file too large error"""
    return jsonify({"error": "File too large. Maximum size is 10MB"}), 413

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    """Handle internal server errors"""
    logger.error(f"Internal server error: {str(e)}", exc_info=True)
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    logger.info("Starting Flask server...")
    logger.info(f"Output directory: {app.config['OUTPUT_DIR']}")
    logger.info(f"Model path: {app.config['MODEL_PATH']}")
    
    # Run server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )

