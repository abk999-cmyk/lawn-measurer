"""
Image Fetcher Module
Downloads and stitches satellite tiles from ESRI World Imagery (free, no API key required)
"""
import os
import math
import requests
from PIL import Image
from io import BytesIO
import logging
from typing import Tuple, Dict, List
import hashlib
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ESRI World Imagery tile service (free, no API key)
TILE_URL_TEMPLATE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE_SIZE = 256  # Standard tile size in pixels


class TileFetcher:
    """Fetches and stitches satellite imagery tiles for a given polygon"""
    
    def __init__(self, cache_dir: str = "./tile_cache"):
        """
        Initialize TileFetcher
        
        Args:
            cache_dir: Directory to cache downloaded tiles
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        logger.info(f"TileFetcher initialized with cache dir: {cache_dir}")
    
    @staticmethod
    def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """
        Convert latitude/longitude to tile coordinates at given zoom level
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            zoom: Zoom level (0-20)
            
        Returns:
            Tuple of (tile_x, tile_y)
        """
        n = 2.0 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return x, y
    
    @staticmethod
    def tile_to_latlon(x: int, y: int, zoom: int) -> Tuple[float, float]:
        """
        Convert tile coordinates to latitude/longitude (northwest corner)
        
        Args:
            x: Tile X coordinate
            y: Tile Y coordinate
            zoom: Zoom level
            
        Returns:
            Tuple of (lat, lon)
        """
        n = 2.0 ** zoom
        lon = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat = math.degrees(lat_rad)
        return lat, lon
    
    def get_tiles_for_bbox(self, min_lon: float, min_lat: float, 
                           max_lon: float, max_lat: float, zoom: int) -> List[Tuple[int, int, int]]:
        """
        Get all tile coordinates covering a bounding box
        
        Args:
            min_lon, min_lat, max_lon, max_lat: Bounding box coordinates
            zoom: Zoom level
            
        Returns:
            List of (x, y, zoom) tuples
        """
        # Get tile coordinates for corners
        x1, y1 = self.latlon_to_tile(max_lat, min_lon, zoom)  # Top-left
        x2, y2 = self.latlon_to_tile(min_lat, max_lon, zoom)  # Bottom-right
        
        # Ensure proper ordering
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)
        
        tiles = []
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tiles.append((x, y, zoom))
        
        logger.info(f"Bounding box at zoom {zoom} requires {len(tiles)} tiles ({x_max-x_min+1}x{y_max-y_min+1} grid)")
        return tiles
    
    def download_tile(self, x: int, y: int, z: int) -> Image.Image:
        """
        Download a single tile, with caching
        
        Args:
            x, y, z: Tile coordinates
            
        Returns:
            PIL Image of the tile
        """
        # Check cache first
        cache_path = os.path.join(self.cache_dir, f"tile_{z}_{y}_{x}.png")
        if os.path.exists(cache_path):
            logger.debug(f"Tile {z}/{y}/{x} found in cache")
            return Image.open(cache_path)
        
        # Download tile
        url = TILE_URL_TEMPLATE.format(z=z, y=y, x=x)
        try:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'LawnAnalysisApp/1.0'
            })
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content))
            
            # Cache the tile
            img.save(cache_path, 'PNG')
            logger.debug(f"Tile {z}/{y}/{x} downloaded and cached")
            
            return img
        except Exception as e:
            logger.error(f"Failed to download tile {z}/{y}/{x}: {e}")
            # Return a blank tile as fallback
            return Image.new('RGB', (TILE_SIZE, TILE_SIZE), color=(200, 200, 200))
    
    def stitch_tiles(self, tiles: List[Tuple[int, int, int]]) -> Tuple[Image.Image, Dict]:
        """
        Download and stitch tiles into a single image
        
        Args:
            tiles: List of (x, y, zoom) tuples
            
        Returns:
            Tuple of (stitched_image, metadata_dict)
        """
        if not tiles:
            raise ValueError("No tiles to stitch")
        
        # Get zoom level (should be same for all tiles)
        zoom = tiles[0][2]
        
        # Find bounds of tile grid
        x_coords = [t[0] for t in tiles]
        y_coords = [t[1] for t in tiles]
        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)
        
        # Calculate output image size
        width = (x_max - x_min + 1) * TILE_SIZE
        height = (y_max - y_min + 1) * TILE_SIZE
        
        logger.info(f"Stitching {len(tiles)} tiles into {width}x{height} image")
        
        # Create output image
        stitched = Image.new('RGB', (width, height))
        
        # Download and place each tile
        for x, y, z in tiles:
            tile_img = self.download_tile(x, y, z)
            
            # Calculate position in stitched image
            px = (x - x_min) * TILE_SIZE
            py = (y - y_min) * TILE_SIZE
            
            stitched.paste(tile_img, (px, py))
        
        # Calculate geographic bounds of stitched image
        top_lat, left_lon = self.tile_to_latlon(x_min, y_min, zoom)
        bottom_lat, right_lon = self.tile_to_latlon(x_max + 1, y_max + 1, zoom)
        
        metadata = {
            "zoom": zoom,
            "tile_bounds": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
            "geo_bounds": {
                "top_left": {"lat": top_lat, "lon": left_lon},
                "bottom_right": {"lat": bottom_lat, "lon": right_lon},
                "bbox": [left_lon, bottom_lat, right_lon, top_lat]
            },
            "image_size": {"width": width, "height": height}
        }
        
        return stitched, metadata
    
    def crop_to_bbox(self, image: Image.Image, metadata: Dict, 
                     target_bbox: List[float]) -> Tuple[Image.Image, Dict]:
        """
        Crop stitched image to exact target bounding box
        
        Args:
            image: Stitched tile image
            metadata: Metadata from stitch_tiles
            target_bbox: [min_lon, min_lat, max_lon, max_lat]
            
        Returns:
            Tuple of (cropped_image, updated_metadata)
        """
        img_bbox = metadata["geo_bounds"]["bbox"]
        img_width, img_height = metadata["image_size"]["width"], metadata["image_size"]["height"]
        
        # Calculate pixel coordinates for target bbox
        min_lon, min_lat, max_lon, max_lat = target_bbox
        img_min_lon, img_min_lat, img_max_lon, img_max_lat = img_bbox
        
        # Convert to pixel coordinates
        x1 = int((min_lon - img_min_lon) / (img_max_lon - img_min_lon) * img_width)
        x2 = int((max_lon - img_min_lon) / (img_max_lon - img_min_lon) * img_width)
        y1 = int((img_max_lat - max_lat) / (img_max_lat - img_min_lat) * img_height)
        y2 = int((img_max_lat - min_lat) / (img_max_lat - img_min_lat) * img_height)
        
        # Ensure bounds are valid
        x1, x2 = max(0, min(x1, x2)), min(img_width, max(x1, x2))
        y1, y2 = max(0, min(y1, y2)), min(img_height, max(y1, y2))
        
        # Crop image
        cropped = image.crop((x1, y1, x2, y2))
        
        # Update metadata
        cropped_metadata = {
            **metadata,
            "geo_bounds": {
                "top_left": {"lat": max_lat, "lon": min_lon},
                "bottom_right": {"lat": min_lat, "lon": max_lon},
                "bbox": target_bbox
            },
            "image_size": {"width": cropped.width, "height": cropped.height},
            "crop_applied": True
        }
        
        logger.info(f"Cropped image to {cropped.width}x{cropped.height}")
        return cropped, cropped_metadata
    
    def fetch_image_for_polygon(self, geojson: Dict, output_path: str, 
                                zoom: int = 18) -> Tuple[str, Dict]:
        """
        Main method: Fetch satellite image for a polygon and save it
        
        Args:
            geojson: GeoJSON FeatureCollection with polygon
            output_path: Path to save the final image
            zoom: Zoom level (default 18 for ~1m/pixel resolution)
            
        Returns:
            Tuple of (image_path, bounds_dict)
        """
        logger.info("=== Starting image fetch for polygon ===")
        
        # Extract polygon coordinates
        try:
            features = geojson.get("features", [])
            if not features:
                raise ValueError("No features in GeoJSON")
            
            coords = features[0]["geometry"]["coordinates"][0]
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            
            # Calculate bounding box with small padding
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)
            
            # Add 5% padding
            lon_pad = (max_lon - min_lon) * 0.05
            lat_pad = (max_lat - min_lat) * 0.05
            min_lon -= lon_pad
            max_lon += lon_pad
            min_lat -= lat_pad
            max_lat += lat_pad
            
            logger.info(f"Bounding box: [{min_lon:.6f}, {min_lat:.6f}, {max_lon:.6f}, {max_lat:.6f}]")
            
        except Exception as e:
            logger.error(f"Failed to extract polygon coordinates: {e}")
            raise ValueError(f"Invalid GeoJSON: {e}")
        
        # Get tiles covering the bounding box
        tiles = self.get_tiles_for_bbox(min_lon, min_lat, max_lon, max_lat, zoom)
        
        if len(tiles) > 100:
            logger.warning(f"Large number of tiles ({len(tiles)}). Consider lowering zoom level.")
        
        # Stitch tiles
        stitched_img, metadata = self.stitch_tiles(tiles)
        
        # Crop to exact bounding box
        target_bbox = [min_lon, min_lat, max_lon, max_lat]
        final_img, final_metadata = self.crop_to_bbox(stitched_img, metadata, target_bbox)
        
        # Save image
        final_img.save(output_path, 'JPEG', quality=95)
        logger.info(f"Image saved to: {output_path}")
        
        # Return in format compatible with run.py
        bounds_dict = {
            "top_left": final_metadata["geo_bounds"]["top_left"],
            "bottom_right": final_metadata["geo_bounds"]["bottom_right"],
            "bbox": final_metadata["geo_bounds"]["bbox"]
        }
        
        logger.info("=== Image fetch complete ===")
        return output_path, bounds_dict


# Quick test function
if __name__ == "__main__":
    # Test with a small polygon
    test_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-86.064739, 39.937661],
                    [-86.064559, 39.937655],
                    [-86.064577, 39.937138],
                    [-86.064761, 39.937139],
                    [-86.064739, 39.937661]
                ]]
            },
            "properties": {}
        }]
    }
    
    fetcher = TileFetcher()
    img_path, bounds = fetcher.fetch_image_for_polygon(test_geojson, "test_output.jpg", zoom=18)
    print(f"Success! Image saved to {img_path}")
    print(f"Bounds: {bounds}")

