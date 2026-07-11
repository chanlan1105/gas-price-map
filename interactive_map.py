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


class MapData:
    """
    A class to fetch and parse data from the Regie Essence Quebec API.
    """
    __url: str = "https://regieessencequebec.ca/stations.geojson.gz"
    __headers: dict = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    MAX_TRIES: int = 3

    def __init__(self):
        self.data = None
        self.tries = 0
        self.df: gpd.GeoDataFrame = None
    
    def fetch_data(self):
        """
        Fetches data from the Regie Essence Quebec API. Raises ValueError if data cannot be fetched after MAX_TRIES attempts.
        """
        while self.tries < self.MAX_TRIES:
            self.tries += 1
            print(f"Fetching data, attempt {self.tries}/{self.MAX_TRIES}...")

            response = requests.get(self.__url, headers=self.__headers)
            if response.status_code == 200:
                self.data = response.json()
                print("Got data")
                self.tries = 0
                break
            else:
                print("Error retrieving data. Waiting 10 seconds...")
                print(response.status_code)
                print(response.text)
                time.sleep(10)
        else:
            raise ValueError(f"Could not fetch data from the Regie Essence Quebec API after {self.MAX_TRIES} attempts")
    
    def parse_data(self) -> gpd.GeoDataFrame:
        """
        Parses the fetched data into a GeoDataFrame.
        
        Returns:
        --------
        gpd.GeoDataFrame
            The parsed data as a GeoDataFrame.
        """
        print("Parsing data into GeoDataFrame...")
        self.df = gpd.GeoDataFrame.from_features(self.data["features"])
        
        # The prices column of the df contains an array of dictionaries
        # with prices for Regular, Super, and Diesel. Parse these prices
        # so each gas type has its own column in the df.
        price_dict = self.df["Prices"].apply(
            lambda prices : {
                item["GasType"]: float(item["Price"].replace("¢", "")) if type(item["Price"]) == str else float("NaN")
                for item in prices
            }
        )
        
        price_df: gpd.GeoDataFrame = pd.json_normalize(price_dict)
        
        # Now remove the original column Prices from the df and 
        # concat the values we have just parsed.
        self.df.drop("Prices", axis=1, inplace=True)
        self.df = pd.concat([self.df, price_df], axis=1)
        
        # Set coordinate reference for basemap
        self.df = self.df.set_crs(epsg=4326)

        return self.df
    
    def filter_regions(self, regions: dict[str, dict]) -> gpd.GeoDataFrame:
        """
        Filters the GeoDataFrame to include only the specified regions.

        Params:
        -------
        regions: dict[str, dict | None]
            Dictionary of regions to filter by. Each region is a dict with a 
            string key (region name) and a dict value with 'lat_min', 'lat_max', 
            'lon_min', 'lon_max' for a bounding box.

            Any coordinate key set to `None` (or omitted) is treated as unbounded 
            in that direction. For example:
            - Specifying only 'lon_min' will include everything from that longitude 
            eastward to the edge of the coordinate system.
            - Specifying no max values means the filter extends indefinitely upward/rightward.
            - Specifying `None` in place of a `dict` will include the entire region.
        
        Returns:
        --------
        gpd.GeoDataFrame
            The filtered data as a GeoDataFrame.
        """
        if not isinstance(regions, dict):
            raise TypeError("regions must be a dict")

        filtered_dfs = []
        for region, bbox in regions.items():
            region_df = self.df[self.df.Region == region]
            if bbox is not None:
                if "lat_min" in bbox and bbox["lat_min"] is not None:
                    region_df = region_df[region_df.geometry.y >= bbox["lat_min"]]
                if "lat_max" in bbox and bbox["lat_max"] is not None:
                    region_df = region_df[region_df.geometry.y <= bbox["lat_max"]]
                if "lon_min" in bbox and bbox["lon_min"] is not None:
                    region_df = region_df[region_df.geometry.x >= bbox["lon_min"]]
                if "lon_max" in bbox and bbox["lon_max"] is not None:
                    region_df = region_df[region_df.geometry.x <= bbox["lon_max"]]
            filtered_dfs.append(region_df)

        self.df = pd.concat(filtered_dfs)
        return self.df


class MapRenderer:
    """
    A class to render the map.
    """
    COLORS: list[str] = [
        "#0C4415",
        "#39C018",
        "#C0BD18",
        "#D47318",
        "#5C0C08" 
    ]
    __quantiles: list[float] = [0, 0.25, 0.5, 0.75, 1]
    __map_center: tuple[float, float] = (45.55, -73.60)

    def __init__(self, stations: gpd.GeoDataFrame, gas_type: str = "Régulier"):
        self.stations = stations.copy()
        self.gas_type = gas_type
        self.colormap: cm.LinearColormap = None 
        self.inter_map: folium.Map = None
        self.rendered_at: str = None

    def _set_colormap(self):
        quantiles_vals = self.stations[self.gas_type].quantile(self.__quantiles).tolist()
        self.colormap = cm.LinearColormap(
            colors=self.COLORS,
            index=quantiles_vals,
            vmin=self.stations[self.gas_type].min(),
            vmax=self.stations[self.gas_type].max()
        )

        self.stations["color"] = self.stations[self.gas_type].apply(
            lambda p: self.colormap(p)[:7] if not pd.isna(p) else "#888888"
        )

    def _add_info(self):
        """
        Inject a bottom-left info panel showing the render timestamp and data source.
        """

        self.rendered_at = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
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
            🕐 <strong>Updated:</strong> {self.rendered_at}<br>
            📊 <strong>Source:</strong>&nbsp;
            <a href="https://regieessencequebec.ca/" target="_blank" rel="noopener">
                regieessencequebec.ca
            </a>
        </div>
        """
        self.inter_map.get_root().html.add_child(folium.Element(info_html))

    def _update_popover_styles(self):
        """
        Inject CSS to set the font size of map element popovers (popups and tooltips) to 11px,
        and to strip the default border/background that Leaflet applies to DivIcon containers
        so our verbose SVG markers render without an unwanted white box behind them.
        """
        
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
            /* User location marker and pulse effect */
            .user-location-marker {
                background: none !important;
                border: none !important;
            }
            .blue-dot {
                width: 14px;
                height: 14px;
                background-color: #007aff;
                border: 2.5px solid #ffffff;
                border-radius: 50%;
                box-shadow: 0 0 5px rgba(0, 0, 0, 0.4);
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                z-index: 1000;
            }
            .blue-dot-pulse {
                width: 32px;
                height: 32px;
                background-color: rgba(0, 122, 255, 0.25);
                border-radius: 50%;
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                animation: pulse 1.8s infinite ease-out;
                z-index: 999;
                pointer-events: none;
            }
            @keyframes pulse {
                0% {
                    transform: translate(-50%, -50%) scale(0.5);
                    opacity: 1;
                }
                100% {
                    transform: translate(-50%, -50%) scale(2.2);
                    opacity: 0;
                }
            }
            /* Recenter floating action button */
            .recenter-fab {
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 48px;
                height: 48px;
                border-radius: 50%;
                background-color: #ffffff;
                border: none;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                color: #333333;
                font-size: 20px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9999;
                transition: all 0.2s ease-in-out;
            }
            .recenter-fab:hover {
                background-color: #f5f5f5;
                transform: scale(1.05);
                box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
            }
            .recenter-fab:active {
                transform: scale(0.95);
            }
            .fab-loading svg {
                animation: fab-fade 0.6s infinite alternate ease-in-out;
            }
            @keyframes fab-fade {
                0% { opacity: 0.3; }
                100% { opacity: 1; }
            }
        </style>
        """
        self.inter_map.get_root().header.add_child(folium.Element(popover_style))

    def _add_verbose_marker_js(self):
        """
        This self-contained IIFE runs after the page loads and takes over all
        CircleMarkers produced by Folium's `explore()`.  On every zoomend / moveend it
        runs a greedy collision-detection pass (cheapest station wins) and replaces
        each winning CircleMarker with an SVG speech-bubble DivIcon showing the
        Régulier price.  Stations that don't win stay as plain dots.
        """

        js_path = Path(__file__).parent / "assets" / "verbose_marker.js"
        js_content = js_path.read_text(encoding="utf-8")

        verbose_marker_js = f"<script>{js_content}</script>"
        self.inter_map.get_root().html.add_child(folium.Element(verbose_marker_js))
    
    def _add_geolocation_js(self):
        """
        Add geolocation and recenter FAB JS/HTML.
        """
        js_path = Path(__file__).parent / "assets" / "geolocation.html"
        js_content = js_path.read_text(encoding="utf-8")

        startup_path = Path(__file__).parent / "assets" / "startup_ux.html"
        startup_content = startup_path.read_text(encoding="utf-8")

        self.inter_map.get_root().html.add_child(folium.Element(js_content))
        self.inter_map.get_root().html.add_child(folium.Element(startup_content))

    def render(self):
        self._set_colormap()
        self.inter_map = self.stations.explore(
            column=self.gas_type,
            cmap=self.colormap,
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

        folium.TileLayer("CartoDB positron", show=True).add_to(self.inter_map)
        folium.LayerControl().add_to(self.inter_map)

        self._add_info()
        self._update_popover_styles()
        self._add_verbose_marker_js()
        self._add_geolocation_js()
        
        # Set map page title
        self.inter_map.get_root().title = "Québec Real-Time Gas Map"

        # Add favicon link to header
        favicon_link = '<link rel="shortcut icon" href="favicon.png" type="image/png">'
        self.inter_map.get_root().header.add_child(folium.Element(favicon_link))

        print("Saving map file...")
        build_dir = Path("build")
        build_dir.mkdir(parents=True, exist_ok=True)
        self.inter_map.save(build_dir / "index.html")

        # Copy favicon to build folder
        favicon_src = Path("media/favicon.png")
        if favicon_src.exists():
            shutil.copy(favicon_src, build_dir / "favicon.png")
            print("Favicon copied to build/favicon.png")

        print(f"Map saved to build/index.html (rendered at {self.rendered_at})")
        

# Fetch and parse data using the class
map_data = MapData()
map_data.fetch_data()
map_data.parse_data()
map_data.filter_regions({
    "Montréal": None, 
    "Laval": None, 
    "Montérégie": None,
    "Lanaudière": {
        "lat_min": 45.55,
        "lat_max": 45.90,
        "lon_min": -73.80,
        "lon_max": -73.30,
    },
    "Laurentides": {
        "lat_max": 46.20,
        "lon_min": -74.80,
    },
})

rendered_map = MapRenderer(map_data.df)
rendered_map.render()
