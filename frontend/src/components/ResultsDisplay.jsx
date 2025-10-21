import { useState } from 'react';

function ResultsDisplay({ results, onNewAnalysis }) {
  const [showMetrics, setShowMetrics] = useState(true);

  if (!results) {
    return (
      <div className="results-placeholder">
        <h2>Lawn Analysis Results</h2>
        <p>Results will appear here after analysis</p>
      </div>
    );
  }

  const { best_overlay_url, front_back_sides_url, metrics } = results.results;
  const { areas_ft2, areas_m2 } = metrics;

  const downloadImage = (url, filename) => {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadAllResults = () => {
    downloadImage(best_overlay_url, 'lawn_overlay.png');
    setTimeout(() => {
      downloadImage(front_back_sides_url, 'yard_zones.png');
    }, 500);
    
    // Open metrics JSON
    const metricsJson = JSON.stringify(metrics, null, 2);
    const blob = new Blob([metricsJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'yard_metrics.json';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="results-display">
      <div className="results-header">
        <h2>Analysis Results</h2>
        <div className="results-actions">
          <button onClick={downloadAllResults} className="download-button">
            Download Results
          </button>
          <button onClick={onNewAnalysis} className="new-analysis-button">
            New Analysis
          </button>
        </div>
      </div>

      <div className="results-images">
        <div className="result-image-container">
          <h3>Lawn Detection</h3>
          <img src={best_overlay_url} alt="Lawn overlay" className="result-image" />
        </div>
        
        <div className="result-image-container">
          <h3>Yard Zones</h3>
          <img src={front_back_sides_url} alt="Yard zones" className="result-image" />
          <div className="zone-legend">
            <div className="legend-item">
              <span className="legend-color" style={{backgroundColor: '#00c800'}}></span>
              <span>Front</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{backgroundColor: '#0000c8'}}></span>
              <span>Back</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{backgroundColor: '#ffa500'}}></span>
              <span>Left</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{backgroundColor: '#c80000'}}></span>
              <span>Right</span>
            </div>
          </div>
        </div>
      </div>

      <div className="metrics-section">
        <div className="metrics-header">
          <h3>Area Measurements</h3>
          <button 
            onClick={() => setShowMetrics(!showMetrics)} 
            className="toggle-button"
          >
            {showMetrics ? 'Hide' : 'Show'}
          </button>
        </div>
        
        {showMetrics && (
          <table className="metrics-table">
            <thead>
              <tr>
                <th>Zone</th>
                <th>Area (ft²)</th>
                <th>Area (m²)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Front Yard</td>
                <td>{areas_ft2.front.toFixed(1)}</td>
                <td>{areas_m2.front.toFixed(1)}</td>
              </tr>
              <tr>
                <td>Back Yard</td>
                <td>{areas_ft2.back.toFixed(1)}</td>
                <td>{areas_m2.back.toFixed(1)}</td>
              </tr>
              <tr>
                <td>Left Side</td>
                <td>{areas_ft2.left.toFixed(1)}</td>
                <td>{areas_m2.left.toFixed(1)}</td>
              </tr>
              <tr>
                <td>Right Side</td>
                <td>{areas_ft2.right.toFixed(1)}</td>
                <td>{areas_m2.right.toFixed(1)}</td>
              </tr>
              <tr>
                <td>Total Sides</td>
                <td>{areas_ft2.sides.toFixed(1)}</td>
                <td>{areas_m2.sides.toFixed(1)}</td>
              </tr>
              <tr className="total-row">
                <td><strong>Total Lawn</strong></td>
                <td><strong>{areas_ft2.total_lawn.toFixed(1)}</strong></td>
                <td><strong>{areas_m2.total_lawn.toFixed(1)}</strong></td>
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default ResultsDisplay;

