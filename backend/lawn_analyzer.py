# -*- coding: utf-8 -*-
import os, sys, json, math, glob, warnings, logging
warnings.filterwarnings("ignore", category=UserWarning)

import torch, torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image, ImageDraw
import numpy as np, requests, matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt, cv2, geopandas as gpd
import segmentation_models_pytorch as smp
from shapely.geometry import Polygon, Point, MultiPolygon, box
from shapely.geometry.polygon import orient as orient_polygon
from shapely.ops import unary_union

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------ CONFIG ------------------------------
MODEL_URL = "https://huggingface.co/IGNF/FLAIR-INC_rgb_12cl_resnet34-unet/resolve/main/FLAIR-INC_rgb_12cl_resnet34-unet_weights.pth"
TILE_SIZE, TILE_OVERLAP = 512, 64
PROB_THRESH_MIN, MIN_PATCH_AREA_M2 = 0.25, 2.0

FLAIR_CLASSES_ALL = [
    'building','pervious surface','impervious surface','bare soil','water','coniferous',
    'deciduous','brushwood','vineyard','herbaceous','agricultural land','plowed land',
    'other','forest','swimming pool','snow','boat','ash','unclassified'
]
CLASS_TO_IDX = {n:i for i,n in enumerate(FLAIR_CLASSES_ALL)}
VEG_CLASSES = ['herbaceous','agricultural land','plowed land','brushwood','coniferous','deciduous','forest','pervious surface']

# Single variant for speed (first from original list)
VARIANT = ("t1-0.26-0.10-0.14", 0.26, 0.10, 0.14)

# ------------------------------ HELPERS ------------------------------
def download_file(url, dst):
    if not os.path.exists(dst):
        logger.info(f"Downloading {os.path.basename(dst)} ...")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for ch in r.iter_content(8192): f.write(ch)

def normalize_bbox(b):
    min_lon,min_lat,max_lon,max_lat = b
    if max_lon < min_lon: min_lon,max_lon = max_lon,min_lon
    if max_lat < min_lat: min_lat,max_lat = max_lat,min_lat
    if abs(max_lon-min_lon) < 1e-12: max_lon += 1e-6
    if abs(max_lat-min_lat) < 1e-12: max_lat += 1e-6
    return [min_lon,min_lat,max_lon,max_lat]

def compute_bbox_from_polygon(coords):
    lons = [p[0] for p in coords]; lats = [p[1] for p in coords]
    mnx,mxx = min(lons),max(lons); mny,mxy = min(lats),max(lats)
    padx = (mxx-mnx)*0.01 or 1e-6; pady = (mxy-mny)*0.01 or 1e-6
    return [mnx-padx, mny-pady, mxx+padx, mxy+pady]

def normalize_aoi_geojson(gj):
    feat = gj['features'][0]; coords = feat['geometry']['coordinates'][0]
    poly = Polygon(coords)
    if not poly.is_valid: poly = poly.buffer(0)
    poly = orient_polygon(poly, sign=1.0)
    bbox_prop = feat.get('properties',{}).get('bbox') or compute_bbox_from_polygon(coords)
    bbox_prop = normalize_bbox(bbox_prop)
    min_lon,min_lat,max_lon,max_lat = bbox_prop
    clipper = box(min_lon, min_lat, max_lon, max_lat)
    poly = poly.intersection(clipper)
    if isinstance(poly, MultiPolygon): poly = max(list(poly.geoms), key=lambda p: p.area)
    return {"type":"FeatureCollection","features":[{
        "type":"Feature",
        "geometry": json.loads(gpd.GeoSeries([poly], crs="EPSG:4326").to_json())["features"][0]["geometry"],
        "properties":{"bbox":[min_lon,min_lat,max_lon,max_lat]}
    }]}

def extract_bounds_and_aoi(gj):
    feat = gj['features'][0]; bbox = normalize_bbox(feat['properties']['bbox'])
    image_bounds = {"top_left":{"lat":bbox[3],"lon":bbox[0]}, "bottom_right":{"lat":bbox[1],"lon":bbox[2]}, "bbox":bbox}
    coords = feat['geometry']['coordinates'][0]
    contour = [{"lat":lat,"lon":lon} for lon,lat in coords]
    return image_bounds, contour

def meters_per_deg_lat(lat): return 111_320.0
def meters_per_deg_lon(lat): return 111_320.0*math.cos(math.radians(lat))
def meters_per_pixel(bounds, W, H):
    lat_min,lat_max = bounds["bottom_right"]["lat"], bounds["top_left"]["lat"]
    lon_min,lon_max = bounds["top_left"]["lon"], bounds["bottom_right"]["lon"]
    lat_c = 0.5*(lat_min+lat_max)
    mppx = meters_per_deg_lon(lat_c) * (lon_max - lon_min) / float(W)
    mppy = meters_per_deg_lat(lat_c) * (lat_max - lat_min) / float(H)
    return mppx, mppy, (mppx+mppy)/2.0

def create_aoi_mask_from_latlon(size, bounds, contour):
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
    zone = int((lon+180)//6)+1
    return 32600+zone if lat>=0 else 32700+zone

def geojson_area_m2(fc):
    if not fc["features"]: return 0.0, None
    gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")
    try: cen = gdf.union_all().centroid
    except Exception: cen = unary_union(gdf.geometry).centroid
    utm = get_utm_epsg(float(cen.x), float(cen.y))
    gdf_utm = gdf.to_crs(epsg=utm)
    return float(gdf_utm.area.sum()), utm

def detect_screenshot_island_mask(img_rgb):
    arr = np.array(img_rgb.convert("RGB"))
    nonwhite = (arr[:,:,0] < 245) | (arr[:,:,1] < 245) | (arr[:,:,2] < 245)
    nw = (nonwhite.astype(np.uint8))*255
    k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21,21))
    nw = cv2.morphologyEx(nw, cv2.MORPH_OPEN, k1)
    nw = cv2.morphologyEx(nw, cv2.MORPH_CLOSE, k2)
    nlab, lab, stats, _ = cv2.connectedComponentsWithStats(nw, connectivity=8)
    if nlab <= 1: return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = 1 + int(np.argmax(areas))
    island = (lab == best)
    frac = island.mean()
    if frac < 0.05: return None
    return island

# ------------------------------ MODEL ------------------------------
def load_flair_unet(weights_path):
    model = smp.Unet(encoder_name="resnet34", encoder_weights=None, in_channels=3, classes=len(FLAIR_CLASSES_ALL))
    state = torch.load(weights_path, map_location="cpu")
    cleaned = {(k[len('model.seg_model.'):] if k.startswith('model.seg_model.') else k): v for k,v in state.items()}
    model.load_state_dict(cleaned, strict=False)
    model.eval(); return model

@torch.no_grad()
def infer_fullres_tiled(model, image_pil, device, tile=TILE_SIZE, overlap=TILE_OVERLAP):
    W,H = image_pil.size
    to_tensor = T.Compose([T.ToTensor(), T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])
    C = len(FLAIR_CLASSES_ALL)
    logits_accum = torch.zeros((C,H,W), dtype=torch.float32, device=device)
    count_accum = torch.zeros((H,W), dtype=torch.float32, device=device)
    stride = tile - overlap
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
    probs = torch.softmax(logits, dim=0).cpu().numpy()
    labels = torch.argmax(logits, dim=0).cpu().numpy()
    return labels, probs

# ------------------------------ REFINEMENT ------------------------------
def compute_confidence(refined_bool, prob_sum, compactness, pct_within_0p3m, aoi_np, mpp):
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
    DILATE_M, CLOSE_M, SMOOTH_M = params

    def kxy_for_m(m):
        kx = max(1, int(round(m / max(mppx,1e-6))))
        ky = max(1, int(round(m / max(mppy,1e-6))))
        return kx, ky

    veg_mask = base_mask & aoi_np

    # building-aware keep-back
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

    # smoothing
    kx,ky = kxy_for_m(SMOOTH_M)
    if kx>1 or ky>1:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*kx+1,2*ky+1))
        v8 = (veg_mask.astype(np.uint8))*255
        v8 = cv2.morphologyEx(v8, cv2.MORPH_OPEN, ker)
        v8 = cv2.morphologyEx(v8, cv2.MORPH_CLOSE, ker)
        veg_mask = v8.astype(bool)

    # drop tiny fragments
    area_per_px = px_area_m2 if px_area_m2 is not None else (mppx*mppy)
    min_area_px = max(1, int(round(MIN_PATCH_AREA_M2 / max(area_per_px,1e-9))))
    nlab, lab, stats, _ = cv2.connectedComponentsWithStats(veg_mask.astype(np.uint8), 8)
    keep = np.zeros(nlab, dtype=bool)
    for i in range(1,nlab):
        if stats[i, cv2.CC_STAT_AREA] >= min_area_px: keep[i]=True
    refined = keep[lab] & aoi_np
    refined_u8 = (refined.astype(np.uint8))*255

    # area
    if px_area_m2 is not None:
        area_m2 = float(refined.sum()) * float(px_area_m2)
    else:
        gj = mask_to_geojson(refined, bounds_if_geo)
        area_m2, _ = geojson_area_m2(gj)
    area_ft2 = area_m2 * 10.7639

    # perimeter/compactness
    contours,_ = cv2.findContours(refined_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    perim_px = sum(cv2.arcLength(c, True) for c in contours)
    perim_m = float(perim_px * math.sqrt(area_per_px))
    compactness = float((4*math.pi*max(area_m2,1e-9)) / (perim_m**2 + 1e-12))

    # clearance to building
    median_clearance_m = min_clearance_m = pct_within_0p3m = None
    if dt_px is not None:
        d = dt_px[refined]
        if d.size>0:
            d_m = d * math.sqrt(area_per_px)
            median_clearance_m = float(np.median(d_m))
            min_clearance_m = float(np.min(d_m))
            pct_within_0p3m = float((d_m <= 0.30).sum()/d_m.size*100.0)

    # confidence
    conf_score, conf_grade, conf_breakdown = compute_confidence(refined, prob_sum, compactness, pct_within_0p3m, aoi_np, math.sqrt(area_per_px))

    # Save artifacts
    Image.fromarray(refined_u8).save(os.path.join(output_dir, f"lawn_mask_{name}.png"))
    base_rgba = image.convert("RGBA")
    overlay = Image.new("RGBA", (W,H), (0,0,0,0))
    overlay.paste((100,200,80,140), mask=Image.fromarray(refined_u8))
    final_overlay = Image.alpha_composite(base_rgba, overlay)
    final_overlay.save(os.path.join(output_dir, f"overlay_{name}.png"))

    return {
        "name": name,
        "lawn_area_ft2": float(area_ft2),
        "lawn_area_m2": float(area_m2),
        "perimeter_m": perim_m, "compactness": compactness,
        "median_clearance_m": median_clearance_m, "min_clearance_m": min_clearance_m,
        "pct_lawn_within_0.30m_of_building": pct_within_0p3m,
        "confidence_score": conf_score, "confidence_grade": conf_grade
    }

# ------------------------------ FRONT/BACK/SIDES ------------------------------
def _largest_cc(mask_u8):
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask_u8, 8)
    if n <= 1: return None, None, None
    areas = stats[1:, cv2.CC_STAT_AREA]
    idx = 1 + int(np.argmax(areas))
    cc = (lab == idx)
    cx, cy = cents[idx]
    return cc, (float(cx), float(cy)), int(stats[idx, cv2.CC_STAT_AREA])

def _norm(v):
    n = np.linalg.norm(v)
    if n < 1e-9: return np.array([1.0, 0.0], dtype=np.float32)
    return v / n

def _estimate_street_direction(labels_np, aoi_np, building_centroid, CLASS_TO_IDX):
    imp_ids = [CLASS_TO_IDX.get('impervious surface', -1)]
    imp_ids = [i for i in imp_ids if i >= 0]
    if not imp_ids: return None
    imp = np.isin(labels_np, imp_ids) & aoi_np
    imp_u8 = (imp.astype(np.uint8)) * 255
    if imp_u8.sum() == 0: return None
    aoi_u8 = (aoi_np.astype(np.uint8)) * 255
    edge = cv2.morphologyEx(aoi_u8, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))) > 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(imp_u8, 8)

    # H1: biggest impervious touching AOI edge
    best_id, best_area = None, 0
    for i in range(1, n):
        comp = (lab == i)
        if (comp & edge).any():
            area = stats[i, cv2.CC_STAT_AREA]
            if area > best_area:
                best_area, best_id = area, i
    if best_id is not None:
        ys, xs = np.where(lab == best_id)
        if len(xs) >= 10:
            pts = np.stack([xs, ys], axis=1).astype(np.float32)
            pts -= pts.mean(axis=0, keepdims=True)
            _, _, vt = cv2.SVDecomp(pts)
            v = vt[0, :2]
            return _norm(v)

    # H2: nearest impervious to building
    if building_centroid is not None:
        bx, by = building_centroid
        best_id, best_d = None, 1e18
        for i in range(1, n):
            x, y, w, h, area = stats[i,0], stats[i,1], stats[i,2], stats[i,3], stats[i,4]
            cx, cy = x + 0.5*w, y + 0.5*h
            d = (cx - bx)**2 + (cy - by)**2
            if d < best_d:
                best_d, best_id = d, i
        if best_id is not None:
            ys, xs = np.where(lab == best_id)
            if len(xs) >= 10:
                pts = np.stack([xs, ys], axis=1).astype(np.float32)
                pts -= pts.mean(axis=0, keepdims=True)
                _, _, vt = cv2.SVDecomp(pts)
                v = vt[0, :2]
                return _norm(v)

    # H3: vector from building to nearest edge
    if building_centroid is not None:
        bx, by = building_centroid
        edge_pts = np.argwhere(edge)
        if len(edge_pts) > 0:
            diffs = edge_pts[:, [1,0]].astype(np.float32) - np.array([[bx, by]], dtype=np.float32)
            i = int(np.argmin(np.sum(diffs**2, axis=1)))
            v = diffs[i]
            return _norm(v)
    return None

def _mask_area_m2(mask_u8, px_area_m2, have_geo, bounds_if_geo):
    m = (mask_u8 > 0)
    if m.sum() == 0: return 0.0
    if px_area_m2 is not None:
        return float(m.sum()) * float(px_area_m2)
    gj = mask_to_geojson(m, bounds_if_geo)
    area_m2, _ = geojson_area_m2(gj)
    return float(area_m2)

def _save_zone_geojson(mask_u8, bounds_if_geo, path):
    if bounds_if_geo is None: return
    gj = mask_to_geojson(mask_u8>0, bounds_if_geo)
    with open(path, "w") as f:
        json.dump(gj, f, indent=2)

def segment_front_back_sides(labels_np, aoi_np, image, output_dir, CLASS_TO_IDX, 
                             mppx, mppy, px_area_m2, have_geo, bounds_if_geo, best_name):
    H, W = labels_np.shape
    lawn_mask_path = os.path.join(output_dir, f"lawn_mask_{best_name}.png")
    if not os.path.exists(lawn_mask_path):
        raise FileNotFoundError(f"Missing {lawn_mask_path}")
    lawn_u8 = np.array(Image.open(lawn_mask_path).convert("L"))
    lawn = (lawn_u8 > 0) & aoi_np

    # Building centroid
    bld = (labels_np == CLASS_TO_IDX.get('building', -999)) & aoi_np
    bld_u8 = (bld.astype(np.uint8))*255
    _, bcentroid, _ = _largest_cc(bld_u8)
    if bcentroid is None:
        ys, xs = np.where(aoi_np)
        if xs.size == 0:
            raise RuntimeError("AOI is empty")
        cx, cy = float(xs.mean()), float(ys.mean())
    else:
        cx, cy = bcentroid

    # Street direction
    v = _estimate_street_direction(labels_np, aoi_np, (cx, cy), CLASS_TO_IDX)
    if v is None:
        v = np.array([1.0, 0.0], dtype=np.float32)
    vx, vy = float(v[0]), float(v[1])
    ux, uy = -vy, vx
    un = _norm(np.array([ux, uy], dtype=np.float32))
    ux, uy = float(un[0]), float(un[1])

    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
    dot_v = (xx - cx) * vx + (yy - cy) * vy
    dot_u = (xx - cx) * ux + (yy - cy) * uy

    front = lawn & (dot_v >= 0)
    back = lawn & (dot_v < 0)
    left = lawn & (dot_u < 0)
    right = lawn & (dot_u >= 0)
    sides = left | right

    zone_masks = {
        "front": (front.astype(np.uint8)*255),
        "back": (back.astype(np.uint8)*255),
        "left": (left.astype(np.uint8)*255),
        "right": (right.astype(np.uint8)*255),
        "sides": (sides.astype(np.uint8)*255),
    }
    for name, m in zone_masks.items():
        Image.fromarray(m).save(os.path.join(output_dir, f"{name}_yard_{best_name}.png"))

    zones_area_m2 = {z: _mask_area_m2(zone_masks[z], px_area_m2, have_geo, bounds_if_geo)
                     for z in ["front","back","left","right","sides"]}
    zones_area_ft2 = {k: v*10.7639 for k,v in zones_area_m2.items()}

    total_lawn_m2 = _mask_area_m2(lawn.astype(np.uint8)*255, px_area_m2, have_geo, bounds_if_geo)
    total_lawn_ft2 = total_lawn_m2 * 10.7639

    if have_geo and bounds_if_geo is not None:
        _save_zone_geojson(zone_masks["front"], bounds_if_geo, os.path.join(output_dir, f"front_yard_{best_name}.geojson"))
        _save_zone_geojson(zone_masks["back"], bounds_if_geo, os.path.join(output_dir, f"back_yard_{best_name}.geojson"))
        _save_zone_geojson(zone_masks["left"], bounds_if_geo, os.path.join(output_dir, f"left_side_{best_name}.geojson"))
        _save_zone_geojson(zone_masks["right"], bounds_if_geo, os.path.join(output_dir, f"right_side_{best_name}.geojson"))
        _save_zone_geojson(zone_masks["sides"], bounds_if_geo, os.path.join(output_dir, f"sides_{best_name}.geojson"))

    # Composite overlay
    base_rgba = image.convert("RGBA")
    over = Image.new("RGBA", (W, H), (0,0,0,0))
    def _paste(color_rgba, mask):
        over.paste(color_rgba, mask=Image.fromarray(mask))
    _paste((255,165,0,110), zone_masks["left"])
    _paste((200,0,0,110), zone_masks["right"])
    _paste((0,200,0,160), zone_masks["front"])
    _paste((0,0,200,160), zone_masks["back"])
    composite = Image.alpha_composite(base_rgba, over)
    composite.save(os.path.join(output_dir, f"overlay_front_back_sides_{best_name}.png"))

    metrics = {
        "variant_used": best_name,
        "centroid_px": {"x": cx, "y": cy},
        "street_dir_v_unit": {"x": vx, "y": vy},
        "left_dir_u_unit": {"x": ux, "y": uy},
        "areas_m2": {
            "front": zones_area_m2["front"],
            "back": zones_area_m2["back"],
            "left": zones_area_m2["left"],
            "right": zones_area_m2["right"],
            "sides": zones_area_m2["sides"],
            "total_lawn": total_lawn_m2
        },
        "areas_ft2": {
            "front": zones_area_ft2["front"],
            "back": zones_area_ft2["back"],
            "left": zones_area_ft2["left"],
            "right": zones_area_ft2["right"],
            "sides": zones_area_ft2["sides"],
            "total_lawn": total_lawn_ft2
        }
    }
    with open(os.path.join(output_dir, f"yard_areas_{best_name}.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics

# ------------------------------ MAIN API ------------------------------
def analyze_lawn(image_path, geojson_payload, address, output_dir, model_path="model_19class.pth"):
    """
    Analyze lawn area from satellite image and geojson polygon.
    
    Args:
        image_path: Path to satellite image
        geojson_payload: GeoJSON dict with polygon feature
        address: Address string (for display)
        output_dir: Directory to save outputs
        model_path: Path to ML model weights
        
    Returns:
        dict with success, message, output_files, and metrics
    """
    try:
        logger.info(f"Starting analysis for {address}")
        os.makedirs(output_dir, exist_ok=True)
        
        # Load image
        image = Image.open(image_path).convert("RGB")
        W, H = image.size
        logger.info(f"Image: {W}x{H}")

        # Process AOI
        aoi_fc = normalize_aoi_geojson(geojson_payload)
        aoi_area_true_m2, _ = geojson_area_m2(aoi_fc)
        logger.info(f"AOI true area ≈ {aoi_area_true_m2*10.7639:.1f} ft²")

        image_bounds, contour = extract_bounds_and_aoi(aoi_fc)
        aoi_mask_proj, _ = create_aoi_mask_from_latlon((W,H), image_bounds, contour)
        aoi_np_proj = np.array(aoi_mask_proj, dtype=bool)
        coverage = aoi_np_proj.mean()

        # Screenshot island detection (only use for actual screenshots with white borders)
        island = detect_screenshot_island_mask(image)
        island_frac = island.mean() if island is not None else 0.0
        logger.info(f"Projected AOI cover={coverage*100:.1f}% | island cover={island_frac*100:.1f}%")

        # Only use island mode if:
        # 1. Island detected AND
        # 2. Coverage is very low (< 50% - indicating screenshot with borders) AND
        # 3. Island coverage is significant (> 60%)
        use_island = False
        if island is not None and coverage < 0.50 and island_frac > 0.60:
            logger.info("SCREENSHOT MODE → detected image with white borders, using island")
            use_island = True

        if use_island:
            aoi_np = island
            px_area_m2 = aoi_area_true_m2 / float(aoi_np.sum())
            mpp = math.sqrt(px_area_m2); mppx = mpp; mppy = mpp
            bounds_if_geo = None; have_geo = False
            Image.fromarray((aoi_np.astype(np.uint8))*255).save(os.path.join(output_dir, "aoi_island_mask.png"))
        else:
            logger.info("STANDARD MODE → using projected AOI polygon mask")
            aoi_np = aoi_np_proj
            mppx, mppy, mpp = meters_per_pixel(image_bounds, W, H)
            px_area_m2 = None
            bounds_if_geo = image_bounds; have_geo = True
            Image.fromarray((aoi_np.astype(np.uint8))*255).save(os.path.join(output_dir, "aoi_projected_mask.png"))

        # Download and load model
        download_file(MODEL_URL, model_path)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {device}")
        model = load_flair_unet(model_path).to(device)
        
        # Inference
        logger.info("Running segmentation inference...")
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

        # Run single variant
        name, d, c, s = VARIANT
        logger.info(f"Processing variant: {name}")
        result = refine_mask_variant(name, (d,c,s), labels_np, prob_sum, base_mask, aoi_np,
                                    W,H,image, mppx,mppy,mpp, px_area_m2=px_area_m2,
                                    have_geo=have_geo, bounds_if_geo=bounds_if_geo, output_dir=output_dir)
        
        logger.info(f"Lawn area: {result['lawn_area_ft2']:.0f} ft² | confidence: {result['confidence_score']:.2f}")

        # Create best overlay
        img = Image.open(os.path.join(output_dir, f"overlay_{name}.png"))
        plt.figure(figsize=(8,8))
        plt.imshow(img)
        plt.title(f"{address}\n{name} | A={result['lawn_area_ft2']:.0f} ft² | conf={result['confidence_score']:.2f}({result['confidence_grade']})")
        plt.axis('off')
        plt.savefig(os.path.join(output_dir, "best_overlay.png"), dpi=160, bbox_inches='tight')
        plt.close()

        # Front/back/sides segmentation
        logger.info("Segmenting front/back/sides...")
        fb_metrics = segment_front_back_sides(labels_np, aoi_np, image, output_dir, CLASS_TO_IDX,
                                             mppx, mppy, px_area_m2, have_geo, bounds_if_geo, name)

        output_files = {
            "best_overlay": os.path.join(output_dir, "best_overlay.png"),
            "front_back_sides_overlay": os.path.join(output_dir, f"overlay_front_back_sides_{name}.png"),
            "metrics_json": os.path.join(output_dir, f"yard_areas_{name}.json")
        }

        logger.info("Analysis complete!")
        return {
            "success": True,
            "message": "Analysis completed successfully",
            "output_files": output_files,
            "metrics": fb_metrics
        }

    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Analysis failed: {str(e)}",
            "output_files": {},
            "metrics": {}
        }

