#!/usr/bin/env python3
"""
Regional Tarrant County Spatial Explorer: Fort Worth, Arlington & Pantego
Uses City of Fort Worth Open Data + US Census Bureau Public Cartographic Boundary API.
No login, account, or API keys required.
"""

import sys
import requests
import geopandas as gpd
import folium
from folium.plugins import Geocoder, MiniMap, Fullscreen, MeasureControl, LocateControl

# ---------------------------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------------------------
# 1. Fort Worth Council Districts (City of Fort Worth MapServer)
FW_ENDPOINT = (
    "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/"
    "OpenData_Boundaries/MapServer/2/query?outFields=*&where=1%3D1&f=geojson"
)

# 2. US Census Bureau Cartographic Boundaries (Texas Places layer - Free & Public)
# Arlington FIPS = '04000', Pantego FIPS = '55212'
CENSUS_PLACES_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGER/Tracts_Blocks/MapServer/20/query"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Regional-GIS/1.0"}
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


def load_census_boundary(place_name: str) -> gpd.GeoDataFrame:
    """Queries US Census TIGER API for a Texas municipality."""
    print(f"Fetching {place_name} from US Census Bureau...")
    params = {
        "where": f"STATE = '48' AND UPPER(NAME) = '{place_name.upper()}'",
        "outFields": "NAME,GEOID,CENTLAT,CENTLON",
        "f": "geojson",
        "returnGeometry": "true"
    }
    try:
        r = requests.get(CENSUS_PLACES_URL, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
        if not features:
            print(f"Warning: No features returned for {place_name}")
            return gpd.GeoDataFrame()
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        print(f"--> Successfully loaded {place_name} ({len(gdf)} polygon).")
        return gdf
    except Exception as e:
        print(f"Census query failed for {place_name}: {e}")
        return gpd.GeoDataFrame()


# ---------------------------------------------------------------------------
# 1. Load Fort Worth Council Districts
# ---------------------------------------------------------------------------
print("Fetching Fort Worth Council Districts...")
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
    print(f"--> Successfully loaded {len(fw_gdf)} Fort Worth Districts.")
except Exception as e:
    print(f"Fort Worth fetch error: {e}")
    fw_gdf = gpd.GeoDataFrame()

# ---------------------------------------------------------------------------
# 2. Load Arlington & Pantego from US Census
# ---------------------------------------------------------------------------
arlington_gdf = load_census_boundary("Arlington")
if not arlington_gdf.empty:
    arlington_gdf["Jurisdiction"] = "City of Arlington"
    arlington_gdf["Type"] = "Incorporated City (US Census Boundary)"

pantego_gdf = load_census_boundary("Pantego")
if not pantego_gdf.empty:
    pantego_gdf["Jurisdiction"] = "Town of Pantego"
    pantego_gdf["Type"] = "Incorporated Town Enclave"

# ---------------------------------------------------------------------------
# 3. Build Map Canvas
# ---------------------------------------------------------------------------
print("Generating Regional Leaflet Map...")
m = folium.Map(location=REGIONAL_CENTER, zoom_start=11, tiles=None, control_scale=True)

for name, cfg in BASEMAPS.items():
    folium.TileLayer(tiles=cfg["url"], attr=cfg["attr"], name=name, overlay=False, control=True).add_to(m)

# Fort Worth Layer (Blue)
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

# Arlington Layer (Warm Orange)
if not arlington_gdf.empty:
    arl_grp = folium.FeatureGroup(name="City of Arlington Boundary", show=True)
    folium.GeoJson(
        arlington_gdf,
        style_function=lambda x: {
            "fillColor": "#d95f02",
            "color": "#993404",
            "weight": 2.0,
            "fillOpacity": 0.35
        },
        highlight_function=lambda x: {
            "fillColor": "#ffaa00",
            "color": "#ffffff",
            "weight": 3.0,
            "fillOpacity": 0.70
        },
        tooltip=folium.GeoJsonTooltip(fields=["NAME", "Type"], aliases=["Municipality:", "Classification:"]),
        popup=folium.Popup("<strong>City of Arlington</strong><br>Official Municipal Boundary", max_width=300)
    ).add_to(arl_grp)
    arl_grp.add_to(m)

# Pantego Layer (Emerald Green)
if not pantego_gdf.empty:
    pantego_grp = folium.FeatureGroup(name="Town of Pantego (Enclave)", show=True)
    folium.GeoJson(
        pantego_gdf,
        style_function=lambda x: {
            "fillColor": "#00a86b",
            "color": "#004d30",
            "weight": 2.5,
            "fillOpacity": 0.70
        },
        highlight_function=lambda x: {
            "fillColor": "#39ff14",
            "color": "#000000",
            "weight": 3.5,
            "fillOpacity": 0.90
        },
        tooltip=folium.GeoJsonTooltip(fields=["NAME", "Type"], aliases=["Municipality:", "Boundary Status:"]),
        popup=folium.Popup("<strong>Town of Pantego</strong><br>Incorporated Town (Enclave within Arlington)", max_width=300)
    ).add_to(pantego_grp)
    pantego_grp.add_to(m)

# GIS Tools
Geocoder(add_marker=True, collapsed=False, position="topleft").add_to(m)
Fullscreen(position="topleft").add_to(m)
MeasureControl(position="topleft", primary_length_unit="miles").add_to(m)
LocateControl(auto_start=False, position="topleft").add_to(m)
MiniMap(
    toggle_display=True,
    tile_layer=folium.TileLayer(tiles=BASEMAPS["Esri Light Gray"]["url"], attr="Esri"),
    position="bottomright"
).add_to(m)
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
print("Complete! Open index.html to view.")