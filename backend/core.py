# -*- coding: utf-8 -*-
"""
Core Lawn Analysis Module
Refactored from run.py to be callable functions for API integration
"""
import os, sys, json, math, glob, subprocess, warnings
warnings.filterwarnings("ignore", category=UserWarning)

import torch, torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image, ImageDraw
import numpy as np, requests, matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt
import cv2, geopandas as gpd
import segmentation_models_pytorch as smp
from shapely.geometry import Polygon, Point, MultiPolygon, box
from shapely.geometry.polygon import orient as orient_polygon
from shapely.ops import unary_union
from shapely.errors import TopologicalError, GEOSException
from shapely import set_precision
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/analysis.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
MODEL_URL = "https://huggingface.co/IGNF/FLAIR-INC_rgb_12cl_resnet34-unet/resolve/main/FLAIR-INC_rgb_12cl_resnet34-unet_weights.pth"
TILE_SIZE, TILE_OVERLAP = 512, 64
PROB_THRESH_MIN, MIN_PATCH_AREA_M2 = 0.25, 2.0

# Precision grid size to avoid floating-point topology issues
# 1e-7 degrees ≈ 1cm at equator
PRECISION_GRID_SIZE = 1e-7

FLAIR_CLASSES_ALL = [
    'building','pervious surface','impervious surface','bare soil','water','coniferous',
    'deciduous','brushwood','vineyard','herbaceous','agricultural land','plowed land',
    'other','forest','swimming pool','snow','boat','ash','unclassified'
]
CLASS_TO_IDX = {n:i for i,n in enumerate(FLAIR_CLASSES_ALL)}
VEG_CLASSES = ['herbaceous','agricultural land','plowed land','brushwood','coniferous','deciduous','forest','pervious surface']

# Morphological operation variants (name, DILATE_M, CLOSE_M, SMOOTH_M)
VARIANTS = [
    ("t1-0.25-0.30-0.35", 0.25, 0.30, 0.35),
]


def download_file(url, dst):
    """Download file if not exists"""
    if not os.path.exists(dst):
        logger.info(f"Downloading {os.path.basename(dst)} ...")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for ch in r.iter_content(8192):
                    f.write(ch)
        logger.info(f"Download complete: {dst}")


def normalize_bbox(b):
    """Normalize bounding box coordinates"""
    min_lon,min_lat,max_lon,max_lat = b
    if max_lon < min_lon: min_lon,max_lon = max_lon,min_lon
    if max_lat < min_lat: min_lat,max_lat = max_lat,min_lat
    if abs(max_lon-min_lon) < 1e-12: max_lon += 1e-6
    if abs(max_lat-min_lat) < 1e-12: max_lat += 1e-6
    return [min_lon,min_lat,max_lon,max_lat]


def compute_bbox_from_polygon(coords):
    """Compute bounding box from polygon coordinates"""
    lons = [p[0] for p in coords]; lats = [p[1] for p in coords]
    mnx,mxx = min(lons),max(lons); mny,mxy = min(lats),max(lats)
    padx = (mxx-mnx)*0.01 or 1e-6; pady = (mxy-mny)*0.01 or 1e-6
    return [mnx-padx, mny-pady, mxx+padx, mxy+pady]


def normalize_aoi_geojson(gj):
    """Normalize and validate AOI GeoJSON with robust geometry repair and precision handling"""
    try:
        feat = gj['features'][0]
        coords = feat['geometry']['coordinates'][0]
        
        # Simplify if too many points (reduces topology risk)
        if len(coords) > 100:
            logger.info(f"Polygon has {len(coords)} points, auto-simplifying to reduce complexity")
            from shapely.geometry import LineString
            line = LineString(coords)
            line = line.simplify(0.00001, preserve_topology=True)
            coords = list(line.coords)
        
        # Create polygon with precision grid to avoid floating-point issues
        poly = Polygon(coords)
        poly = set_precision(poly, PRECISION_GRID_SIZE, mode='pointwise')
        
        # Multi-step geometry repair process
        if not poly.is_valid:
            logger.warning(f"Invalid geometry detected: {poly.is_valid_reason if hasattr(poly, 'is_valid_reason') else 'unknown'}")
            
            try:
                # Step 1: Try buffer(0) - fixes most topology issues
                poly = poly.buffer(0)
                poly = set_precision(poly, PRECISION_GRID_SIZE, mode='pointwise')
            except (TopologicalError, GEOSException) as e:
                logger.warning(f"buffer(0) raised exception: {e}")
            
            # Step 2: If still invalid, try simplify + buffer
            if not poly.is_valid:
                logger.warning("Buffer(0) failed, trying simplify")
                try:
                    poly = poly.simplify(0.0001, preserve_topology=False).buffer(0)
                    poly = set_precision(poly, PRECISION_GRID_SIZE, mode='pointwise')
                except (TopologicalError, GEOSException) as e:
                    logger.warning(f"Simplify+buffer raised exception: {e}")
            
            # Step 3: If still invalid, use convex hull as last resort
            if not poly.is_valid:
                logger.warning("Simplify failed, using convex hull (may lose precision)")
                try:
                    poly = poly.convex_hull
                    poly = set_precision(poly, PRECISION_GRID_SIZE, mode='pointwise')
                except (TopologicalError, GEOSException) as e:
                    logger.error(f"Even convex hull failed: {e}")
            
            # Step 4: Final validation
            if not poly.is_valid:
                raise ValueError(
                    "Unable to repair invalid polygon geometry. "
                    "Please redraw your polygon ensuring: "
                    "1) Lines don't cross each other, "
                    "2) The polygon is properly closed, "
                    "3) There are at least 3 distinct points."
                )
            
            logger.info("Geometry successfully repaired")
        
        # Orient polygon (wrapped in try-catch)
        try:
            poly = orient_polygon(poly, sign=1.0)
        except (TopologicalError, GEOSException) as e:
            logger.warning(f"orient_polygon failed: {e}, continuing with current orientation")
        
        # Calculate bounding box
        bbox_prop = feat.get('properties',{}).get('bbox') or compute_bbox_from_polygon(coords)
        bbox_prop = normalize_bbox(bbox_prop)
        min_lon,min_lat,max_lon,max_lat = bbox_prop
        
        # Clip to bounding box (wrapped in try-catch - this is where many errors occur)
        try:
            clipper = box(min_lon, min_lat, max_lon, max_lat)
            clipper = set_precision(clipper, PRECISION_GRID_SIZE, mode='pointwise')
            poly_clipped = poly.intersection(clipper)
            
            # Only use clipped version if it's valid
            if poly_clipped.is_valid and not poly_clipped.is_empty:
                poly = poly_clipped
            else:
                logger.warning("Intersection produced invalid/empty geometry, using original polygon")
        except (TopologicalError, GEOSException) as e:
            logger.warning(f"Intersection with clipper failed: {e}, using original polygon")
            # Continue with unclipped polygon
        
        # Handle MultiPolygon (take largest)
        if isinstance(poly, MultiPolygon): 
            poly = max(list(poly.geoms), key=lambda p: p.area)
        
        # Final validation
        if not poly.is_valid:
            logger.error("Final polygon is still invalid after all repairs")
            raise ValueError("Unable to create valid polygon geometry. Please try a simpler shape.")
        
        # Convert back to GeoJSON
        return {"type":"FeatureCollection","features":[{
            "type":"Feature",
            "geometry": json.loads(gpd.GeoSeries([poly], crs="EPSG:4326").to_json())["features"][0]["geometry"],
            "properties":{"bbox":[min_lon,min_lat,max_lon,max_lat]}
        }]}
        
    except (TopologicalError, GEOSException) as e:
        logger.error(f"Shapely topology error in normalize_aoi_geojson: {e}", exc_info=True)
        raise ValueError(
            "Unable to process polygon due to geometric complexity. "
            "Please try: 1) Redrawing with fewer points, "
            "2) Drawing a simpler shape, "
            "3) Avoiding self-intersecting lines."
        )
    except ValueError:
        # Re-raise ValueError (already formatted for user)
        raise
    except Exception as e:
        logger.error(f"Unexpected error in normalize_aoi_geojson: {e}", exc_info=True)
        raise ValueError(f"Failed to process polygon: {str(e)}")


def extract_bounds_and_aoi(gj):
    """Extract bounds and contour from normalized GeoJSON"""
    feat = gj['features'][0]; bbox = normalize_bbox(feat['properties']['bbox'])
    image_bounds = {"top_left":{"lat":bbox[3],"lon":bbox[0]}, "bottom_right":{"lat":bbox[1],"lon":bbox[2]}, "bbox":bbox}
    coords = feat['geometry']['coordinates'][0]
    contour = [{"lat":lat,"lon":lon} for lon,lat in coords]
    return image_bounds, contour


def meters_per_deg_lat(lat): return 111_320.0


def meters_per_deg_lon(lat): return 111_320.0*math.cos(math.radians(lat))


def meters_per_pixel(bounds, W, H):
    """Calculate meters per pixel for an image"""
    lat_min,lat_max = bounds["bottom_right"]["lat"], bounds["top_left"]["lat"]
    lon_min,lon_max = bounds["top_left"]["lon"], bounds["bottom_right"]["lon"]
    lat_c = 0.5*(lat_min+lat_max)
    mppx = meters_per_deg_lon(lat_c) * (lon_max - lon_min) / float(W)
    mppy = meters_per_deg_lat(lat_c) * (lat_max - lat_min) / float(H)
    return mppx, mppy, (mppx+mppy)/2.0


def create_aoi_mask_from_latlon(size, bounds, contour):
    """Create AOI mask from lat/lon contour"""
    W,H = size
    lat_min,lat_max = bounds["bottom_right"]["lat"], bounds["top_left"]["lat"]
    lon_min,lon_max = bounds["top_left"]["lon"], bounds["bottom_right"]["lon"]
    poly=[]
    for p in contour:
        x = (p["lon"] - lon_min) / (lon_max - lon_min + 1e-12) * W
        y = (lat_max - p["lat"]) / (lat_max - lat_min + 1e-12) * H
        poly.append((x,y))
    if len(poly)>=3:
        shp = Polygon(poly); shp = orient_polygon(shp, sign=-1.0)
        poly = list(shp.exterior.coords)
    mask = Image.new('L',(W,H),0); ImageDraw.Draw(mask).polygon(poly, outline=255, fill=255)
    return mask, poly


def get_utm_epsg(lon,lat):
    """Get UTM EPSG code for given coordinates"""
    zone = int((lon+180)//6)+1
    return 32600+zone if lat>=0 else 32700+zone


def geojson_area_m2(fc):
    """Calculate area in square meters from GeoJSON with robust topology handling"""
    if not fc["features"]: return 0.0, None
    
    try:
        gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")
        
        # Fix any invalid geometries before union
        gdf['geometry'] = gdf['geometry'].apply(lambda geom: geom.buffer(0) if not geom.is_valid else geom)
        
        # Try to get centroid for UTM zone calculation
        try:
            cen = gdf.union_all().centroid
        except (TopologicalError, GEOSException, AttributeError):
            try:
                cen = unary_union(gdf.geometry).centroid
            except (TopologicalError, GEOSException):
                # Fallback: use centroid of first geometry
                logger.warning("Union failed, using first geometry centroid for UTM zone")
                cen = gdf.geometry.iloc[0].centroid
        
        utm = get_utm_epsg(float(cen.x), float(cen.y))
        gdf_utm = gdf.to_crs(epsg=utm)
        return float(gdf_utm.area.sum()), utm
        
    except Exception as e:
        logger.error(f"geojson_area_m2 failed: {e}", exc_info=True)
        # Fallback: rough area calculation using bounding box
        try:
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
            # Very rough estimate: use average lat/lon to meters conversion
            avg_lat = (bounds[1] + bounds[3]) / 2
            width_m = (bounds[2] - bounds[0]) * meters_per_deg_lon(avg_lat)
            height_m = (bounds[3] - bounds[1]) * meters_per_deg_lat(avg_lat)
            area_m2 = width_m * height_m * 0.5  # Rough estimate assuming ~50% coverage
            utm = get_utm_epsg((bounds[0] + bounds[2])/2, (bounds[1] + bounds[3])/2)
            logger.warning(f"Using fallback area calculation: {area_m2:.1f} m²")
            return float(area_m2), utm
        except:
            logger.error("Even fallback area calculation failed, returning 0")
            return 0.0, None


def load_flair_unet(weights_path, device):
    """Load FLAIR UNet model"""
    logger.info(f"Loading model from {weights_path}")
    model = smp.Unet(encoder_name="resnet34", encoder_weights=None, in_channels=3, classes=len(FLAIR_CLASSES_ALL))
    state = torch.load(weights_path, map_location="cpu")
    cleaned = {(k[len('model.seg_model.'):] if k.startswith('model.seg_model.') else k): v for k,v in state.items()}
    model.load_state_dict(cleaned, strict=False)
    model.eval()
    model.to(device)
    logger.info("Model loaded successfully")
    return model


@torch.no_grad()
def infer_fullres_tiled(model, image_pil, device, tile=TILE_SIZE, overlap=TILE_OVERLAP):
    """Run inference on full resolution image using tiled approach"""
    W,H = image_pil.size
    logger.info(f"Running inference on {W}x{H} image")
    to_tensor = T.Compose([T.ToTensor(), T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])
    C = len(FLAIR_CLASSES_ALL)
    logits_accum = torch.zeros((C,H,W), dtype=torch.float32, device=device)
    count_accum  = torch.zeros((H,W), dtype=torch.float32, device=device)
    stride = tile - overlap
    total_tiles = ((H + stride - 1) // stride) * ((W + stride - 1) // stride)
    logger.info(f"Processing {total_tiles} tiles...")
    
    for y0 in range(0,H,stride):
        for x0 in range(0,W,stride):
            x1,y1 = min(x0+tile,W), min(y0+tile,H)
            crop = image_pil.crop((x0,y0,x1,y1))
            x = to_tensor(crop).unsqueeze(0).to(device)
            out = model(x)
            out = F.interpolate(out, size=(y1-y0,x1-x0), mode="bilinear", align_corners=False).squeeze(0)
            logits_accum[:,y0:y1,x0:x1] += out
            count_accum[y0:y1,x0:x1] += 1.0
    
    logits = logits_accum / (count_accum.unsqueeze(0)+1e-8)
    probs  = torch.softmax(logits, dim=0).cpu().numpy()
    labels = torch.argmax(logits, dim=0).cpu().numpy()
    logger.info("Inference complete")
    return labels, probs


def compute_confidence(refined_bool, prob_sum, compactness, pct_within_0p3m, aoi_np, mpp):
    """Compute confidence score and grade for lawn detection"""
    if refined_bool.sum() == 0:
        return 0.0, "D", {"mean_veg_prob":0.0,"near_bld_frac":1.0,"compactness_norm":0.0,"edge_touch_frac":1.0}
    mean_veg_prob = float(prob_sum[refined_bool].mean()) if prob_sum is not None else 0.5
    near_bld_frac = float((pct_within_0p3m or 0.0)/100.0)
    aoi_u8 = (aoi_np.astype(np.uint8))*255
    band_px = max(1, int(round(1.0 / max(mpp, 1e-6))))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*band_px+1, 2*band_px+1))
    edge = cv2.morphologyEx(aoi_u8, cv2.MORPH_GRADIENT, ker) > 0
    edge_band = cv2.dilate(edge.astype(np.uint8)*255, ker) > 0
    edge_touch_frac = float((refined_bool & edge_band).sum() / max(refined_bool.sum(),1))
    compactness_norm = float(min(1.0, (compactness or 0.0)/0.8))
    score = 0.40*mean_veg_prob + 0.25*(1.0 - near_bld_frac) + 0.20*compactness_norm + 0.15*(1.0 - edge_touch_frac)
    score = float(min(1.0, max(0.0, score)))
    grade = "A" if score >= 0.85 else ("B" if score >= 0.70 else ("C" if score >= 0.55 else "D"))
    return score, grade, {"mean_veg_prob":mean_veg_prob,"near_bld_frac":near_bld_frac,
                          "compactness_norm":compactness_norm,"edge_touch_frac":edge_touch_frac}


def mask_to_geojson(mask_bool, bounds):
    """Convert binary mask to GeoJSON"""
    from skimage import measure
    H,W = mask_bool.shape
    contours = measure.find_contours(mask_bool.astype(float), 0.5)
    feats=[]
    for c in contours:
        def px_to_latlon(x,y):
            lat_min,lat_max = bounds["bottom_right"]["lat"], bounds["top_left"]["lat"]
            lon_min,lon_max = bounds["top_left"]["lon"], bounds["bottom_right"]["lon"]
            lon = lon_min + (x/(W+1e-12))*(lon_max - lon_min)
            lat = lat_max - (y/(H+1e-12))*(lat_max - lat_min)
            return [lon,lat]
        ring = [px_to_latlon(x,y) for y,x in c]
        if ring and ring[0]!=ring[-1]: ring.append(ring[0])
        if len(ring)>=4:
            feats.append({"type":"Feature","geometry":{"type":"Polygon","coordinates":[ring]},"properties":{}})
    return {"type":"FeatureCollection","features":feats}


def refine_mask_variant(name, params, labels_np, prob_sum, base_mask, aoi_np,
                        W,H,image, mppx,mppy,mpp, px_area_m2=None,
                        have_geo=False, bounds_if_geo=None, output_dir="."):
    """Refine vegetation mask with morphological operations"""
    logger.info(f"Refining mask variant: {name}")
    DILATE_M, CLOSE_M, SMOOTH_M = params

    def kxy_for_m(m):
        kx = max(1, int(round(m / max(mppx,1e-6))))
        ky = max(1, int(round(m / max(mppy,1e-6))))
        return kx, ky

    veg_mask = base_mask & aoi_np

    # Building-aware keep-back
    bld = (labels_np == CLASS_TO_IDX.get('building', -999))
    dt_px = None
    if bld.any():
        bld_u8 = (bld.astype(np.uint8))*255
        kx,ky = kxy_for_m(CLOSE_M)
        if kx>1 or ky>1:
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*kx+1,2*ky+1))
            bld_u8 = cv2.morphologyEx(bld_u8, cv2.MORPH_CLOSE, ker)
        kx,ky = kxy_for_m(DILATE_M)
        if kx>0 or ky>0:
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*kx+1,2*ky+1))
            bld_u8 = cv2.dilate(bld_u8, ker)
        veg_mask &= ~(bld_u8>0)
        inv_bld = (~bld).astype(np.uint8)*255
        dt_px = cv2.distanceTransform(inv_bld, cv2.DIST_L2, 3)

    # Smoothing
    kx,ky = kxy_for_m(SMOOTH_M)
    if kx>1 or ky>1:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*kx+1,2*ky+1))
        v8 = (veg_mask.astype(np.uint8))*255
        v8 = cv2.morphologyEx(v8, cv2.MORPH_OPEN,  ker)
        v8 = cv2.morphologyEx(v8, cv2.MORPH_CLOSE, ker)
        veg_mask = v8.astype(bool)

    # Drop tiny fragments
    area_per_px = px_area_m2 if px_area_m2 is not None else (mppx*mppy)
    min_area_px = max(1, int(round(MIN_PATCH_AREA_M2 / max(area_per_px,1e-9))))
    nlab, lab, stats, _ = cv2.connectedComponentsWithStats(veg_mask.astype(np.uint8), 8)
    keep = np.zeros(nlab, dtype=bool)
    for i in range(1,nlab):
        if stats[i, cv2.CC_STAT_AREA] >= min_area_px: keep[i]=True
    refined = keep[lab] & aoi_np
    refined_u8 = (refined.astype(np.uint8))*255

    # Calculate area
    if px_area_m2 is not None:
        area_m2 = float(refined.sum()) * float(px_area_m2)
    else:
        gj = mask_to_geojson(refined, bounds_if_geo)
        area_m2, _ = geojson_area_m2(gj)
    area_ft2 = area_m2 * 10.7639

    # Perimeter/compactness
    contours,_ = cv2.findContours(refined_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    perim_px = sum(cv2.arcLength(c, True) for c in contours)
    perim_m  = float(perim_px * math.sqrt(area_per_px))
    compactness = float((4*math.pi*max(area_m2,1e-9)) / (perim_m**2 + 1e-12))

    # Clearance to building
    median_clearance_m = min_clearance_m = pct_within_0p3m = None
    if dt_px is not None:
        d = dt_px[refined]
        if d.size>0:
            d_m = d * math.sqrt(area_per_px)
            median_clearance_m = float(np.median(d_m))
            min_clearance_m    = float(np.min(d_m))
            pct_within_0p3m    = float((d_m <= 0.30).sum()/d_m.size*100.0)

    # Confidence
    conf_score, conf_grade, conf_breakdown = compute_confidence(refined, prob_sum, compactness, pct_within_0p3m, aoi_np, math.sqrt(area_per_px))

    # Save artifacts
    Image.fromarray(refined_u8).save(os.path.join(output_dir, f"lawn_mask_{name}.png"))
    # Create RGBA overlay image - composite the satellite image with lawn colored overlay
    base_arr = np.array(image, dtype=np.uint8)  # RGB base
    result_arr = base_arr.copy()
    
    # Where we have lawn, blend in the green color
    lawn_mask = refined_u8 > 0
    alpha_val = 140 / 255.0  # Semi-transparency
    result_arr[lawn_mask, 0] = (result_arr[lawn_mask, 0] * (1 - alpha_val) + 100 * alpha_val).astype(np.uint8)
    result_arr[lawn_mask, 1] = (result_arr[lawn_mask, 1] * (1 - alpha_val) + 200 * alpha_val).astype(np.uint8)
    result_arr[lawn_mask, 2] = (result_arr[lawn_mask, 2] * (1 - alpha_val) + 80 * alpha_val).astype(np.uint8)
    
    final_overlay = Image.fromarray(result_arr, mode='RGB')
    final_overlay.save(os.path.join(output_dir, f"overlay_{name}.png"))

    logger.info(f"Variant {name}: area={area_ft2:.0f} ft², confidence={conf_score:.2f} ({conf_grade})")

    return {
        "name": name,
        "lawn_area_ft2": float(area_ft2),
        "lawn_area_m2": float(area_m2),
        "perimeter_m": perim_m, "compactness": compactness,
        "median_clearance_m": median_clearance_m, "min_clearance_m": min_clearance_m,
        "pct_lawn_within_0.30m_of_building": pct_within_0p3m,
        "confidence_score": conf_score, "confidence_grade": conf_grade
    }


def segment_front_back_sides(labels_np, aoi_np, image, output_dir, mppx, mppy, px_area_m2,
                             have_geo, bounds_if_geo, best_variant):
    """Segment lawn into front/back/sides"""
    logger.info("Segmenting lawn into front/back/sides")
    H, W = labels_np.shape
    best_name = best_variant["name"]
    lawn_mask_path = os.path.join(output_dir, f"lawn_mask_{best_name}.png")
    
    lawn_u8 = np.array(Image.open(lawn_mask_path).convert("L"))
    lawn = (lawn_u8 > 0) & aoi_np

    # Building centroid
    bld = (labels_np == CLASS_TO_IDX.get('building', -999)) & aoi_np
    bld_u8 = (bld.astype(np.uint8))*255
    nlab, lab, stats, cents = cv2.connectedComponentsWithStats(bld_u8, 8)
    
    if nlab > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        idx = 1 + int(np.argmax(areas))
        cx, cy = cents[idx]
    else:
        ys, xs = np.where(aoi_np)
        cx, cy = float(xs.mean()), float(ys.mean())

    # Simple front/back split (vertical)
    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
    front = lawn & (yy >= cy)
    back  = lawn & (yy < cy)
    left  = lawn & (xx < cx)
    right = lawn & (xx >= cx)
    sides = left | right

    # Save masks
    zone_masks = {
        "front": (front.astype(np.uint8)*255),
        "back":  (back.astype(np.uint8)*255),
        "left":  (left.astype(np.uint8)*255),
        "right": (right.astype(np.uint8)*255),
        "sides": (sides.astype(np.uint8)*255),
    }
    for name, m in zone_masks.items():
        Image.fromarray(m).save(os.path.join(output_dir, f"{name}_yard_{best_name}.png"))

    # Calculate areas
    def mask_area(m):
        if m.sum() == 0: return 0.0
        if px_area_m2 is not None:
            return float((m>0).sum()) * float(px_area_m2)
        gj = mask_to_geojson(m>0, bounds_if_geo)
        a, _ = geojson_area_m2(gj)
        return float(a)
    
    zones_area_m2 = {z: mask_area(zone_masks[z]) for z in ["front","back","left","right","sides"]}
    zones_area_ft2 = {k: v*10.7639 for k,v in zones_area_m2.items()}

    # Composite overlay - blend zones onto satellite image
    base_arr = np.array(image, dtype=np.uint8)  # RGB base
    result_arr = base_arr.copy()
    
    # Apply each zone color with alpha blending - last one wins at overlaps
    # Left - Orange (255,165,0) with alpha 110
    left_mask = zone_masks["left"] > 0
    alpha_val = 110 / 255.0
    result_arr[left_mask, 0] = (result_arr[left_mask, 0] * (1 - alpha_val) + 255 * alpha_val).astype(np.uint8)
    result_arr[left_mask, 1] = (result_arr[left_mask, 1] * (1 - alpha_val) + 165 * alpha_val).astype(np.uint8)
    result_arr[left_mask, 2] = (result_arr[left_mask, 2] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    
    # Right - Red (200,0,0) with alpha 110
    right_mask = zone_masks["right"] > 0
    alpha_val = 110 / 255.0
    result_arr[right_mask, 0] = (result_arr[right_mask, 0] * (1 - alpha_val) + 200 * alpha_val).astype(np.uint8)
    result_arr[right_mask, 1] = (result_arr[right_mask, 1] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    result_arr[right_mask, 2] = (result_arr[right_mask, 2] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    
    # Front - Green (0,200,0) with alpha 160
    front_mask = zone_masks["front"] > 0
    alpha_val = 160 / 255.0
    result_arr[front_mask, 0] = (result_arr[front_mask, 0] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    result_arr[front_mask, 1] = (result_arr[front_mask, 1] * (1 - alpha_val) + 200 * alpha_val).astype(np.uint8)
    result_arr[front_mask, 2] = (result_arr[front_mask, 2] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    
    # Back - Blue (0,0,200) with alpha 160
    back_mask = zone_masks["back"] > 0
    alpha_val = 160 / 255.0
    result_arr[back_mask, 0] = (result_arr[back_mask, 0] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    result_arr[back_mask, 1] = (result_arr[back_mask, 1] * (1 - alpha_val) + 0 * alpha_val).astype(np.uint8)
    result_arr[back_mask, 2] = (result_arr[back_mask, 2] * (1 - alpha_val) + 200 * alpha_val).astype(np.uint8)
    
    composite = Image.fromarray(result_arr, mode='RGB')
    composite.save(os.path.join(output_dir, f"overlay_front_back_sides_{best_name}.png"))

    logger.info(f"Zones - Front: {zones_area_ft2['front']:.0f} ft², Back: {zones_area_ft2['back']:.0f} ft², "
                f"Left: {zones_area_ft2['left']:.0f} ft², Right: {zones_area_ft2['right']:.0f} ft²")

    return {
        "areas_m2": zones_area_m2,
        "areas_ft2": zones_area_ft2
    }


def analyze_lawn_from_geojson(geojson_payload, image_path, output_dir="./outputs", model_path="model_19class.pth", satellite_bounds=None):
    """
    Main analysis function - callable from API
    
    Args:
        geojson_payload: GeoJSON FeatureCollection with polygon
        image_path: Path to satellite image
        output_dir: Directory to save outputs
        model_path: Path to model weights
        satellite_bounds: Actual bounds of the satellite image (from image_fetcher)
        
    Returns:
        Dictionary with analysis results
    """
    logger.info("=== Starting lawn analysis ===")
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # Load image
        image = Image.open(image_path).convert("RGB")
        W, H = image.size
        logger.info(f"Image: {W}x{H}")
        
        # Normalize AOI
        aoi_fc = normalize_aoi_geojson(geojson_payload)
        aoi_area_true_m2, _ = geojson_area_m2(aoi_fc)
        logger.info(f"AOI area: {aoi_area_true_m2*10.7639:.1f} ft²")
        
        # Create AOI mask using actual satellite image bounds
        _, contour = extract_bounds_and_aoi(aoi_fc)
        
        # Use satellite bounds if provided, otherwise fallback to polygon bounds
        if satellite_bounds is not None:
            image_bounds = satellite_bounds
            logger.info(f"Using actual satellite image bounds for AOI mask")
        else:
            image_bounds, _ = extract_bounds_and_aoi(aoi_fc)
            logger.warning(f"No satellite bounds provided, using polygon bounds (may be inaccurate)")
        
        aoi_mask_proj, _ = create_aoi_mask_from_latlon((W,H), image_bounds, contour)
        aoi_np = np.array(aoi_mask_proj, dtype=bool)
        
        # Calculate scale
        mppx, mppy, mpp = meters_per_pixel(image_bounds, W, H)
        logger.info(f"Resolution: {mpp:.3f} m/pixel")
        
        # Download and load model
        download_file(MODEL_URL, model_path)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {device}")
        model = load_flair_unet(model_path, device)
        
        # Run inference
        labels_np, probs_np = infer_fullres_tiled(model, image, device)
        
        # Base vegetation mask
        veg_idx = [CLASS_TO_IDX[c] for c in VEG_CLASSES if c in CLASS_TO_IDX]
        mask_labels = np.isin(labels_np, veg_idx)
        prob_sum = probs_np[veg_idx].sum(axis=0)
        ps = (prob_sum[aoi_np]*255.0).astype(np.uint8)
        if ps.size>0 and np.any(ps):
            thr_val, _ = cv2.threshold(ps, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
            thr = max(PROB_THRESH_MIN, float(thr_val)/255.0)
        else:
            thr = PROB_THRESH_MIN
        base_mask = mask_labels & (prob_sum >= thr)
        
        # Run refinement (using best variant)
        name, d, c, s = VARIANTS[0]
        result = refine_mask_variant(name, (d,c,s), labels_np, prob_sum, base_mask, aoi_np,
                                    W, H, image, mppx, mppy, mpp, px_area_m2=None,
                                    have_geo=True, bounds_if_geo=image_bounds, output_dir=output_dir)
        
        # Segment zones
        zones = segment_front_back_sides(labels_np, aoi_np, image, output_dir, mppx, mppy, None,
                                        True, image_bounds, result)
        
        # Combine results
        final_result = {
            "success": True,
            "lawn_area_ft2": result["lawn_area_ft2"],
            "lawn_area_m2": result["lawn_area_m2"],
            "confidence_score": result["confidence_score"],
            "confidence_grade": result["confidence_grade"],
            "zones": zones,
            "output_dir": output_dir,
            "variant": result["name"]
        }
        
        logger.info("=== Analysis complete ===")
        return final_result
        
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

