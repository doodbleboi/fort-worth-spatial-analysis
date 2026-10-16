#!/usr/bin/env python3
"""
Regional Tarrant County Spatial Explorer: Fort Worth, Arlington & Pantego
Multi-source geospatial ETL pipeline with client-side attribute filtering.
"""

import sys
import requests
import geopandas as gpd
import folium
from folium.plugins import (
    Geocoder,
    MiniMap,
    Fullscreen,
    MeasureControl,
    LocateControl
)

# ---------------------------------------------------------------------------
# Endpoints & Configurations
# ---------------------------------------------------------------------------
FW_ENDPOINT = (
    "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/"
    "OpenData_Boundaries/MapServer/2/query"
)

# NCTCOG Regional Municipal Boundaries (Authoritative source for North Texas cities)
NCTCOG_MUNIS_ENDPOINT = (
    "https://services.arcgis.com/rOo16HdIMDhWgIKI/arcgis/rest/services/"
    "City_Limits/FeatureServer/0/query"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Regional-GIS-Explorer/4.0 (Tarrant County Analytics)"
    )
}

OUTPUT_FILE = "index.html"
REGIONAL_CENTER = [32.7357, -97.2000]

SQ_FT_TO_SQ_MILES = 1 / 27878400
SQ_FT_TO_ACRES = 1 / 43560

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


def query_arcgis_endpoint(url: str, params: dict, label: str) -> gpd.GeoDataFrame:
    """Queries an ArcGIS REST endpoint and returns a GeoDataFrame."""
    print(f"Fetching {label}...")
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()

        if "error" in payload:
            print(f"Server error for {label}: {payload['error'].get('message', payload['error'])}", file=sys.stderr)
            return gpd.GeoDataFrame()

        features = payload.get("features", [])
        if not features:
            print(f"Notice: No features returned for {label}.", file=sys.stderr)
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        print(f"--> Successfully loaded {len(gdf)} feature(s) for {label}.")
        return gdf

    except Exception as err:
        print(f"Notice: Query failed for {label} ({err}).", file=sys.stderr)
        return gpd.GeoDataFrame()


def filter_city_polygon(gdf: gpd.GeoDataFrame, city_name: str) -> gpd.GeoDataFrame:
    """Safely finds and filters a municipality across any text attribute column."""
    if gdf.empty:
        return gpd.GeoDataFrame()
    
    target = city_name.strip().upper()
    
    # Check every string column for the target municipality name
    mask = False
    for col in gdf.columns:
        if col == "geometry":
            continue
        try:
            col_match = gdf[col].astype(str).str.strip().str.upper() == target
            mask = mask | col_match
        except Exception:
            continue
            
    matched = gdf[mask].copy()
    return matched


def build_regional_map():
    # -----------------------------------------------------------------------
    # 1. Fetch Datasets
    # -----------------------------------------------------------------------
    # A. Fort Worth Council Districts
    fw_gdf = query_arcgis_endpoint(
        FW_ENDPOINT,
        params={
            "where": "1=1",
            "outFields": "OBJECTID,NAME,DISTRICT,SHAPE.STArea()",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="Fort Worth Council Districts"
    )

    if not fw_gdf.empty:
        fw_gdf["Jurisdiction"] = "City of Fort Worth"
        fw_gdf["District_Display"] = "District " + fw_gdf["DISTRICT"].astype(str).str.replace(".0", "", regex=False)
        if "SHAPE.STArea()" in fw_gdf.columns:
            fw_gdf["Sq_Miles"] = (fw_gdf["SHAPE.STArea()"].astype(float) * SQ_FT_TO_SQ_MILES).round(2)
            fw_gdf["Acres"] = (fw_gdf["SHAPE.STArea()"].astype(float) * SQ_FT_TO_ACRES).round(1)
        else:
            fw_gdf["Sq_Miles"] = "N/A"
            fw_gdf["Acres"] = "N/A"

    # B. Regional Municipal Layer (Fetch without complex WHERE clauses)
    regional_munis = query_arcgis_endpoint(
        NCTCOG_MUNIS_ENDPOINT,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="NCTCOG Regional Boundaries"
    )

    # Client-side filtering across attributes
    arlington_gdf = filter_city_polygon(regional_munis, "Arlington")
    if not arlington_gdf.empty:
        arlington_gdf["Jurisdiction"] = "City of Arlington"
        arlington_gdf["Type"] = "Incorporated Municipal Boundary"
        print(f"--> Extracted Arlington municipal boundary ({len(arlington_gdf)} polygon).")

    pantego_gdf = filter_city_polygon(regional_munis, "Pantego")
    if not pantego_gdf.empty:
        pantego_gdf["Jurisdiction"] = "Town of Pantego"
        pantego_gdf["Type"] = "Incorporated Town (Enclave in Arlington)"
        print(f"--> Extracted Pantego municipal boundary ({len(pantego_gdf)} polygon).")

    # -----------------------------------------------------------------------
    # 2. Map Canvas Setup & Basemaps
    # -----------------------------------------------------------------------
    print("Assembling multi-layer regional GIS canvas...")
    m = folium.Map(
        location=REGIONAL_CENTER,
        zoom_start=11,
        tiles=None,
        control_scale=True
    )

    for name, config in BASEMAPS.items():
        folium.TileLayer(
            tiles=config["url"],
            attr=config["attr"],
            name=name,
            overlay=False,
            control=True
        ).add_to(m)

    # -----------------------------------------------------------------------
    # 3. Vector Layers
    # -----------------------------------------------------------------------
    # Layer 1: Fort Worth Council Districts
    if not fw_gdf.empty:
        fw_group = folium.FeatureGroup(name="Fort Worth Council Districts", show=True)
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
                aliases=["Jurisdiction:", "Division:", "Representative:", "Area (Sq Mi):"],
                style=(
                    "background: rgba(255, 255, 255, 0.95); font-family: -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, sans-serif; font-size: 12px; padding: 10px; border-radius: 6px; "
                    "box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
                ),
                sticky=True
            ),
            popup=folium.GeoJsonPopup(
                fields=["Jurisdiction", "District_Display", "NAME", "Sq_Miles", "Acres"],
                aliases=["Entity:", "Jurisdiction Level:", "Representative:", "Total Area (Sq Mi):", "Total Area (Acres):"]
            )
        ).add_to(fw_group)
        fw_group.add_to(m)

    # Layer 2: Arlington Boundary
    if not arlington_gdf.empty:
        arl_group = folium.FeatureGroup(name="City of Arlington Boundary", show=True)
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
            tooltip=folium.GeoJsonTooltip(
                fields=["Jurisdiction", "Type"],
                aliases=["Municipality:", "Classification:"],
                style=(
                    "background: rgba(255, 255, 255, 0.95); font-family: -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, sans-serif; font-size: 12px; padding: 10px; border-radius: 6px; "
                    "box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
                ),
                sticky=True
            ),
            popup=folium.Popup(
                "<strong>City of Arlington</strong><br>Municipal Boundary (Tarrant County)",
                max_width=300
            )
        ).add_to(arl_group)
        arl_group.add_to(m)

    # Layer 3: Town of Pantego Enclave