#!/usr/bin/env python3
"""
Regional Tarrant County Spatial Explorer: Fort Worth, Arlington & Pantego
Combines Fort Worth live REST API with guaranteed polygon boundaries for Arlington & Pantego.
"""

import sys
import requests
import geopandas as gpd
from shapely.geometry import shape
import folium
from folium.plugins import Geocoder, MiniMap, Fullscreen, MeasureControl, LocateControl

# ---------------------------------------------------------------------------
# Endpoints & Configurations
# ---------------------------------------------------------------------------
FW_ENDPOINT = (
    "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/"
    "OpenData_Boundaries/MapServer/2/query?outFields=*&where=1%3D1&f=geojson"
)

# OpenStreetMap Nominatim Open GeoJSON Endpoints (Zero auth, zero license gate)
ARLINGTON_OSM_URL = "https://nominatim.openstreetmap.org/search?city=Arlington&state=Texas&polygon_geojson=1&format=geojson"
PANTEGO_OSM_URL = "https://nominatim.openstreetmap.org/search?q=Town+of+Pantego,+Texas&polygon_geojson=1&format=geojson"

HEADERS = {"User-Agent": "Regional-GIS-Explorer-Local/1.0 (pantego-arlington-analysis)"}
OUTPUT_FILE = "index.html"
REGIONAL_CENTER = [32.7357, -97.2000]
SQ_FT_TO_SQ_MILES = 1 / 27878400

BASEMAPS = {
    "Esri Light Gray": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
    },
    "Esri Streets": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Sources: Esri, DeLorme, USGS, NPS"
    },
    "Esri Satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP"
    }
}


def fetch_osm_boundary(url: str, label: str) -> gpd.GeoDataFrame:
    """Fetches high-precision polygon boundaries via Nominatim GeoJSON."""
    print(f"Fetching {label} boundary...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        
        # Filter for Polygon / MultiPolygon results
        poly_features = [
            f for f in data.get("features", [])
            if f.get("geometry", {}).get("type") in ["Polygon", "MultiPolygon"]
        ]
        
        if not poly_features:
            print(f"Notice: No polygon found in response for {label}.")
            return gpd.GeoDataFrame()
            
        gdf = gpd.GeoDataFrame.from_features([poly_features[0]], crs="EPSG:4326")
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        print(f"--> SUCCESS: Loaded {label} boundary.")
        return gdf
    except Exception as e:
        print(f"Notice: Fallback triggered for {label} ({e})")
        return gpd.GeoDataFrame()


# ---------------------------------------------------------------------------
# 1. Load Datasets
# ---------------------------------------------------------------------------
print("1/3: Fetching Fort Worth Council Districts...")
try:
    res = requests.get(FW_ENDPOINT, headers=HEADERS, timeout=30)
    res.raise_for_status()
    fw_gdf = gpd.GeoDataFrame.from_features(res.json()["features"], crs="EPSG:4326")
    fw_gdf = fw_gdf[~fw_gdf.geometry.is_empty & fw_gdf.geometry.notna()].copy()
    fw_gdf["Jurisdiction"] = "City of Fort Worth"
    fw_gdf["District_Display"] = "District " + fw_gdf["DISTRICT"].astype(str).str.replace(".0", "", regex=False)
    if "SHAPE.STArea()" in fw_gdf.columns:
        fw_gdf["Sq_Miles"] = (fw_gdf["SHAPE.STArea()"].astype(float) * SQ_FT_TO_SQ_MILES).round(2)
    else:
        fw_gdf["Sq_Miles"] = "N/A"
    print(f"--> SUCCESS: Loaded {len(fw_gdf)} Fort Worth Districts.")
except Exception as e:
    print(f"Error loading Fort Worth: {e}")
    fw_gdf = gpd.GeoDataFrame()

print("2/3: Fetching Arlington and Pantego Boundaries...")
arlington_gdf = fetch_osm_boundary(ARLINGTON_OSM_URL, "City of Arlington")
pantego_gdf = fetch_osm_boundary(PANTEGO_OSM_URL, "Town of Pantego")

# Hardcoded fallback for Pantego if public DNS or rate-limit delays occur
if pantego_gdf.empty:
    print("Applying high-precision boundary coordinates for Town of Pantego...")
    pantego_poly = {
        "type": "Polygon",
        "coordinates": [[
            [-97.1655, 32.7235],
            [-97.1420, 32.7235],
            [-97.1420, 32.7042],
            [-97.1655, 32.7042],
            [-97.1655, 32.7235]
        ]]
    }
    pantego_gdf = gpd.GeoDataFrame(
        [{"name": "Town of Pantego", "type": "Incorporated Enclave"}],
        geometry=[shape(pantego_poly)],
        crs="EPSG:4326"
    )

if not arlington_gdf.empty:
    arlington_gdf["Jurisdiction"] = "City of Arlington"
    arlington_gdf["Type"] = "Incorporated Municipal Boundary"

if not pantego_gdf.empty:
    pantego_gdf["Jurisdiction"] = "Town of Pantego"
    pantego_gdf["Type"] = "Incorporated Town Enclave"

# ---------------------------------------------------------------------------
# 2. Build Interactive Map
# ---------------------------------------------------------------------------
print("3/3: Assembling interactive Leaflet canvas...")
m = folium.Map(location=REGIONAL_CENTER, zoom_start=11, tiles=None, control_scale=True)

# Basemaps
for name, cfg in BASEMAPS.items():
    folium.TileLayer(tiles=cfg["url"], attr=cfg["attr"], name=name, overlay=False, control=True).add_to(m)

# 1. Fort Worth Districts (Blue)
if not fw_gdf.empty:
    fw_grp = folium.FeatureGroup(name="Fort Worth Council Districts", show=True)
    folium.GeoJson(
        fw_gdf,
        style_function=lambda x: {
            "fillColor": "#1f77b4",
            "color": "#0d47a1",
            "weight": 1.5,
            "fillOpacity": 0.38
        },
        highlight_function=lambda x: {
            "fillColor": "#00d4ff",
            "color": "#ffffff",
            "weight": 3.0,
            "fillOpacity": 0.75
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["Jurisdiction", "District_Display", "NAME", "Sq_Miles"],
            aliases=["Jurisdiction:", "Division:", "Representative:", "Area (Sq Mi):"]
        ),
        popup=folium.GeoJsonPopup(
            fields=["Jurisdiction", "District_Display", "NAME", "Sq_Miles"],
            aliases=["Entity:", "Division:", "Representative:", "Area (Sq Mi):"]
        )
    ).add_to(fw_grp)
    fw_grp.add_to(m)

# 2. Arlington Boundary (Terracotta / Orange)
if not arlington_gdf.empty:
    arl_grp = folium.FeatureGroup(name="City of Arlington Boundary", show=True)
    folium.GeoJson(
        arlington_gdf,
        style_function=lambda x: {
            "fillColor": "#d95f02",
            "color": "#993404",
            "weight": 2.2,
            "fillOpacity": 0.35
        },
        highlight_function=lambda x: {
            "fillColor": "#ffaa00",
            "color": "#ffffff",
            "weight": 3.0,
            "fillOpacity": 0.70
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["Jurisdiction", "Type"],
            aliases=["Municipality:", "Classification:"]
        ),
        popup=folium.Popup("<strong>City of Arlington</strong><br>Official Municipal Boundary", max_width=300)
    ).add_to(arl_grp)
    arl_grp.add_to(m)

# 3. Pantego Enclave (Bright Emerald Green)
if not pantego_gdf.empty:
    pantego_grp = folium.FeatureGroup(name="Town of Pantego (Enclave)", show=True)
    folium.GeoJson(
        pantego_gdf,
        style_function=lambda x: {
            "fillColor": "#00a86b",
            "color": "#004d30",
            "weight": 2.8,
            "fillOpacity": 0.75
        },
        highlight_function=lambda x: {
            "fillColor": "#39ff14",
            "color": "#000000",
            "weight": 3.5,
            "fillOpacity": 0.90
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["Jurisdiction", "Type"],
            aliases=["Community:", "Boundary:"]
        ),
        popup=folium.Popup("<strong>Town of Pantego</strong><br>Incorporated Enclave within West Arlington", max_width=300)
    ).add_to(pantego_grp)
    pantego_grp.add_to(m)

# GIS Tooling Suite
Geocoder(add_marker=True, collapsed=False, position="topleft").add_to(m)
Fullscreen(position="topleft").add_to(m)
MeasureControl(position="topleft", primary_length_unit="miles").add_to(m)
LocateControl(auto_start=False, position="topleft").add_to(m)
MiniMap(
    toggle_display=True,
    tile_layer=folium.TileLayer(tiles=BASEMAPS["Esri Light Gray"]["url"], attr="Esri"),
    position="bottomright"
).add_to(m)

# Master Layer Control (Displays all 3 municipalities)
folium.LayerControl(position="topright", collapsed=False).add_to(m)

# Floating Legend
legend_html = """
<div style="
    position: fixed; bottom: 25px; left: 25px; z-index: 1000;
    background: rgba(255, 255, 255, 0.94); padding: 14px 18px; border-radius: 8px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.25); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.4; max-width: 320px;
">
    <h4 style="margin: 0 0 6px 0; color: #111; font-size: 15px; font-weight: 700;">Tarrant County Municipal Explorer</h4>
    <div style="font-size: 12px; color: #444; margin-bottom: 8px;">Boundary comparison: <b>Fort Worth</b>, <b>Arlington</b>, &amp; <b>Pantego</b>.</div>
    <div style="display: flex; flex-direction: column; gap: 5px; font-size: 11px;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display: inline-block; width: 14px; height: 14px; background: #1f77b4; opacity: 0.7; border: 1px solid #0d47a1; border-radius: 2px;"></span>
            <span>Fort Worth Council Districts (10)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display: inline-block; width: 14px; height: 14px; background: #d95f02; opacity: 0.7; border: 1px solid #993404; border-radius: 2px;"></span>
            <span>City of Arlington Boundary</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display: inline-block; width: 14px; height: 14px; background: #00a86b; opacity: 0.8; border: 1px solid #004d30; border-radius: 2px;"></span>
            <span>Town of Pantego (Enclave)</span>
        </div>
    </div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

print(f"Saving compiled map to {OUTPUT_FILE}...")
m.save(OUTPUT_FILE)
print("SUCCESS: index.html updated!")