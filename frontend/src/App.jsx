import { useState, useRef } from 'react';
import { useLoadScript } from '@react-google-maps/api';
import MapContainer from './components/MapContainer';
import AddressSearch from './components/AddressSearch';
import AnalysisPanel from './components/AnalysisPanel';
import ResultsDisplay from './components/ResultsDisplay';
import './App.css';

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;

const libraries = ['drawing', 'places'];

function App() {
  const [polygon, setPolygon] = useState(null);
  const [bounds, setBounds] = useState(null);
  const [address, setAddress] = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const mapRef = useRef(null);

  const { isLoaded, loadError } = useLoadScript({
    googleMapsApiKey: GOOGLE_MAPS_API_KEY,
    libraries,
  });

  const handlePolygonComplete = (geojson, polygonBounds) => {
    console.log('Polygon completed:', geojson);
    setPolygon(geojson);
    setBounds(polygonBounds);
    setResults(null); // Clear previous results
    setError(null);
  };

  const handlePlaceSelected = (location, selectedAddress) => {
    console.log('Place selected:', selectedAddress);
    setAddress(selectedAddress);
    // Clear previous polygon and results when new address is selected
    setPolygon(null);
    setBounds(null);
    setResults(null);
    setError(null);
  };

  const handleAnalysisStart = () => {
    setLoading(true);
    setError(null);
    setResults(null);
  };

  const handleAnalysisComplete = (analysisResults) => {
    console.log('Analysis complete:', analysisResults);
    setResults(analysisResults);
    setLoading(false);
    setError(null);
  };

  const handleAnalysisError = (errorMessage) => {
    console.error('Analysis error:', errorMessage);
    setError(errorMessage);
    setLoading(false);
    setResults(null);
  };

  const handleNewAnalysis = () => {
    setResults(null);
    setPolygon(null);
    setBounds(null);
    setError(null);
  };

  if (loadError) {
    return (
      <div className="error-container">
        <h1>Error loading Google Maps</h1>
        <p>{loadError.message}</p>
      </div>
    );
  }

  if (!isLoaded) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading Google Maps...</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Lawn Segmentation Analysis</h1>
        <p>Draw a polygon around your property to analyze lawn areas</p>
      </header>

      <div className="app-content">
        <div className="map-section">
          <div className="map-controls">
            <AddressSearch 
              mapRef={mapRef} 
              onPlaceSelected={handlePlaceSelected}
            />
          </div>
          <div className="map-container">
            <MapContainer
              onPolygonComplete={handlePolygonComplete}
              mapRef={mapRef}
            />
          </div>
          <div className="analysis-controls">
            <AnalysisPanel
              geojson={polygon}
              bounds={bounds}
              address={address}
              onAnalysisStart={handleAnalysisStart}
              onAnalysisComplete={handleAnalysisComplete}
              onAnalysisError={handleAnalysisError}
            />
          </div>
        </div>

        <div className="results-section">
          {error && (
            <div className="error-message">
              <h3>Error</h3>
              <p>{error}</p>
              <button onClick={() => setError(null)}>Dismiss</button>
            </div>
          )}
          
          {loading && (
            <div className="loading-overlay">
              <div className="spinner"></div>
              <p>Analyzing lawn area... This may take 30-60 seconds</p>
            </div>
          )}
          
          <ResultsDisplay 
            results={results} 
            onNewAnalysis={handleNewAnalysis}
          />
        </div>
      </div>

      <footer className="app-footer">
        <p>Powered by FLAIR-INC ML Model | Google Maps API</p>
      </footer>
    </div>
  );
}

export default App;
