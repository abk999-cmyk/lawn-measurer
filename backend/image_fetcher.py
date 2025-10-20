"""
Google Maps Static API Image Fetcher
Fetches high-resolution satellite imagery using Google Maps Static API
"""
import requests
import math
from PIL import Image
from io import BytesIO
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class GoogleStaticMapFetcher:
    """Fetch satellite imagery using Google Maps Static API"""
    
    def __init__(self, api_key, cache_dir="./tile_cache"):
        """
        Initialize the Google Maps Static API fetcher
        
        Args:
            api_key: Google Maps API key
            cache_dir: Directory for caching images (optional)
        """
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api/staticmap"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        logger.info("Initialized Google Static Map Fetcher")
    
    def fetch_image_for_polygon(self, geojson, zoom=19):
        """
        Fetch high-resolution satellite image for polygon area
        
        Args:
            geojson: GeoJSON FeatureCollection with polygon
            zoom: Zoom level (1-21, default 19 for lawn detail)
        
        Returns:
            tuple: (PIL.Image, bounds_dict)
        """
        logger.info("=== Starting Google Maps Static API image fetch ===")
        
        # Extract polygon bounds
        coords = geojson['features'][0]['geometry']['coordinates'][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        
        center_lat = (min(lats) + max(lats)) / 2
        center_lon = (min(lons) + max(lons)) / 2
        
        logger.info(f"Center: {center_lat:.6f}, {center_lon:.6f}")
        logger.info(f"Zoom level: {zoom}")
        
        # Google Static Maps API parameters
        # Scale 2 = high DPI (retina), max 640x640 → actual 1280x1280 pixels
        params = {
            'center': f'{center_lat},{center_lon}',
            'zoom': zoom,
            'size': '640x640',  # Max size for free tier
            'scale': 2,  # High DPI (doubles resolution to 1280x1280)
            'maptype': 'satellite',
            'format': 'png',
            'key': self.api_key
        }
        
        logger.info(f"Fetching image at {params['size']} with scale={params['scale']}")
        logger.info(f"Expected actual resolution: 1280x1280 pixels")
        
        # Fetch image from Google
        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Check for API errors in response
            content_type = response.headers.get('content-type', '')
            if 'image' not in content_type:
                logger.error(f"Unexpected content type: {content_type}")
                logger.error(f"Response: {response.text[:500]}")
                raise ValueError(
                    "Google Maps API returned non-image response. "
                    "Check API key, quotas, and ensure Maps Static API is enabled."
                )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch image from Google Maps: {e}")
            raise ValueError(f"Failed to fetch satellite imagery: {e}")
        
        # Load image
        image = Image.open(BytesIO(response.content))
        logger.info(f"Image fetched successfully: {image.size[0]}x{image.size[1]} pixels")
        
        # Calculate geographic bounds
        # Google Maps uses Web Mercator projection
        # Formula: meters_per_pixel = 156543.03392 * cos(lat) / (2 ^ zoom)
        # This is the resolution at the center of the image
        meters_per_pixel = (156543.03392 * math.cos(center_lat * math.pi / 180)) / (2 ** zoom)
        
        # Image dimensions in meters
        width_m = image.width * meters_per_pixel
        height_m = image.height * meters_per_pixel
        
        logger.info(f"Resolution: {meters_per_pixel:.3f} m/pixel")
        logger.info(f"Image covers {width_m:.1f}m x {height_m:.1f}m")
        
        # Convert meters to degrees
        # 1 degree latitude = ~111,320 meters (constant)
        # 1 degree longitude = ~111,320 * cos(lat) meters (varies by latitude)
        lat_deg_per_m = 1.0 / 111320.0
        lon_deg_per_m = 1.0 / (111320.0 * math.cos(center_lat * math.pi / 180))
        
        # Calculate corner coordinates
        # Image is centered on center_lat, center_lon
        half_width_deg = (width_m / 2) * lon_deg_per_m
        half_height_deg = (height_m / 2) * lat_deg_per_m
        
        bounds = {
            "top_left": {
                "lat": center_lat + half_height_deg,
                "lon": center_lon - half_width_deg
            },
            "bottom_right": {
                "lat": center_lat - half_height_deg,
                "lon": center_lon + half_width_deg
            },
            "bbox": [
                center_lon - half_width_deg,  # min_lon (west)
                center_lat - half_height_deg,  # min_lat (south)
                center_lon + half_width_deg,  # max_lon (east)
                center_lat + half_height_deg   # max_lat (north)
            ]
        }
        
        logger.info(f"Bounds: [{bounds['bbox'][0]:.6f}, {bounds['bbox'][1]:.6f}, "
                   f"{bounds['bbox'][2]:.6f}, {bounds['bbox'][3]:.6f}]")
        logger.info("=== Image fetch complete ===")
        
        return image, bounds
