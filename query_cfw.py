import folium
import geopandas as gpd
import requests

# Fort Worth Official MapServer Layer 2: Council Districts
URL = "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/OpenData_Boundaries/MapServer/2/query?outFields=*&where=1%3D1&f=geojson"

print("Fetching Council Districts from mapit.fortworthtexas.gov...")

# Add User-Agent header so the server accepts the script's connection
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
res = requests.get(URL, headers=headers)
res.raise_for_status()

# Parse GeoJSON directly into a GeoDataFrame
data = res.json()
gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")

print(f"Loaded {len(gdf)} Council Districts successfully.")
print("Columns available:", list(gdf.columns))

# Initialize Folium interactive map centered on Fort Worth
m = folium.Map(
    location=[32.7555, -97.3308], zoom_start=11, tiles="CartoDB positron"
)

# Identify a district label column if present
label_col = next(
    (
        col
        for col in ["DISTRICT", "COUNCIL_DISTRICT", "NAME", "DIST_NAME"]
        if col in gdf.columns
    ),
    gdf.columns[0],
)

# Draw district boundary polygons
folium.GeoJson(
    gdf,
    name="Council Districts",
    style_function=lambda x: {
        "fillColor": "#3186cc",
        "fillOpacity": 0.2,
        "color": "#1f77b4",
        "weight": 2,
    },
    tooltip=folium.GeoJsonTooltip(fields=[label_col], aliases=["District: "]),
).add_to(m)

folium.LayerControl().add_to(m)
m.save("index.html")
print("Saved interactive map to index.html!")