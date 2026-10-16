import folium
import geopandas as gpd
import requests

# 1. Fort Worth Open Data Public FeatureServer Endpoints
# Example: Council District Boundaries (Polygons) & Code Violations (Points)
DISTRICTS_URL = "https://services.arcgis.com/8VkOubw30CJvGz6t/arcgis/rest/services/CFW_Council_Districts/FeatureServer/0/query"
VIOLATIONS_URL = "https://services.arcgis.com/8VkOubw30CJvGz6t/arcgis/rest/services/CFW_Code_Violations_Points/FeatureServer/0/query"


def fetch_geojson(base_url, where_clause="1=1", limit=1000):
  """Queries Fort Worth's ArcGIS REST API directly for GeoJSON."""
  params = {
      "where": where_clause,
      "outFields": "*",
      "f": "geojson",
      "resultRecordCount": limit,
  }
  res = requests.get(base_url, params=params)
  return gpd.read_file(res.text)


print("Fetching Council Districts...")
districts_gdf = fetch_geojson(DISTRICTS_URL)

print("Fetching Code Violation points...")
violations_gdf = fetch_geojson(
    VIOLATIONS_URL, where_clause="STATUS = 'Open'", limit=500
)

# 2. Ensure Coordinate Systems Match (EPSG 4326 = standard Lat/Long WGS84)
districts_gdf = districts_gdf.to_crs(epsg=4326)
violations_gdf = violations_gdf.to_crs(epsg=4326)

# 3. SPATIAL QUERY: Spatial Join / Point-in-Polygon intersection
# Identifies which Council District each violation falls inside
joined_gdf = gpd.sjoin(violations_gdf, districts_gdf, predicate="within")

print(f"Successfully joined {len(joined_gdf)} points to districts.")
print(joined_gdf[["CASE_NUMBER", "DISTRICT", "geometry"]].head())

# 4. EXPORT TO INTERACTIVE WEB MAP
# Centers map near Downtown Fort Worth (32.7555, -97.3308)
m = folium.Map(
    location=[32.7555, -97.3308], zoom_start=11, tiles="CartoDB positron"
)

# Add District outlines
folium.GeoJson(
    districts_gdf,
    name="Council Districts",
    style_function=lambda x: {
        "fillColor": "transparent",
        "color": "#1f77b4",
        "weight": 2,
    },
).add_to(m)

# Add Violation points as clustered markers
for _, row in joined_gdf.iterrows():
  folium.CircleMarker(
      location=[row.geometry.y, row.geometry.x],
      radius=4,
      color="#d62728",
      fill=True,
      fill_opacity=0.7,
      popup=f"Case: {row.get('CASE_NUMBER', 'N/A')}<br>District: {row.get('DISTRICT', 'N/A')}",
  ).add_to(m)

# Save as index.html (ready for GitHub Pages)
m.save("index.html")
print("Saved interactive map to index.html.")
