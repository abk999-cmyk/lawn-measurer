import { useState, useCallback, useRef } from 'react';
import { GoogleMap, DrawingManager, Polygon } from '@react-google-maps/api';

const mapContainerStyle = {
  width: '100%',
  height: '100%',
};

const defaultCenter = {
  lat: 39.8283,
  lng: -98.5795,
};

const defaultOptions = {
  mapTypeId: 'satellite',
  disableDefaultUI: false,
  zoomControl: true,
  mapTypeControl: true,
  streetViewControl: false,
  fullscreenControl: true,
};

const drawingManagerOptions = {
  drawingControl: true,
  drawingControlOptions: {
    position: window.google?.maps?.ControlPosition?.TOP_CENTER,
    drawingModes: ['polygon'],
  },
  polygonOptions: {
    fillColor: '#2196F3',
    fillOpacity: 0.3,
    strokeWeight: 2,
    strokeColor: '#2196F3',
    clickable: true,
    editable: true,
    draggable: false,
    zIndex: 1,
  },
};

function MapContainer({ onPolygonComplete, onMapLoad, mapRef }) {
  const [polygon, setPolygon] = useState(null);
  const drawingManagerRef = useRef(null);

  const handlePolygonComplete = useCallback((newPolygon) => {
    // Delete previous polygon if exists
    if (polygon) {
      polygon.setMap(null);
    }

    // Store new polygon
    setPolygon(newPolygon);

    // Get polygon path (coordinates)
    const path = newPolygon.getPath();
    const coordinates = [];
    
    for (let i = 0; i < path.getLength(); i++) {
      const point = path.getAt(i);
      coordinates.push([point.lng(), point.lat()]);
    }
    
    // Close the polygon by adding first point at the end
    if (coordinates.length > 0) {
      coordinates.push(coordinates[0]);
    }

    // Create GeoJSON
    const geojson = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [coordinates],
        },
        properties: {},
      }],
    };

    // Calculate bounds for the polygon
    const bounds = new window.google.maps.LatLngBounds();
    path.forEach((point) => {
      bounds.extend(point);
    });

    const ne = bounds.getNorthEast();
    const sw = bounds.getSouthWest();
    geojson.features[0].properties.bbox = [sw.lng(), sw.lat(), ne.lng(), ne.lat()];

    // Pass to parent
    if (onPolygonComplete) {
      onPolygonComplete(geojson, bounds);
    }

    // Disable drawing mode after polygon is drawn
    if (drawingManagerRef.current) {
      drawingManagerRef.current.setDrawingMode(null);
    }
  }, [polygon, onPolygonComplete]);

  const handleLoad = useCallback((map) => {
    if (mapRef) {
      mapRef.current = map;
    }
    if (onMapLoad) {
      onMapLoad(map);
    }
  }, [mapRef, onMapLoad]);

  const handleDrawingManagerLoad = useCallback((drawingManager) => {
    drawingManagerRef.current = drawingManager;
  }, []);

  return (
    <GoogleMap
      mapContainerStyle={mapContainerStyle}
      center={defaultCenter}
      zoom={4}
      options={defaultOptions}
      onLoad={handleLoad}
    >
      <DrawingManager
        onLoad={handleDrawingManagerLoad}
        onPolygonComplete={handlePolygonComplete}
        options={drawingManagerOptions}
      />
    </GoogleMap>
  );
}

export default MapContainer;

