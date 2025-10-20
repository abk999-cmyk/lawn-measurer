"""
FastAPI Backend for Lawn Analysis Web App
Handles API requests and coordinates between image fetcher and analysis core
"""
import os
import sys
import uuid
import base64
import logging
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from shapely.errors import TopologicalError, GEOSException
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from image_fetcher import GoogleStaticMapFetcher
from core import analyze_lawn_from_geojson

# Configure logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./outputs")
TILE_CACHE_DIR = os.environ.get("TILE_CACHE_DIR", "./tile_cache")
MODEL_PATH = os.environ.get("MODEL_PATH", "../model_19class.pth")

# Validate required configuration
if not GOOGLE_MAPS_API_KEY:
    logger.warning("GOOGLE_MAPS_API_KEY not set! Image fetching will fail.")
    logger.warning("Set GOOGLE_MAPS_API_KEY environment variable with your Google Maps API key")

# Ensure directories exist
Path(OUTPUT_DIR).mkdir(exist_ok=True)
Path(TILE_CACHE_DIR).mkdir(exist_ok=True)

# Initialize FastAPI app
app = FastAPI(
    title="Lawn Analysis API",
    description="API for analyzing lawn areas from satellite imagery using AI segmentation",
    version="1.0.0"
)

# CORS middleware - allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Google Maps image fetcher (reused across requests)
image_fetcher = GoogleStaticMapFetcher(api_key=GOOGLE_MAPS_API_KEY, cache_dir=TILE_CACHE_DIR)


# Request/Response models
class AnalyzeRequest(BaseModel):
    geojson: Dict
    address: Optional[str] = None
    zoom: Optional[int] = 18


class AnalyzeResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    lawn_area_ft2: Optional[float] = None
    lawn_area_m2: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_grade: Optional[str] = None
    overlay_base64: Optional[str] = None
    zones_overlay_base64: Optional[str] = None
    zones_metrics: Optional[Dict] = None
    processing_time_seconds: Optional[float] = None


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Lawn Analysis API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Health check with more details"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "output_dir": OUTPUT_DIR,
        "tile_cache_dir": TILE_CACHE_DIR,
        "model_path": MODEL_PATH,
        "model_exists": os.path.exists(MODEL_PATH),
        "google_maps_api_configured": bool(GOOGLE_MAPS_API_KEY),
        "image_source": "Google Maps Static API"
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_lawn(request: AnalyzeRequest):
    """
    Analyze lawn area from a polygon drawn on a map
    
    Args:
        request: AnalyzeRequest containing geojson polygon and optional address
        
    Returns:
        AnalyzeResponse with lawn measurements, overlay images, and confidence scores
    """
    start_time = datetime.now()
    session_id = str(uuid.uuid4())[:8]
    session_output_dir = os.path.join(OUTPUT_DIR, f"session_{session_id}")
    
    logger.info(f"[{session_id}] New analysis request received")
    
    try:
        # Validate GeoJSON
        if not request.geojson:
            raise HTTPException(status_code=400, detail="GeoJSON is required")
        
        if "features" not in request.geojson or not request.geojson["features"]:
            raise HTTPException(status_code=400, detail="GeoJSON must contain at least one feature")
        
        # Create session output directory
        os.makedirs(session_output_dir, exist_ok=True)
        logger.info(f"[{session_id}] Session directory created: {session_output_dir}")
        
        # Step 1: Fetch satellite imagery using Google Maps Static API
        logger.info(f"[{session_id}] Fetching satellite imagery at zoom {request.zoom}")
        image_path = os.path.join(session_output_dir, "satellite_image.jpg")
        
        try:
            # Fetch image from Google Maps Static API
            image, bounds = image_fetcher.fetch_image_for_polygon(
                request.geojson,
                zoom=request.zoom if request.zoom else 19
            )
            
            # Convert to RGB if needed (some Google Maps images come as palette mode)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Save image to disk
            image.save(image_path, 'JPEG', quality=95)
            logger.info(f"[{session_id}] Image fetched successfully")
            logger.info(f"[{session_id}] Image saved to: {image_path}")
        except Exception as e:
            logger.error(f"[{session_id}] Image fetch failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch satellite imagery: {str(e)}")
        
        # Step 2: Run lawn analysis
        logger.info(f"[{session_id}] Starting lawn analysis")
        
        try:
            analysis_result = analyze_lawn_from_geojson(
                geojson_payload=request.geojson,
                image_path=image_path,
                output_dir=session_output_dir,
                model_path=MODEL_PATH,
                satellite_bounds=bounds  # Pass actual satellite image bounds
            )
            
            if not analysis_result.get("success"):
                error_msg = analysis_result.get("error", "Unknown error during analysis")
                logger.error(f"[{session_id}] Analysis failed: {error_msg}")
                raise HTTPException(status_code=500, detail=f"Analysis failed: {error_msg}")
            
            logger.info(f"[{session_id}] Analysis completed successfully")
        
        except ValueError as e:
            # Geometry validation errors from normalize_aoi_geojson
            logger.error(f"[{session_id}] Geometry validation error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid polygon: {str(e)}"
            )
        
        except (TopologicalError, GEOSException) as e:
            # Shapely topology errors
            logger.error(f"[{session_id}] Topology error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="The drawn polygon has overlapping lines or invalid geometry. "
                       "Please redraw your polygon ensuring: "
                       "1) Lines don't cross each other, "
                       "2) The polygon is properly closed, "
                       "3) There are at least 3 distinct points."
            )
            
        except Exception as e:
            # Catch-all for other errors
            logger.error(f"[{session_id}] Analysis error: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")
        
        # Step 3: Load and encode result images
        variant_name = analysis_result.get("variant", "t1-0.70-0.30-0.35")
        
        overlay_path = os.path.join(session_output_dir, f"overlay_{variant_name}.png")
        zones_overlay_path = os.path.join(session_output_dir, f"overlay_front_back_sides_{variant_name}.png")
        
        # Encode overlay image
        overlay_base64 = None
        if os.path.exists(overlay_path):
            with open(overlay_path, "rb") as f:
                overlay_base64 = base64.b64encode(f.read()).decode('utf-8')
            logger.info(f"[{session_id}] Overlay image encoded")
        else:
            logger.warning(f"[{session_id}] Overlay image not found: {overlay_path}")
        
        # Encode zones overlay
        zones_overlay_base64 = None
        if os.path.exists(zones_overlay_path):
            with open(zones_overlay_path, "rb") as f:
                zones_overlay_base64 = base64.b64encode(f.read()).decode('utf-8')
            logger.info(f"[{session_id}] Zones overlay image encoded")
        else:
            logger.warning(f"[{session_id}] Zones overlay not found: {zones_overlay_path}")
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Prepare response
        response = AnalyzeResponse(
            success=True,
            lawn_area_ft2=analysis_result.get("lawn_area_ft2"),
            lawn_area_m2=analysis_result.get("lawn_area_m2"),
            confidence_score=analysis_result.get("confidence_score"),
            confidence_grade=analysis_result.get("confidence_grade"),
            overlay_base64=overlay_base64,
            zones_overlay_base64=zones_overlay_base64,
            zones_metrics={
                "front_ft2": analysis_result["zones"]["areas_ft2"]["front"],
                "back_ft2": analysis_result["zones"]["areas_ft2"]["back"],
                "left_ft2": analysis_result["zones"]["areas_ft2"]["left"],
                "right_ft2": analysis_result["zones"]["areas_ft2"]["right"],
                "sides_ft2": analysis_result["zones"]["areas_ft2"]["sides"],
            },
            processing_time_seconds=processing_time
        )
        
        logger.info(f"[{session_id}] Request completed in {processing_time:.2f}s - "
                   f"Lawn: {response.lawn_area_ft2:.0f} ft² (confidence: {response.confidence_grade})")
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": f"Internal server error: {str(exc)}"
        }
    )


if __name__ == "__main__":
    # Run the server
    logger.info("Starting Lawn Analysis API server...")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"Tile cache directory: {TILE_CACHE_DIR}")
    logger.info(f"Model path: {MODEL_PATH}")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

