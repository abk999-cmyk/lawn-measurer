import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000';

/**
 * Analyze property lawn from image and GeoJSON
 * @param {Blob} imageBlob - Satellite image blob
 * @param {Object} geojson - GeoJSON object with polygon
 * @param {string} address - Property address
 * @returns {Promise} Analysis results
 */
export const analyzeProperty = async (imageBlob, geojson, address) => {
  try {
    const formData = new FormData();
    formData.append('image', imageBlob, 'satellite.jpg');
    formData.append('geojson', JSON.stringify(geojson));
    formData.append('address', address);

    const response = await axios.post(`${API_BASE_URL}/api/analyze`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 120000, // 2 minutes timeout
    });

    return response.data;
  } catch (error) {
    console.error('Analysis API error:', error);
    if (error.response) {
      throw new Error(error.response.data.error || 'Analysis failed');
    } else if (error.request) {
      throw new Error('No response from server. Please ensure the backend is running.');
    } else {
      throw new Error('Error setting up the request: ' + error.message);
    }
  }
};

/**
 * Get result image URL
 * @param {string} jobId - Job UUID
 * @param {string} filename - Image filename
 * @returns {string} Full URL to the image
 */
export const getResultImageUrl = (jobId, filename) => {
  return `${API_BASE_URL}/api/results/${jobId}/${filename}`;
};

/**
 * Health check API
 * @returns {Promise} Health status
 */
export const healthCheck = async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/health`);
    return response.data;
  } catch (error) {
    console.error('Health check failed:', error);
    throw error;
  }
};

