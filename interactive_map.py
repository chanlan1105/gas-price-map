import geopandas as gpd
import pandas as pd
import requests
import folium
import branca.colormap as cm
from datetime import datetime
from zoneinfo import ZoneInfo
import time
from pathlib import Path
import shutil

# Fetch data from the Regie Essence Quebec API
data = None
tries = 0
MAX_TRIES = 3

while tries < MAX_TRIES:
    tries += 1

    print(f"Fetching data, attempt {tries}/{MAX_TRIES}...")

    response = requests.get(
        "https://regieessencequebec.ca/stations.geojson.gz",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
    if response.status_code == 200:
        data = response.json()
        print("Got data")
        break
    else:
        print("Error retrieving data. Waiting 10 seconds...")
        print(response.status_code)
        print(response.text)
        time.sleep(10)
else:
    print(f"Could not fetch data after {MAX_TRIES} attempts. Exiting...")
    exit(1)

print("Parsing data into GeoDataFrame...")
df = gpd.GeoDataFrame.from_features(data["features"])

# The prices column of the df contains an array of dictionaries
# with prices for Regular, Super, and Diesel. Parse these prices
# so each gas type has its own column in the df.
price_dict = df["Prices"].apply(
    lambda prices : {
        item["GasType"]: float(item["Price"].replace("¢", "")) if type(item["Price"]) == str else float("NaN")
        for item in prices
    }
)

price_df: gpd.GeoDataFrame = pd.json_normalize(price_dict)

# Now remove the original column Prices from the df and 
# concat the values we have just parsed.
df.drop("Prices", axis=1, inplace=True)

df: gpd.GeoDataFrame = pd.concat([df, price_df], axis=1)

# Set coordinate reference for basemap
df_crs = df.set_crs(epsg=4326)

REGIONS = ["Montréal", "Laval", "Montérégie"]
base_stations = df_crs[df_crs.Region.isin(REGIONS)]

# Include Lanaudière stations that fall within the Greater Montreal area
# (Terrebonne, Mascouche, Repentigny, L'Assomption). Joliette, Berthierville,
# and other northern Lanaudière cities are excluded via this bounding box.
LANAUDIERE_BBOX = {
    "lat_min": 45.55,
    "lat_max": 45.90,
    "lon_min": -73.80,
    "lon_max": -73.30,
}
lanaudiere = df_crs[df_crs.Region == "Lanaudière"]
lanaudiere_filtered = lanaudiere[
    (lanaudiere.geometry.y >= LANAUDIERE_BBOX["lat_min"]) &
    (lanaudiere.geometry.y <= LANAUDIERE_BBOX["lat_max"]) &
    (lanaudiere.geometry.x >= LANAUDIERE_BBOX["lon_min"]) &
    (lanaudiere.geometry.x <= LANAUDIERE_BBOX["lon_max"])
]

# Include Laurentides stations up to and including the Mont-Tremblant area.
# Stations north of ~46.20°N or west of ~74.80°W are excluded (remote
# northern/western Laurentides beyond the main Autoroute 15 corridor).
LAURENTIDES_BBOX = {
    "lat_max": 46.20,
    "lon_min": -74.80,
}
laurentides = df_crs[df_crs.Region == "Laurentides"]
laurentides_filtered = laurentides[
    (laurentides.geometry.y <= LAURENTIDES_BBOX["lat_max"]) &
    (laurentides.geometry.x >= LAURENTIDES_BBOX["lon_min"])
]

stations = pd.concat([base_stations, lanaudiere_filtered,
                      laurentides_filtered]).drop(columns=['PostalCode', 'Region'])

COLORS = [
    "#0C4415",
    "#39C018",
    "#C0BD18",
    "#D47318",
    "#5C0C08" 
]
quantiles = stations["Régulier"].quantile([0, 0.25, 0.5, 0.75, 1]).tolist()
colormap = cm.LinearColormap(
    colors=COLORS,
    index=quantiles,
    vmin=stations["Régulier"].min(),
    vmax=stations["Régulier"].max()
)

# Compute per-station hex colour so the JS verbose-marker renderer can read
# it directly from GeoJSON feature properties without re-implementing the
# colormap in JavaScript.
stations = stations.copy()
stations["color"] = stations["Régulier"].apply(
    lambda p: colormap(p)[:7] if not pd.isna(p) else "#888888"
)

print("Rendering interactive map...")
inter_map: folium.Map = stations.explore(
    column="Régulier",
    cmap=colormap,
    marker_kwds=dict(radius=5, fill=True),
    marker_type="circle_marker",
    name="Gas Stations",  # name of the layer in the map
    tooltip=[
        "Name",
        "brand",
        "Status",
        "Address",
        "Régulier",
        "Super",
        "Diesel"
    ]
)

folium.TileLayer("CartoDB positron", show=True).add_to(inter_map)
folium.LayerControl().add_to(inter_map)

# Inject a bottom-left info panel showing the render timestamp and data source.
rendered_at = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
info_html = f"""
<div style="
    position: fixed;
    bottom: 20px; left: 20px; z-index: 9999;
    background: rgba(255,255,255,0.88);
    backdrop-filter: blur(6px);
    border-radius: 8px;
    padding: 8px 14px;
    font-family: sans-serif;
    font-size: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.18);
    line-height: 1.6;
">
    🕐 <strong>Updated:</strong> {rendered_at}<br>
    📊 <strong>Source:</strong>&nbsp;
    <a href="https://regieessencequebec.ca/" target="_blank" rel="noopener">
        regieessencequebec.ca
    </a>
</div>
"""
inter_map.get_root().html.add_child(folium.Element(info_html))

# Inject CSS to set the font size of map element popovers (popups and tooltips) to 11px,
# and to strip the default border/background that Leaflet applies to DivIcon containers
# so our verbose SVG markers render without an unwanted white box behind them.
popover_style = """
<style>
    .leaflet-popup-content,
    .leaflet-popup-content *,
    .leaflet-tooltip,
    .leaflet-tooltip *,
    .foliumtooltip,
    .foliumtooltip * {
        font-size: 11px !important;
    }
    /* Verbose gas-price speech-bubble markers */
    .verbose-gas-marker {
        background: none !important;
        border: none !important;
        overflow: visible !important;
    }
    .verbose-gas-marker svg {
        overflow: visible;
        filter: drop-shadow(0 1px 4px rgba(0,0,0,0.40));
    }
</style>
"""
inter_map.get_root().header.add_child(folium.Element(popover_style))

# ---------------------------------------------------------------------------
# Verbose gas-price marker JS
# ---------------------------------------------------------------------------
# This self-contained IIFE runs after the page loads and takes over all
# CircleMarkers produced by Folium's explore().  On every zoomend / moveend it
# runs a greedy collision-detection pass (cheapest station wins) and replaces
# each winning CircleMarker with an SVG speech-bubble DivIcon showing the
# Régulier price.  Stations that don't win stay as plain dots.
# ---------------------------------------------------------------------------
verbose_marker_js = """
<script>
(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────────────────────
    var BW  = 72;   // bubble rectangle width (px)
    var BH  = 26;   // bubble rectangle height (px)
    var TL  = 8;    // tip length (px)
    var TH  = 6;    // tip half-width at base (px)
    var CR  = 5;    // rectangle corner radius (px)
    var DR  = 5;    // dot radius (px)
    var GP  = 4;    // minimum gap between bounding boxes (px)
    var MIN_ZOOM = 12;  // below this zoom level, always use dots

    // Determine maximum verbose markers allowed based on screen width
    function getMaxVerboseMarkers() {
        var w = window.innerWidth;
        if (w < 768)   return 8;  // xs and sm
        if (w < 992)   return 14; // md
        if (w < 1200)  return 20; // lg
        return 25;                // xl+
    }

    var mapObj, stations = [], vLayer, timer;

    // ── Colour helpers ─────────────────────────────────────────────────────────

    // Relative luminance (WCAG 2.x) of a 6-char hex colour string.
    function luminance(hex) {
        hex = hex.replace('#', '');
        function lin(c) {
            c /= 255;
            return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * lin(parseInt(hex.slice(0, 2), 16))
             + 0.7152 * lin(parseInt(hex.slice(2, 4), 16))
             + 0.0722 * lin(parseInt(hex.slice(4, 6), 16));
    }

    function hexToRgba(hex, a) {
        hex = hex.replace('#', '');
        return 'rgba(' + parseInt(hex.slice(0,2),16) + ','
                       + parseInt(hex.slice(2,4),16) + ','
                       + parseInt(hex.slice(4,6),16) + ',' + a + ')';
    }

    // ── SVG speech-bubble builder ──────────────────────────────────────────────
    //
    // Returns { svg, svgW, svgH, ax, ay } where (ax, ay) is the iconAnchor
    // (the pixel within the SVG that maps to the station lat/lng).
    //
    // Tip directions:
    //   'down'  – tip points down   (marker sits above the station)
    //   'up'    – tip points up     (marker sits below the station)
    //   'left'  – tip points left   (marker sits to the right of the station)
    //   'right' – tip points right  (marker sits to the left of the station)
    //
    // For 'left' and 'right', the two corners adjacent to the tip are kept
    // sharp to avoid a geometric gap between the corner arc and the tip base.

    function buildBubble(label, color, dir) {
        var W = BW, H = BH, T = TL, th = TH, r = CR;
        var cx = W / 2, mY = H / 2;
        var svgW, svgH, d, tx, ty, ax, ay;

        if (dir === 'down') {
            svgW = W;     svgH = H + T;
            tx = cx;      ty = mY;      ax = cx;   ay = svgH;
            d = 'M '+(r)+' 0'
              +' L '+(W-r)+' 0 Q '+W+' 0 '+W+' '+r
              +' L '+W+' '+(H-r)+' Q '+W+' '+H+' '+(W-r)+' '+H
              +' L '+(cx+th)+' '+H+' L '+cx+' '+svgH+' L '+(cx-th)+' '+H
              +' L '+r+' '+H+' Q 0 '+H+' 0 '+(H-r)
              +' L 0 '+r+' Q 0 0 '+r+' 0 Z';

        } else if (dir === 'up') {
            svgW = W;     svgH = H + T;
            tx = cx;      ty = T + mY;  ax = cx;   ay = 0;
            d = 'M '+cx+' 0'
              +' L '+(cx+th)+' '+T+' L '+(W-r)+' '+T
              +' Q '+W+' '+T+' '+W+' '+(T+r)
              +' L '+W+' '+(svgH-r)+' Q '+W+' '+svgH+' '+(W-r)+' '+svgH
              +' L '+r+' '+svgH+' Q 0 '+svgH+' 0 '+(svgH-r)
              +' L 0 '+(T+r)+' Q 0 '+T+' '+r+' '+T
              +' L '+(cx-th)+' '+T+' Z';

        } else if (dir === 'left') {
            // Tip points left; rectangle is to the right of the tip.
            // No corner curves on the left side to keep the geometry clean.
            svgW = W + T; svgH = H;
            tx = T + cx;  ty = mY;      ax = 0;    ay = mY;
            d = 'M 0 '+mY
              +' L '+T+' '+(mY-th)+' L '+T+' 0'
              +' L '+(svgW-r)+' 0 Q '+svgW+' 0 '+svgW+' '+r
              +' L '+svgW+' '+(H-r)+' Q '+svgW+' '+H+' '+(svgW-r)+' '+H
              +' L '+T+' '+H+' L '+T+' '+(mY+th)+' Z';

        } else { // 'right'
            // Tip points right; rectangle is to the left of the tip.
            // No corner curves on the right side to keep the geometry clean.
            svgW = W + T; svgH = H;
            tx = cx;      ty = mY;      ax = svgW; ay = mY;
            d = 'M '+svgW+' '+mY
              +' L '+W+' '+(mY-th)+' L '+W+' 0'
              +' L '+r+' 0 Q 0 0 0 '+r
              +' L 0 '+(H-r)+' Q 0 '+H+' '+r+' '+H
              +' L '+W+' '+H+' L '+W+' '+(mY+th)+' Z';
        }

        var fillCol  = hexToRgba(color, 0.35);
        var textCol  = luminance(color) > 0.179 ? '#111111' : '#ffffff';

        var svg = '<svg width="'+svgW+'" height="'+svgH+'"'
                +' xmlns="http://www.w3.org/2000/svg">'
                +'<path d="'+d+'" fill="'+fillCol+'" stroke="'+color+'"'
                +' stroke-width="2" stroke-linejoin="round"/>'
                +'<text x="'+tx+'" y="'+ty+'" dominant-baseline="middle"'
                +' text-anchor="middle" fill="'+textCol+'"'
                +' font-family="\\'Helvetica Neue\\',Helvetica,Arial,sans-serif"'
                +' font-size="12" font-weight="700">'+label+'</text>'
                +'</svg>';

        return { svg: svg, svgW: svgW, svgH: svgH, ax: Math.round(ax), ay: Math.round(ay) };
    }

    // ── Bounding-box helpers ───────────────────────────────────────────────────

    function verboseBox(px, py, dir) {
        var W = BW, H = BH, T = TL;
        if (dir === 'down')  return { x1: px - W/2,   y1: py - H - T, x2: px + W/2,   y2: py       };
        if (dir === 'up')    return { x1: px - W/2,   y1: py,         x2: px + W/2,   y2: py + H+T };
        if (dir === 'left')  return { x1: px,          y1: py - H/2,   x2: px + W+T,   y2: py + H/2 };
        /* right */          return { x1: px - W - T,  y1: py - H/2,   x2: px,         y2: py + H/2 };
    }

    function dotBox(px, py) {
        var r = DR + GP;
        return { x1: px - r, y1: py - r, x2: px + r, y2: py + r };
    }

    function clashes(a, b) {
        return a.x1 - GP < b.x2 && a.x2 + GP > b.x1
            && a.y1 - GP < b.y2 && a.y2 + GP > b.y1;
    }

    function isTaken(box, occupied) {
        for (var i = 0; i < occupied.length; i++) {
            if (clashes(box, occupied[i])) return true;
        }
        return false;
    }

    // ── Main render pass ───────────────────────────────────────────────────────

    var DIRS = ['down', 'up', 'right', 'left'];

    function update() {
        if (!mapObj || !stations.length) return;

        var zoom     = mapObj.getZoom();
        var bounds   = mapObj.getBounds();
        var occupied = [];

        // Clear previously placed verbose markers
        vLayer.clearLayers();

        // Partition stations into visible-with-price vs everything-else
        var visible = [], rest = [];
        stations.forEach(function (s) {
            (bounds.contains(s.ll) && s.price !== null ? visible : rest).push(s);
        });

        // Stations that are off-screen or have no price: always restore their dot
        rest.forEach(function (s) { s.circle.setStyle(s.orig); });

        // Below the zoom threshold: all dots
        if (zoom < MIN_ZOOM) {
            visible.forEach(function (s) { s.circle.setStyle(s.orig); });
            return;
        }

        // Rule 1: If there are many gas stations visible on the map (more than 300),
        // none of them should show as verbose markers.
        if (visible.length > 300) {
            visible.forEach(function (s) { s.circle.setStyle(s.orig); });
            return;
        }

        // Precompute coordinates and distance to the screen center for each visible station
        var centerPt = mapObj.latLngToLayerPoint(mapObj.getCenter());
        var size = mapObj.getSize();
        var R = Math.min(size.x, size.y) * 0.35; // responsive radius for center region

        visible.forEach(function (s) {
            s.pt = mapObj.latLngToLayerPoint(s.ll);
            s.distToCenter = Math.sqrt(Math.pow(s.pt.x - centerPt.x, 2) + Math.pow(s.pt.y - centerPt.y, 2));
            s.inCenter = (s.distToCenter <= R);
            s.selected = false;
            s.placedDir = null;
        });

        // Split into center region vs outer region
        var centerStations = [];
        var outerStations = [];
        visible.forEach(function (s) {
            if (s.inCenter) {
                centerStations.push(s);
            } else {
                outerStations.push(s);
            }
        });

        var selectedCount = 0;
        var maxVerboseLimit = getMaxVerboseMarkers();

        function selectAndPlace(candidates) {
            while (selectedCount < maxVerboseLimit) {
                var placeables = [];
                candidates.forEach(function (s) {
                    if (s.selected) return;

                    var valid = null;
                    for (var i = 0; i < DIRS.length; i++) {
                        var box = verboseBox(s.pt.x, s.pt.y, DIRS[i]);
                        if (!isTaken(box, occupied)) {
                            valid = { dir: DIRS[i], box: box };
                            break;
                        }
                    }
                    if (valid) {
                        placeables.push({ station: s, dir: valid.dir, box: valid.box });
                    }
                });

                if (placeables.length === 0) {
                    break;
                }

                var bestIdx = 0;
                if (selectedCount === 0) {
                    // Seed with the station closest to the center
                    var minDist = Infinity;
                    for (var i = 0; i < placeables.length; i++) {
                        if (placeables[i].station.distToCenter < minDist) {
                            minDist = placeables[i].station.distToCenter;
                            bestIdx = i;
                        }
                    }
                } else {
                    // Subsequent selections: maximize score = 0.5 * normD + 0.5 * normP
                    var bestScore = -1;
                    var dMins = [];
                    var pMins = [];
                    var maxDMin = 0;
                    var maxPMin = 0;

                    var selectedStations = [];
                    visible.forEach(function (s) {
                        if (s.selected) {
                            selectedStations.push(s);
                        }
                    });

                    placeables.forEach(function (p) {
                        var s = p.station;
                        var dMin = Infinity;
                        var pMin = Infinity;
                        selectedStations.forEach(function (sel) {
                            var dist = Math.sqrt(Math.pow(s.pt.x - sel.pt.x, 2) + Math.pow(s.pt.y - sel.pt.y, 2));
                            if (dist < dMin) dMin = dist;

                            var pDiff = Math.abs(s.price - sel.price);
                            if (pDiff < pMin) pMin = pDiff;
                        });
                        dMins.push(dMin);
                        pMins.push(pMin);
                        if (dMin > maxDMin) maxDMin = dMin;
                        if (pMin > maxPMin) maxPMin = pMin;
                    });

                    placeables.forEach(function (p, idx) {
                        var normD = maxDMin > 0 ? dMins[idx] / maxDMin : 1;
                        var normP = maxPMin > 0 ? pMins[idx] / maxPMin : 1;
                        var score = 0.5 * normD + 0.5 * normP;
                        if (score > bestScore) {
                            bestScore = score;
                            bestIdx = idx;
                        }
                    });
                }

                // Place candidate
                var winner = placeables[bestIdx];
                winner.station.selected = true;
                winner.station.placedDir = winner.dir;
                occupied.push(winner.box);
                selectedCount++;
            }
        }

        // Run selection: center region first, then outer region if slots are left
        selectAndPlace(centerStations);
        selectAndPlace(outerStations);

        // Render pass
        visible.forEach(function (s) {
            if (s.selected) {
                // --- Verbose marker ---
                s.circle.setStyle({ radius: 0, opacity: 0, fillOpacity: 0, weight: 0 });

                var b   = buildBubble(s.price.toFixed(1) + '\u00a2', s.color, s.placedDir);
                var ico = L.divIcon({
                    html:       b.svg,
                    iconSize:   [b.svgW, b.svgH],
                    iconAnchor: [b.ax,   b.ay],
                    className:  'verbose-gas-marker'
                });
                var m = L.marker(s.ll, { icon: ico, interactive: true });

                (function (circle) {
                    m.on('click',     function () { circle.openPopup();   });
                    m.on('mouseover', function () { circle.openTooltip(); });
                    m.on('mouseout',  function () { circle.closeTooltip(); });
                }(s.circle));

                vLayer.addLayer(m);
            } else {
                // --- Dot fallback ---
                s.circle.setStyle(s.orig);
                // Register its dot area as occupied to prevent overlaps
                var pt = mapObj.latLngToLayerPoint(s.ll);
                occupied.push(dotBox(pt.x, pt.y));
            }
        });
    }

    // ── Initialisation ─────────────────────────────────────────────────────────

    function init() {
        // Locate the Leaflet map instance created by Folium
        for (var k in window) {
            try {
                var v = window[k];
                if (v && v._leaflet_id != null
                      && typeof v.getZoom  === 'function'
                      && typeof v.on       === 'function') {
                    mapObj = v;
                    break;
                }
            } catch (ignore) {}
        }
        if (!mapObj) {
            console.warn('[VerboseMarkers] No Leaflet map instance found.');
            return;
        }

        // Separate layer group for verbose DivIcon markers
        vLayer = L.layerGroup().addTo(mapObj);

        // Recursively walk all layers to harvest every CircleMarker
        // that carries a GeoJSON Point feature (i.e. gas stations).
        function harvest(layer) {
            if (typeof layer.getLatLng  === 'function'
             && typeof layer.getRadius  === 'function'
             && layer.feature
             && layer.feature.geometry
             && layer.feature.geometry.type === 'Point') {

                var p     = layer.feature.properties;
                var price = parseFloat(p['R\u00e9gulier']);
                var col   = String(p['color'] || '#888888');

                stations.push({
                    ll:    layer.getLatLng(),
                    price: isNaN(price) ? null : price,
                    color: col.slice(0, 7),   // ensure exactly 6-char hex
                    circle: layer,
                    orig: {
                        radius:      layer.options.radius      || 5,
                        opacity:     layer.options.opacity     != null ? layer.options.opacity     : 1,
                        fillOpacity: layer.options.fillOpacity != null ? layer.options.fillOpacity : 0.8,
                        weight:      layer.options.weight      || 1
                    }
                });

            } else if (typeof layer.eachLayer === 'function') {
                layer.eachLayer(harvest);
            }
        }
        mapObj.eachLayer(harvest);
        console.log('[VerboseMarkers] ' + stations.length + ' stations indexed.');

        update();
        mapObj.on('zoomend', update);
        mapObj.on('moveend', function () {
            clearTimeout(timer);
            timer = setTimeout(update, 200);
        });
        mapObj.on('resize', function () {
            clearTimeout(timer);
            timer = setTimeout(update, 200);
        });
    }

    // Defer until everything (Leaflet, Folium JS) has finished loading
    window.addEventListener('load', function () { setTimeout(init, 300); });

}());
</script>
"""
inter_map.get_root().html.add_child(folium.Element(verbose_marker_js))

# Set map page title
inter_map.get_root().title = "Québec Real-Time Gas Map"

# Add favicon link to header
favicon_link = '<link rel="shortcut icon" href="favicon.png" type="image/png">'
inter_map.get_root().header.add_child(folium.Element(favicon_link))

print("Saving map file...")
build_dir = Path("build")
build_dir.mkdir(parents=True, exist_ok=True)
inter_map.save(build_dir / "index.html")

# Copy favicon to build folder
favicon_src = Path("media/favicon.png")
if favicon_src.exists():
    shutil.copy(favicon_src, build_dir / "favicon.png")
    print("Favicon copied to build/favicon.png")

print(f"Map saved to build/index.html (rendered at {rendered_at})")