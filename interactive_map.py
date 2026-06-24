import geopandas as gpd
import pandas as pd
import requests
import folium
import branca.colormap as cm
# from flask import Flask

# app = Flask(__name__)

# Fetch data from the Regie Essence Quebec API
response = requests.get("https://regieessencequebec.ca/stations.geojson.gz")
if response.status_code == 200:
    data = response.json()
else:
    print("Error retrieving data")
    print(response.status_code)
    print(response.text())
    exit(1)

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

inter_map: folium.Map = stations.explore(
    column="Régulier",
    cmap=colormap,
    marker_kwds=dict(radius=5, fill=True),
    marker_type="circle_marker",
    name="Gas Stations"  # name of the layer in the map
)

folium.TileLayer("CartoDB positron", show=False).add_to(inter_map)
folium.LayerControl().add_to(inter_map)

inter_map.show_in_browser()