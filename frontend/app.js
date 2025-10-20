/**
 * Lawn Analysis Frontend Application - Google Maps Version
 * Handles map interaction, drawing, and API communication
 */

// Configuration
const API_BASE_URL = 'http://localhost:8000';
const DEFAULT_CENTER = { lat: 39.9526, lng: -86.0569 }; // Indianapolis, IN
const DEFAULT_ZOOM = 13;

// State
let map = null;
let currentPolygon = null;
let drawingManager = null;

// DOM Elements
const elements = {
    mapContainer: document.getElementById('map'),
    instructions: document.getElementById('instructions'),
    closeInstructions: document.getElementById('close-instructions'),
    showInstructions: document.getElementById('show-instructions-btn'),
    analyzeBtn: document.getElementById('analyze-btn'),
    clearBtn: document.getElementById('clear-btn'),
    newAnalysisBtn: document.getElementById('new-analysis-btn'),
    resultsPanel: document.getElementById('results-panel'),
    errorPanel: document.getElementById('error-panel'),
    dismissError: document.getElementById('dismiss-error-btn'),
    // Results elements
    totalAreaFt: document.getElementById('total-area-ft'),
    totalAreaM: document.getElementById('total-area-m'),
    confidenceScore: document.getElementById('confidence-score'),
    confidenceGrade: document.getElementById('confidence-grade'),
    zoneFront: document.getElementById('zone-front'),
    zoneBack: document.getElementById('zone-back'),
    zoneLeft: document.getElementById('zone-left'),
    zoneRight: document.getElementById('zone-right'),
    zoneSides: document.getElementById('zone-sides'),
    overlayImage: document.getElementById('overlay-image'),
    zonesImage: document.getElementById('zones-image'),
    errorMessage: document.getElementById('error-message')
};

/**
 * Initialize the application (called by Google Maps API)
 */
function initMap() {
    console.log('Initializing Lawn Analysis App with Google Maps...');
    
    // Initialize map
    map = new google.maps.Map(document.getElementById('map'), {
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        mapTypeId: 'satellite',  // Satellite view for lawn analysis
        tilt: 0,  // Disable 3D tilt
        mapTypeControl: true,
        mapTypeControlOptions: {
            style: google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
            position: google.maps.ControlPosition.TOP_RIGHT,
            mapTypeIds: ['satellite', 'hybrid', 'roadmap']
        },
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
        gestureHandling: 'greedy'
    });

    // Initialize address search
    initAddressSearch();
    
    // Initialize drawing tools
    initDrawingManager();
    
    // Initialize event listeners
    initEventListeners();
    
    console.log('App initialized successfully');
}

/**
 * Initialize Google Places Autocomplete for address search
 */
function initAddressSearch() {
    // Create search input box
    const searchBox = document.createElement('input');
    searchBox.type = 'text';
    searchBox.placeholder = 'Search for address...';
    searchBox.classList.add('map-search-box');
    
    // Add to map controls
    map.controls[google.maps.ControlPosition.TOP_LEFT].push(searchBox);
    
    // Initialize Places Autocomplete
    const autocomplete = new google.maps.places.Autocomplete(searchBox, {
        types: ['address'],
        componentRestrictions: { country: ['us', 'ca'] },
        fields: ['formatted_address', 'geometry', 'name']
    });
    
    // Bind to map bounds
    autocomplete.bindTo('bounds', map);
    
    // Handle place selection
    autocomplete.addListener('place_changed', function() {
        const place = autocomplete.getPlace();
        
        if (!place.geometry || !place.geometry.location) {
            showNotification('Address not found. Please try a more specific address.', 'error');
            return;
        }
        
        console.log('Address selected:', place.formatted_address);
        
        // Navigate to location
        if (place.geometry.viewport) {
            map.fitBounds(place.geometry.viewport);
        } else {
            map.setCenter(place.geometry.location);
            map.setZoom(18);  // Good zoom for lawn analysis
        }
        
        // Add temporary marker
        const marker = new google.maps.Marker({
            map: map,
            position: place.geometry.location,
            animation: google.maps.Animation.DROP,
            title: place.formatted_address
        });
        
        // Remove marker after 5 seconds
        setTimeout(() => marker.setMap(null), 5000);
        
        showNotification(`📍 ${place.formatted_address}`, 'success', 3000);
    });
    
    console.log('Address search initialized');
}

/**
 * Initialize Google Maps Drawing Manager
 */
function initDrawingManager() {
    drawingManager = new google.maps.drawing.DrawingManager({
        drawingMode: null,
        drawingControl: true,
        drawingControlOptions: {
            position: google.maps.ControlPosition.TOP_CENTER,
            drawingModes: [google.maps.drawing.OverlayType.POLYGON]
        },
        polygonOptions: {
            fillColor: '#10b981',
            fillOpacity: 0.2,
            strokeWeight: 3,
            strokeColor: '#10b981',
            clickable: true,
            editable: true,
            zIndex: 1
        }
    });
    
    drawingManager.setMap(map);
    
    // Listen for polygon completion
    google.maps.event.addListener(drawingManager, 'overlaycomplete', function(event) {
        if (event.type === google.maps.drawing.OverlayType.POLYGON) {
            handlePolygonCreated(event.overlay);
        }
    });
    
    console.log('Drawing manager initialized');
}

/**
 * Initialize event listeners
 */
function initEventListeners() {
    elements.closeInstructions.addEventListener('click', hideInstructions);
    elements.showInstructions.addEventListener('click', showInstructions);
    elements.analyzeBtn.addEventListener('click', handleAnalyze);
    elements.clearBtn.addEventListener('click', handleClear);
    elements.newAnalysisBtn.addEventListener('click', handleNewAnalysis);
    elements.dismissError.addEventListener('click', hideError);

    console.log('Event listeners initialized');
}

/**
 * Handle polygon creation
 */
function handlePolygonCreated(polygon) {
    // Remove existing polygon if any
    if (currentPolygon) {
        currentPolygon.setMap(null);
    }
    
    currentPolygon = polygon;
    
    // Enable buttons
    elements.analyzeBtn.disabled = false;
    elements.clearBtn.disabled = false;
    
    // Switch to hand tool after drawing
    drawingManager.setDrawingMode(null);
    
    // Hide instructions
    hideInstructions();
    
    console.log('Polygon created with', polygon.getPath().getLength(), 'points');
}

/**
 * Convert Google Maps Polygon to GeoJSON
 */
function polygonToGeoJSON(polygon) {
    const path = polygon.getPath();
    const coordinates = [];
    
    // Extract coordinates
    for (let i = 0; i < path.getLength(); i++) {
        const point = path.getAt(i);
        coordinates.push([point.lng(), point.lat()]);  // [lon, lat] for GeoJSON
    }
    
    // Close the polygon if not already closed
    if (coordinates.length > 0) {
        const first = coordinates[0];
        const last = coordinates[coordinates.length - 1];
        if (first[0] !== last[0] || first[1] !== last[1]) {
            coordinates.push([...first]);
        }
    }
    
    // Create GeoJSON FeatureCollection
    return {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            geometry: {
                type: 'Polygon',
                coordinates: [coordinates]
            },
            properties: {}
        }]
    };
}

/**
 * Handle clear button
 */
function handleClear() {
    if (currentPolygon) {
        currentPolygon.setMap(null);
        currentPolygon = null;
    }
    elements.analyzeBtn.disabled = true;
    elements.clearBtn.disabled = true;
}

/**
 * Validate polygon geometry before sending to backend
 */
function validatePolygon(geojson) {
    const coords = geojson.features[0].geometry.coordinates[0];
    
    // Check minimum points (at least 4: 3 distinct + closing point)
    if (coords.length < 4) {
        throw new Error('Polygon must have at least 3 points. Please draw a larger area.');
    }
    
    // Check for reasonable size (not too small)
    const lons = coords.map(c => c[0]);
    const lats = coords.map(c => c[1]);
    const width = Math.max(...lons) - Math.min(...lons);
    const height = Math.max(...lats) - Math.min(...lats);
    
    // Rough check: ~10m minimum at mid-latitudes (0.0001 degrees ≈ 11m)
    if (width < 0.00009 || height < 0.00009) {
        throw new Error('Polygon is too small. Please draw a larger area (at least 10m x 10m).');
    }
    
    // Check for extremely large polygons (more than ~5km on a side)
    if (width > 0.05 || height > 0.05) {
        throw new Error('Polygon is too large. Please draw a smaller area (maximum ~5km x 5km).');
    }
    
    // Check for duplicate consecutive points (can cause topology issues)
    for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const curr = coords[i];
        if (prev[0] === curr[0] && prev[1] === curr[1] && i < coords.length - 1) {
            throw new Error('Polygon has duplicate points. Please redraw more carefully.');
        }
    }
    
    return true;
}

/**
 * Handle analyze button
 */
async function handleAnalyze() {
    if (!currentPolygon) {
        showError('Please draw a polygon on the map first.');
        return;
    }

    // Convert to GeoJSON
    const geojson = polygonToGeoJSON(currentPolygon);

    // Validate polygon before sending to backend
    try {
        validatePolygon(geojson);
    } catch (error) {
        showError(error.message);
        return;
    }

    console.log('Starting analysis...', geojson);

    // Show loading state
    setLoadingState(true);

    try {
        // Call API
        const response = await fetch(`${API_BASE_URL}/api/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                geojson: geojson,
                zoom: 19  // Google Maps Static API zoom level
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        console.log('Analysis result:', result);

        if (result.success) {
            displayResults(result);
        } else {
            throw new Error(result.error || 'Analysis failed');
        }

    } catch (error) {
        console.error('Analysis error:', error);
        showError(`Analysis failed: ${error.message}`);
    } finally {
        setLoadingState(false);
    }
}

/**
 * Display analysis results
 */
function displayResults(result) {
    // Hide map, show results
    document.getElementById('map-container').style.display = 'none';
    elements.resultsPanel.classList.remove('hidden');
    elements.errorPanel.classList.add('hidden');

    // Populate metrics
    elements.totalAreaFt.textContent = formatNumber(result.lawn_area_ft2, 0);
    elements.totalAreaM.textContent = formatNumber(result.lawn_area_m2, 1);
    elements.confidenceScore.textContent = (result.confidence_score * 100).toFixed(0) + '%';
    
    // Set confidence badge
    const grade = result.confidence_grade || 'D';
    elements.confidenceGrade.textContent = grade;
    elements.confidenceGrade.className = 'badge grade-' + grade;

    // Populate zones
    if (result.zones_metrics) {
        elements.zoneFront.textContent = formatNumber(result.zones_metrics.front_ft2, 0);
        elements.zoneBack.textContent = formatNumber(result.zones_metrics.back_ft2, 0);
        elements.zoneLeft.textContent = formatNumber(result.zones_metrics.left_ft2, 0);
        elements.zoneRight.textContent = formatNumber(result.zones_metrics.right_ft2, 0);
        elements.zoneSides.textContent = formatNumber(result.zones_metrics.sides_ft2, 0);
    }

    // Display images
    if (result.overlay_base64) {
        elements.overlayImage.src = `data:image/png;base64,${result.overlay_base64}`;
    }
    if (result.zones_overlay_base64) {
        elements.zonesImage.src = `data:image/png;base64,${result.zones_overlay_base64}`;
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });

    console.log('Results displayed successfully');
}

/**
 * Handle new analysis
 */
function handleNewAnalysis() {
    // Show map, hide results
    document.getElementById('map-container').style.display = 'block';
    elements.resultsPanel.classList.add('hidden');
    
    // Clear polygon
    handleClear();
    
    // Show instructions again
    showInstructions();
}

/**
 * Show error message
 */
function showError(message) {
    elements.errorMessage.textContent = message;
    document.getElementById('map-container').style.display = 'none';
    elements.resultsPanel.classList.add('hidden');
    elements.errorPanel.classList.remove('hidden');
}

/**
 * Hide error message
 */
function hideError() {
    elements.errorPanel.classList.add('hidden');
    document.getElementById('map-container').style.display = 'block';
}

/**
 * Show instructions overlay
 */
function showInstructions() {
    elements.instructions.classList.remove('hidden');
}

/**
 * Hide instructions overlay
 */
function hideInstructions() {
    elements.instructions.classList.add('hidden');
}

/**
 * Set loading state
 */
function setLoadingState(isLoading) {
    const btnText = elements.analyzeBtn.querySelector('.btn-text');
    const spinner = elements.analyzeBtn.querySelector('.spinner');
    
    if (isLoading) {
        btnText.textContent = 'Analyzing...';
        spinner.classList.remove('hidden');
        elements.analyzeBtn.disabled = true;
        elements.clearBtn.disabled = true;
    } else {
        btnText.textContent = 'Analyze Lawn';
        spinner.classList.add('hidden');
        elements.analyzeBtn.disabled = false;
        elements.clearBtn.disabled = false;
    }
}

/**
 * Show notification message
 */
function showNotification(message, type = 'info', duration = 4000) {
    const notif = document.createElement('div');
    notif.className = `notification notification-${type}`;
    notif.textContent = message;
    notif.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: ${type === 'error' ? '#dc3545' : type === 'warning' ? '#ffc107' : type === 'success' ? '#10b981' : '#17a2b8'};
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
        max-width: 350px;
        font-size: 14px;
    `;
    
    document.body.appendChild(notif);
    
    setTimeout(() => {
        notif.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notif.remove(), 300);
    }, duration);
}

/**
 * Format number with commas
 */
function formatNumber(num, decimals = 0) {
    if (num === null || num === undefined) return '-';
    return num.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log('DOM ready, waiting for Google Maps API...');
    });
} else {
    console.log('DOM already loaded, waiting for Google Maps API...');
}
