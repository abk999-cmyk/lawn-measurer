import { useState } from 'react';
import { analyzeProperty } from '../services/api';

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;

function AnalysisPanel({ geojson, bounds, address, onAnalysisStart, onAnalysisComplete, onAnalysisError }) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');

  const calculateZoomLevel = (bounds, mapWidth, mapHeight) => {
    // Get bounds
    const ne = bounds.getNorthEast();
    const sw = bounds.getSouthWest();
    
    // Calculate the lat/lng spans
    const latSpan = Math.abs(ne.lat() - sw.lat());
    const lngSpan = Math.abs(ne.lng() - sw.lng());
    
    // World dimensions at zoom 0 (256px)
    const WORLD_DIM = 256;
    const ZOOM_MAX = 21;
    
    // Calculate zoom for latitude (with tighter fit factor of 0.8 to fill more of image)
    const latZoom = Math.floor(
      Math.log2((mapHeight * 0.8) * 360 / (latSpan * WORLD_DIM))
    );
    
    // Calculate zoom for longitude (with tighter fit factor of 0.8)
    const lngZoom = Math.floor(
      Math.log2((mapWidth * 0.8) * 360 / (lngSpan * WORLD_DIM))
    );
    
    // Use the minimum to ensure the entire bounds fit, then add 1 for closer view
    let zoom = Math.min(latZoom, lngZoom, ZOOM_MAX);
    
    // Boost zoom by 1 for tighter framing (but don't exceed max)
    zoom = Math.min(zoom + 1, ZOOM_MAX);
    
    // Ensure minimum zoom of 19 for good detail, maximum 21
    return Math.max(19, Math.min(zoom, ZOOM_MAX));
  };

  const captureStaticMapImage = async (bounds, geojson) => {
    if (!bounds) {
      throw new Error('No bounds provided');
    }

    // Get exact bounding box of polygon
    const ne = bounds.getNorthEast();
    const sw = bounds.getSouthWest();
    
    // Calculate center
    const center = bounds.getCenter();
    const lat = center.lat();
    const lng = center.lng();

    // Image dimensions
    const imageSize = 640;
    
    // Calculate zoom to fit polygon with minimal padding
    const zoom = calculateZoomLevel(bounds, imageSize, imageSize);
    
    console.log(`Calculated zoom level: ${zoom} for polygon bounds:`, {
      center: { lat, lng },
      ne: ne.toJSON(),
      sw: sw.toJSON()
    });

    // Build Static Maps API URL - this fetches centered on polygon
    const staticMapUrl = new URL('https://maps.googleapis.com/maps/api/staticmap');
    staticMapUrl.searchParams.append('center', `${lat},${lng}`);
    staticMapUrl.searchParams.append('zoom', zoom);
    staticMapUrl.searchParams.append('size', `${imageSize}x${imageSize}`);
    staticMapUrl.searchParams.append('maptype', 'satellite');
    staticMapUrl.searchParams.append('key', GOOGLE_MAPS_API_KEY);

    console.log('Fetching static map:', staticMapUrl.toString());

    // Fetch image
    const response = await fetch(staticMapUrl.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch map image: ${response.statusText}`);
    }

    const blob = await response.blob();
    
    // Create image element to load the blob
    const img = new Image();
    const imageUrl = URL.createObjectURL(blob);
    
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = imageUrl;
    });

    // Now crop the image to ONLY the polygon bounding box
    // Calculate the pixel coordinates of the polygon bounds within the fetched image
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    
    // At the fetched zoom level, calculate what pixels correspond to polygon bounds
    // Google Maps uses Mercator projection
    const WORLD_SIZE = 256 * Math.pow(2, zoom);
    
    // Convert lat/lng to world coordinates
    const latToY = (lat) => {
      const sin = Math.sin(lat * Math.PI / 180);
      return (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * WORLD_SIZE;
    };
    
    const lngToX = (lng) => {
      return ((lng + 180) / 360) * WORLD_SIZE;
    };
    
    // Image center in world coordinates
    const centerX = lngToX(lng);
    const centerY = latToY(lat);
    
    // Top-left corner of the image in world coordinates
    const imageTopLeftX = centerX - imageSize / 2;
    const imageTopLeftY = centerY - imageSize / 2;
    
    // Polygon bounds in world coordinates
    const polyNorthY = latToY(ne.lat());
    const polySouthY = latToY(sw.lat());
    const polyWestX = lngToX(sw.lng());
    const polyEastX = lngToX(ne.lng());
    
    // Convert to pixel coordinates within the fetched image
    const cropX = Math.max(0, Math.floor(polyWestX - imageTopLeftX));
    const cropY = Math.max(0, Math.floor(polyNorthY - imageTopLeftY));
    const cropWidth = Math.min(imageSize - cropX, Math.ceil(polyEastX - polyWestX));
    const cropHeight = Math.min(imageSize - cropY, Math.ceil(polySouthY - polyNorthY));
    
    console.log('Cropping to polygon bounds:', { cropX, cropY, cropWidth, cropHeight });
    
    // Set canvas to cropped size (minimum 100x100 for valid processing)
    canvas.width = Math.max(100, cropWidth);
    canvas.height = Math.max(100, cropHeight);
    
    // Draw cropped region
    ctx.drawImage(img, cropX, cropY, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
    
    // Clean up
    URL.revokeObjectURL(imageUrl);
    
    // Convert canvas to blob
    const croppedBlob = await new Promise((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', 0.95);
    });
    
    console.log(`Cropped image from ${imageSize}x${imageSize} to ${canvas.width}x${canvas.height} (polygon-only area)`);
    
    return croppedBlob;
  };

  const handleAnalyze = async () => {
    if (!geojson || !bounds) {
      alert('Please draw a polygon on the map first');
      return;
    }

    setLoading(true);
    setStatus('Capturing satellite image...');
    
    if (onAnalysisStart) {
      onAnalysisStart();
    }

    try {
      // Capture satellite image (cropped to polygon bounds only)
      const imageBlob = await captureStaticMapImage(bounds, geojson);
      setStatus('Analyzing lawn area...');

      // Send to backend for analysis
      const result = await analyzeProperty(
        imageBlob,
        geojson,
        address || 'Unknown Location'
      );

      setStatus('Analysis complete!');
      
      if (onAnalysisComplete) {
        onAnalysisComplete(result);
      }
    } catch (error) {
      console.error('Analysis error:', error);
      setStatus('');
      
      if (onAnalysisError) {
        onAnalysisError(error.message || 'Analysis failed');
      } else {
        alert('Error: ' + (error.message || 'Analysis failed'));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="analysis-panel">
      <button
        onClick={handleAnalyze}
        disabled={!geojson || loading}
        className="analyze-button"
      >
        {loading ? 'Analyzing...' : 'Analyze Lawn'}
      </button>
      
      {status && (
        <div className="status-message">
          {loading && <div className="spinner"></div>}
          <p>{status}</p>
        </div>
      )}
      
      {!geojson && (
        <p className="hint-text">
          Draw a polygon around the property on the map to begin analysis
        </p>
      )}
    </div>
  );
}

export default AnalysisPanel;

