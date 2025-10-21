# Lawn Segmentation Web Application

A full-stack web application that uses machine learning to analyze satellite imagery and segment lawn areas into front, back, and side yards with precise area measurements.

## Features

- 🗺️ **Interactive Satellite Map** - Browse and navigate using Google Maps satellite view
- 📍 **Address Search** - Search and jump to any address using Google Places API
- ✏️ **Polygon Drawing** - Draw custom boundaries around properties
- 🤖 **ML-Powered Analysis** - Uses FLAIR-INC deep learning model for semantic segmentation
- 📊 **Detailed Measurements** - Get area measurements in both ft² and m²
- 🎨 **Visual Overlays** - View lawn detection and zone segmentation overlays
- 💾 **Export Results** - Download overlay images and metrics JSON

## Technology Stack

### Backend
- **Python 3.11** with Flask REST API
- **PyTorch** for deep learning inference
- **FLAIR-INC ResNet34-UNet** model for land cover segmentation
- **GeoPandas** for geospatial processing
- **OpenCV** for image processing

### Frontend
- **React 18** with Vite
- **Google Maps JavaScript API** with Drawing Manager
- **Axios** for API communication
- **CSS3** for modern, responsive design

## Prerequisites

- **Python 3.11+** installed
- **Node.js 18+** and npm
- **Google Maps API Key** with the following APIs enabled:
  - Maps JavaScript API
  - Places API
  - Static Maps API

## Setup Instructions

### 1. Clone or Navigate to Project

```bash
cd "/Users/abhinav/Desktop/Personal Projects/fix"
```

### 2. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment (if not already done)
python3.11 -m venv ../.venv311
source ../.venv311/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Note**: The ML model (`model_19class.pth`, ~93MB) will be automatically downloaded on first run.

### 3. Backend Configuration

The `.env` file in the `backend/` directory is already configured:

```env
FLASK_ENV=development
FLASK_DEBUG=True
OUTPUT_DIR=outputs
MODEL_PATH=model_19class.pth
SINGLE_RUN=1
GOOGLE_MAPS_API_KEY=AIzaSyAc4z6iX8EWzwfwabF0oasPyORh4hQ7zbY
```

### 4. Frontend Setup

```bash
# Navigate to frontend directory
cd ../frontend

# Install dependencies
npm install
```

### 5. Frontend Configuration

The `.env` file in the `frontend/` directory is already configured with the Google Maps API key.

## Running the Application

### Start Backend Server

```bash
# From backend directory (with venv activated)
cd backend
source ../.venv311/bin/activate
python app.py
```

The Flask server will start on `http://localhost:5000`

### Start Frontend Development Server

In a **new terminal**:

```bash
# From frontend directory
cd frontend
npm run dev
```

The React app will start on `http://localhost:5173`

### Access the Application

Open your browser and navigate to: **http://localhost:5173**

## Usage Guide

### Step 1: Search for Location
1. Use the search bar at the top of the map
2. Type an address (e.g., "5980 Woodmill Dr, Fishers, IN 46038")
3. Select from autocomplete suggestions
4. Map will zoom to the location

### Step 2: Draw Polygon
1. Click the polygon tool in the map controls
2. Click on the map to place polygon vertices around the property boundary
3. Close the polygon by clicking the first point or double-clicking
4. You can draw only one polygon at a time (previous polygon will be deleted)

### Step 3: Analyze
1. Click the "Analyze Lawn" button
2. Wait 30-60 seconds while the system:
   - Captures satellite imagery
   - Runs ML segmentation
   - Calculates area measurements
3. Results will appear in the right panel

### Step 4: View Results
- **Lawn Detection**: Shows identified lawn areas in green overlay
- **Yard Zones**: Color-coded visualization:
  - 🟢 Green = Front yard
  - 🔵 Blue = Back yard
  - 🟠 Orange = Left side
  - 🔴 Red = Right side
- **Metrics Table**: Detailed area measurements for each zone

### Step 5: Download Results
- Click "Download Results" to save:
  - Lawn overlay image
  - Yard zones overlay image
  - Metrics JSON file

## API Endpoints

### Backend API

**Health Check**
```
GET /api/health
```

**Analyze Property**
```
POST /api/analyze
Content-Type: multipart/form-data

Parameters:
  - image: Image file (JPEG/PNG)
  - geojson: GeoJSON string with polygon coordinates
  - address: Property address string

Response:
{
  "job_id": "uuid",
  "status": "success",
  "results": {
    "best_overlay_url": "/api/results/{uuid}/best_overlay.png",
    "front_back_sides_url": "/api/results/{uuid}/overlay_front_back_sides_{variant}.png",
    "metrics": {...}
  }
}
```

**Get Result Files**
```
GET /api/results/{job_id}/{filename}
```

## Architecture

```
fix/
├── backend/
│   ├── app.py                 # Flask API server
│   ├── lawn_analyzer.py       # ML segmentation logic
│   ├── requirements.txt       # Python dependencies
│   ├── .env                   # Environment variables
│   ├── outputs/               # Analysis results (UUID-based)
│   ├── logs/                  # Application logs
│   └── model_19class.pth      # ML model weights
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Main component
│   │   ├── App.css           # Styling
│   │   ├── components/       # React components
│   │   │   ├── MapContainer.jsx
│   │   │   ├── AddressSearch.jsx
│   │   │   ├── AnalysisPanel.jsx
│   │   │   └── ResultsDisplay.jsx
│   │   └── services/
│   │       └── api.js        # Backend API client
│   ├── vite.config.js        # Vite configuration
│   ├── .env                  # Environment variables
│   └── package.json          # Node dependencies
│
├── run.py                     # Original standalone script
└── README.md                  # This file
```

## Troubleshooting

### Backend Issues

**Port 5000 already in use**
```bash
# Find and kill the process using port 5000
lsof -ti:5000 | xargs kill -9
```

**Model download fails**
- Check internet connection
- Model URL: https://huggingface.co/IGNF/FLAIR-INC_rgb_12cl_resnet34-unet
- Manually download and place in `backend/model_19class.pth`

**Import errors**
```bash
# Ensure virtual environment is activated
source ../.venv311/bin/activate
# Reinstall dependencies
pip install -r requirements.txt
```

### Frontend Issues

**Google Maps not loading**
- Verify API key in `frontend/.env`
- Check browser console for API errors
- Ensure Maps JavaScript API is enabled in Google Cloud Console

**"No response from server" error**
- Ensure backend is running on port 5000
- Check `vite.config.js` proxy settings
- Verify firewall/antivirus isn't blocking connections

**Polygon tool not appearing**
- Refresh the page
- Check browser console for errors
- Ensure Drawing library is loaded

### Analysis Issues

**Analysis takes too long**
- Normal processing time: 30-60 seconds
- First run may take longer (model download)
- Check backend logs: `backend/logs/app.log`

**Low confidence scores**
- Image quality may be poor
- Polygon may be too large or too small
- Try redrawing polygon with more precise boundaries

**Building detection inaccurate**
- ML model trained on aerial imagery
- Works best with clear building structures
- Consider manually adjusting polygon boundaries

## Performance Notes

- **Image Size**: Fixed at 640x640 pixels (Google Static Maps free tier)
- **Processing Time**: ~30-60 seconds per analysis
- **Model Size**: 93MB (cached after first download)
- **Supported Image Formats**: PNG, JPEG, TIFF, WebP
- **Max Upload Size**: 10MB

## Development

### Backend Development

```bash
# Run with debug mode
cd backend
FLASK_DEBUG=True python app.py

# View logs
tail -f logs/app.log
```

### Frontend Development

```bash
# Run dev server with hot reload
cd frontend
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Credits

- **FLAIR-INC Model**: French National Geographic Institute (IGN)
- **Segmentation Model**: ResNet34-UNet architecture
- **Maps Data**: Google Maps Platform
- **ML Framework**: PyTorch

## License

This project uses the FLAIR-INC model which has specific licensing terms. Please refer to the model's Hugging Face page for details.

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review backend logs in `backend/logs/app.log`
3. Check browser console for frontend errors
4. Ensure all prerequisites are properly installed

---

**Note**: This application is designed for localhost development and testing. For production deployment, additional security measures, rate limiting, and error handling should be implemented.

