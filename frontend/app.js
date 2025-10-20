/**
 * Lawn Analysis Frontend Application
 * Handles map interaction, drawing, and API communication
 */

// Configuration
const API_BASE_URL = 'http://localhost:8000';
const DEFAULT_CENTER = [39.9526, -86.0569]; // Indianapolis, IN
const DEFAULT_ZOOM = 13;

// State
let map = null;
let drawnItems = null;
let currentPolygon = null;
let drawControl = null;

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
 * Initialize the application
 */
function init() {
    console.log('Initializing Lawn Analysis App...');
    initMap();
    initDrawControls();
    initEventListeners();
    console.log('App initialized successfully');
}

/**
 * Initialize Leaflet map with ESRI World Imagery tiles
 */
function initMap() {
    // Create map
    map = L.map('map', {
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        zoomControl: true
    });

    // Add ESRI World Imagery tile layer (free, no API key required!)
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        maxZoom: 19,
        minZoom: 3
    }).addTo(map);

    // Initialize feature group for drawn items
    drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    // Add geocoding (address search) control
    const geocoder = L.Control.geocoder({
        defaultMarkGeocode: false,
        placeholder: 'Search for address...',
        errorMessage: 'Address not found. Try being more specific.',
        position: 'topleft',
        geocoder: L.Control.Geocoder.nominatim({
            geocodingQueryParams: {
                'accept-language': 'en',
                countrycodes: 'us,ca'  // US and Canada
            }
        })
    })
    .on('markgeocode', function(e) {
        const latlng = e.geocode.center;
        const bbox = e.geocode.bbox;
        
        console.log('Address found:', e.geocode.name, 'at', latlng);
        
        // Zoom to location with smooth animation
        if (bbox) {
            map.fitBounds([
                [bbox.getSouth(), bbox.getWest()],
                [bbox.getNorth(), bbox.getEast()]
            ], {
                maxZoom: 18,  // Good zoom for lawn analysis
                padding: [50, 50],
                animate: true,
                duration: 1.0
            });
        } else {
            map.setView(latlng, 18, {
                animate: true,
                duration: 1.0
            });
        }
        
        // Add temporary marker to show location
        const marker = L.marker(latlng, {
            icon: L.icon({
                iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41]
            })
        }).addTo(map);
        
        // Remove marker after 3 seconds
        setTimeout(() => {
            map.removeLayer(marker);
        }, 3000);
    })
    .addTo(map);

    console.log('Map initialized with ESRI World Imagery tiles and address search');
}

/**
 * Initialize Leaflet Draw controls
 */
function initDrawControls() {
    // Configure draw control
    drawControl = new L.Control.Draw({
        position: 'topleft',
        draw: {
            polygon: {
                allowIntersection: false,
                showArea: true,
                metric: ['km', 'm'],
                imperial: ['mi', 'ft'],
                shapeOptions: {
                    color: '#10b981',
                    weight: 3,
                    fillOpacity: 0.2
                }
            },
            polyline: false,
            rectangle: false,
            circle: false,
            marker: false,
            circlemarker: false
        },
        edit: {
            featureGroup: drawnItems,
            remove: true
        }
    });

    map.addControl(drawControl);

    // Event listeners for drawing
    map.on(L.Draw.Event.CREATED, handlePolygonCreated);
    map.on(L.Draw.Event.DELETED, handlePolygonDeleted);
    map.on(L.Draw.Event.EDITED, handlePolygonEdited);

    console.log('Draw controls initialized');
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
function handlePolygonCreated(e) {
    const layer = e.layer;
    
    // Remove existing polygon if any
    if (currentPolygon) {
        drawnItems.removeLayer(currentPolygon);
    }
    
    // Add new polygon
    currentPolygon = layer;
    drawnItems.addLayer(layer);
    
    // Enable buttons
    elements.analyzeBtn.disabled = false;
    elements.clearBtn.disabled = false;
    
    // Hide instructions
    hideInstructions();
    
    console.log('Polygon created:', layer.toGeoJSON());
}

/**
 * Handle polygon deletion
 */
function handlePolygonDeleted(e) {
    currentPolygon = null;
    elements.analyzeBtn.disabled = true;
    elements.clearBtn.disabled = true;
    console.log('Polygon deleted');
}

/**
 * Handle polygon editing
 */
function handlePolygonEdited(e) {
    console.log('Polygon edited');
}

/**
 * Handle clear button
 */
function handleClear() {
    if (currentPolygon) {
        drawnItems.removeLayer(currentPolygon);
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
    
    // Check if polygon is properly closed
    const first = coords[0];
    const last = coords[coords.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
        // Auto-close if needed
        coords.push([...first]);
        console.log('Auto-closed polygon');
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

    // Get GeoJSON
    const geojson = {
        type: 'FeatureCollection',
        features: [currentPolygon.toGeoJSON()]
    };

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
                zoom: 18
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
 * Format number with commas
 */
function formatNumber(num, decimals = 0) {
    if (num === null || num === undefined) return '-';
    return num.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

