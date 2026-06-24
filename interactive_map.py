import geopandas as gpd
import pandas as pd
import requests
import folium
import branca.colormap as cm
from datetime import datetime
from zoneinfo import ZoneInfo

# Fetch data from the Regie Essence Quebec API
data = None
tries = 0
MAX_TRIES = 3

while tries < MAX_TRIES:
    tries += 1

    print(f"Fetching data, attempt {tries}/{MAX_TRIES}...")

    response = requests.get("https://regieessencequebec.ca/stations.geojson.gz")
    if response.status_code == 200:
        data = response.json()
        print("Got data")
        break
    else:
        print("Error retrieving data")
        print(response.status_code)
        print(response)
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

price_df = pd.json_normalize(price_dict)

# Now remove the original column Prices from the df and 
# concat the values we have just parsed.
df.drop("Prices", axis=1, inplace=True)

df = pd.concat([df, price_df], axis=1)

# Set coordinate reference for basemap
df_crs = df.set_crs(epsg=4326)

REGIONS = ["Montréal", "Laval", "Montérégie", "Laurentides"]
stations = df_crs[df_crs.Region.isin(REGIONS)]

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

print("Rendering interactive map...")
inter_map: folium.Map = stations.explore(
    column="Régulier",
    cmap=colormap,
    marker_kwds=dict(radius=5, fill=True),
    marker_type="circle_marker",
    name="Gas Stations",  # name of the layer in the map
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

inter_map.save("index.html")
print(f"Map saved to index.html (rendered at {rendered_at})")