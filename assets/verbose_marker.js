(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────────────────────
    var BW = 72;   // bubble rectangle width (px)
    var BH = 26;   // bubble rectangle height (px)
    var TL = 8;    // tip length (px)
    var TH = 6;    // tip half-width at base (px)
    var CR = 5;    // rectangle corner radius (px)
    var DR = 5;    // dot radius (px)
    var GP = 4;    // minimum gap between bounding boxes (px)
    var MIN_ZOOM = 12;  // below this zoom level, always use dots

    // Fields displayed in the tooltip and popup, matching the columns
    // passed to explore() in interactive_map.py.
    var TOOLTIP_FIELDS = ['Name', 'brand', 'Status', 'Address', 'Régulier', 'Super', 'Diesel'];

    // Determine maximum verbose markers allowed based on screen width
    function getMaxVerboseMarkers() {
        var w = window.innerWidth;
        if (w < 768) return 8;  // xs and sm
        if (w < 992) return 14; // md
        if (w < 1200) return 20; // lg
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
        return 'rgba(' + parseInt(hex.slice(0, 2), 16) + ','
            + parseInt(hex.slice(2, 4), 16) + ','
            + parseInt(hex.slice(4, 6), 16) + ',' + a + ')';
    }

    // ── Tooltip / popup HTML builder ────────────────────────────────────────────
    //
    // Builds an HTML table from a GeoJSON feature's properties, matching
    // the format that Folium's GeoJsonTooltip / GeoJsonPopup generates.

    function buildInfoTable(props) {
        var rows = '';
        for (var i = 0; i < TOOLTIP_FIELDS.length; i++) {
            var key = TOOLTIP_FIELDS[i];
            var val = props[key];
            if (val === null || val === undefined) val = '';
            else if (typeof val === 'object') val = JSON.stringify(val);
            rows += '<tr><th>' + key + '</th><td>' + val + '</td></tr>';
        }
        return '<table>' + rows + '</table>';
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
            svgW = W; svgH = H + T;
            tx = cx; ty = mY; ax = cx; ay = svgH;
            d = 'M ' + (r) + ' 0'
                + ' L ' + (W - r) + ' 0 Q ' + W + ' 0 ' + W + ' ' + r
                + ' L ' + W + ' ' + (H - r) + ' Q ' + W + ' ' + H + ' ' + (W - r) + ' ' + H
                + ' L ' + (cx + th) + ' ' + H + ' L ' + cx + ' ' + svgH + ' L ' + (cx - th) + ' ' + H
                + ' L ' + r + ' ' + H + ' Q 0 ' + H + ' 0 ' + (H - r)
                + ' L 0 ' + r + ' Q 0 0 ' + r + ' 0 Z';

        } else if (dir === 'up') {
            svgW = W; svgH = H + T;
            tx = cx; ty = T + mY; ax = cx; ay = 0;
            d = 'M ' + cx + ' 0'
                + ' L ' + (cx + th) + ' ' + T + ' L ' + (W - r) + ' ' + T
                + ' Q ' + W + ' ' + T + ' ' + W + ' ' + (T + r)
                + ' L ' + W + ' ' + (svgH - r) + ' Q ' + W + ' ' + svgH + ' ' + (W - r) + ' ' + svgH
                + ' L ' + r + ' ' + svgH + ' Q 0 ' + svgH + ' 0 ' + (svgH - r)
                + ' L 0 ' + (T + r) + ' Q 0 ' + T + ' ' + r + ' ' + T
                + ' L ' + (cx - th) + ' ' + T + ' Z';

        } else if (dir === 'left') {
            // Tip points left; rectangle is to the right of the tip.
            // No corner curves on the left side to keep the geometry clean.
            svgW = W + T; svgH = H;
            tx = T + cx; ty = mY; ax = 0; ay = mY;
            d = 'M 0 ' + mY
                + ' L ' + T + ' ' + (mY - th) + ' L ' + T + ' 0'
                + ' L ' + (svgW - r) + ' 0 Q ' + svgW + ' 0 ' + svgW + ' ' + r
                + ' L ' + svgW + ' ' + (H - r) + ' Q ' + svgW + ' ' + H + ' ' + (svgW - r) + ' ' + H
                + ' L ' + T + ' ' + H + ' L ' + T + ' ' + (mY + th) + ' Z';

        } else { // 'right'
            // Tip points right; rectangle is to the left of the tip.
            // No corner curves on the right side to keep the geometry clean.
            svgW = W + T; svgH = H;
            tx = cx; ty = mY; ax = svgW; ay = mY;
            d = 'M ' + svgW + ' ' + mY
                + ' L ' + W + ' ' + (mY - th) + ' L ' + W + ' 0'
                + ' L ' + r + ' 0 Q 0 0 0 ' + r
                + ' L 0 ' + (H - r) + ' Q 0 ' + H + ' ' + r + ' ' + H
                + ' L ' + W + ' ' + H + ' L ' + W + ' ' + (mY + th) + ' Z';
        }

        var fillCol = hexToRgba(color, 0.35);
        var textCol = luminance(color) > 0.179 ? '#111111' : '#ffffff';

        var svg = '<svg width="' + svgW + '" height="' + svgH + '"'
            + ' xmlns="http://www.w3.org/2000/svg">'
            + '<path d="' + d + '" fill="' + fillCol + '" stroke="' + color + '"'
            + ' stroke-width="2" stroke-linejoin="round"/>'
            + '<text x="' + tx + '" y="' + ty + '" dominant-baseline="middle"'
            + ' text-anchor="middle" fill="' + textCol + '"'
            + ' font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif"'
            + ' font-size="12" font-weight="700">' + label + '</text>'
            + '</svg>';

        return { svg: svg, svgW: svgW, svgH: svgH, ax: Math.round(ax), ay: Math.round(ay) };
    }

    // ── Bounding-box helpers ───────────────────────────────────────────────────

    function verboseBox(px, py, dir) {
        var W = BW, H = BH, T = TL;
        if (dir === 'down') return { x1: px - W / 2, y1: py - H - T, x2: px + W / 2, y2: py };
        if (dir === 'up') return { x1: px - W / 2, y1: py, x2: px + W / 2, y2: py + H + T };
        if (dir === 'left') return { x1: px, y1: py - H / 2, x2: px + W + T, y2: py + H / 2 };
        /* right */          return { x1: px - W - T, y1: py - H / 2, x2: px, y2: py + H / 2 };
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

        var zoom = mapObj.getZoom();
        var bounds = mapObj.getBounds();
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

        var meanPrice = 0;
        var stdDev = 0;
        if (visible.length > 0) {
            var sum = 0;
            visible.forEach(function (s) {
                sum += s.price;
            });
            meanPrice = sum / visible.length;

            var varianceSum = 0;
            visible.forEach(function (s) {
                varianceSum += Math.pow(s.price - meanPrice, 2);
            });
            stdDev = Math.sqrt(varianceSum / visible.length);
        }

        visible.forEach(function (s) {
            s.zScore = stdDev > 0 ? (s.price - meanPrice) / stdDev : 0;
        });

        var zMin = Infinity;
        var zMax = -Infinity;
        visible.forEach(function (s) {
            if (s.zScore < zMin) zMin = s.zScore;
            if (s.zScore > zMax) zMax = s.zScore;
        });

        visible.forEach(function (s) {
            s.pt = mapObj.latLngToLayerPoint(s.ll);
            s.distToCenter = Math.sqrt(Math.pow(s.pt.x - centerPt.x, 2) + Math.pow(s.pt.y - centerPt.y, 2));
            s.inCenter = (s.distToCenter <= R);
            s.selected = false;
            s.placedDir = null;

            s.cheapness = (zMax > zMin) ? (zMax - s.zScore) / (zMax - zMin) : 1.0;
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
                        var cheapness = p.station.cheapness;
                        var score = 0.4 * normD + 0.4 * normP + 0.2 * cheapness;
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

                var b = buildBubble(s.price.toFixed(1) + '\u00a2', s.color, s.placedDir);
                var ico = L.divIcon({
                    html: b.svg,
                    iconSize: [b.svgW, b.svgH],
                    iconAnchor: [b.ax, b.ay],
                    className: 'verbose-gas-marker'
                });
                var m = L.marker(s.ll, { icon: ico, interactive: true });

                // Build tooltip HTML from the station's feature
                // properties and bind it directly to the verbose marker.
                // We cannot proxy through the hidden circle because Leaflet
                // refuses to show tooltips on a CircleMarker with radius 0.
                var infoHtml = buildInfoTable(s.circle.feature.properties);
                m.bindTooltip(infoHtml, { sticky: true, className: 'foliumtooltip' });

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
                    && typeof v.getZoom === 'function'
                    && typeof v.on === 'function') {
                    mapObj = v;
                    break;
                }
            } catch (ignore) { }
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
            if (typeof layer.getLatLng === 'function'
                && typeof layer.getRadius === 'function'
                && layer.feature
                && layer.feature.geometry
                && layer.feature.geometry.type === 'Point') {

                var p = layer.feature.properties;
                var price = parseFloat(p['GAS_TYPE_PLACEHOLDER']);
                var col = String(p['color'] || '#888888');

                stations.push({
                    ll: layer.getLatLng(),
                    price: isNaN(price) ? null : price,
                    color: col.slice(0, 7),   // ensure exactly 6-char hex
                    circle: layer,
                    orig: {
                        radius: layer.options.radius || 5,
                        opacity: layer.options.opacity != null ? layer.options.opacity : 1,
                        fillOpacity: layer.options.fillOpacity != null ? layer.options.fillOpacity : 0.8,
                        weight: layer.options.weight || 1
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