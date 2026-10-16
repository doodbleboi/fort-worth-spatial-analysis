#!/usr/bin/env python3
"""
Regional Tarrant County Spatial Explorer: Fort Worth, Arlington & Pantego
Multi-source geospatial ETL pipeline powered by Fort Worth GIS & NCTCOG Regional Open Data.
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
# 1. Fort Worth Official Council Districts (MapServer)
FW_ENDPOINT = (
    "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/"
    "OpenData_Boundaries/MapServer/2/query"
)

# 2. NCTCOG Regional Municipal Boundaries (Authoritative source for Arlington & Pantego)
NCTCOG_MUNIS_ENDPOINT = (
    "https://services.arcgis.com/rOo16HdIMDhWgIKI/arcgis/rest/services/"
    "City_Limits/FeatureServer/0/query"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Regional-GIS-Explorer/3.0 (Tarrant County Spatial Analytics)"
    )
}

OUTPUT_FILE = "index.html"
REGIONAL_CENTER = [32.7357, -97.2000]  # Balanced centroid of Fort Worth, Arlington, and Pantego

# Area conversion constants (from sq ft)
SQ_FT_TO_SQ_MILES = 1 / 27878400
SQ_FT_TO_ACRES = 1 / 43560

# Free, high-performance Esri Basemaps (No API keys required, no localhost/file:// blocks)
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
    """Queries an ArcGIS REST endpoint and constructs a normalized WGS84 GeoDataFrame."""
    print(f"Fetching {label}...")
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()

        if "error" in payload:
            print(f"Notice for {label}: {payload['error'].get('message', payload['error'])}", file=sys.stderr)
            return gpd.GeoDataFrame()

        features = payload.get("features", [])
        if not features:
            print(f"Warning: No spatial features found for {label}.", file=sys.stderr)
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        print(f"--> Successfully loaded {len(gdf)} feature(s) for {label}.")
        return gdf

    except Exception as err:
        print(f"Error fetching {label}: {err}", file=sys.stderr)
        return gpd.GeoDataFrame()


def build_regional_map():
    # -----------------------------------------------------------------------
    # 1. Fetch & Enrich Datasets
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

    # B. City of Arlington Boundary (via NCTCOG Regional Layer)
    arlington_gdf = query_arcgis_endpoint(
        NCTCOG_MUNIS_ENDPOINT,
        params={
            "where": "UPPER(CITY_NAME) = 'ARLINGTON' OR UPPER(NAME) = 'ARLINGTON'",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="City of Arlington Boundary"
    )

    if not arlington_gdf.empty:
        arlington_gdf["Jurisdiction"] = "City of Arlington"
        arlington_gdf["Type"] = "Incorporated Municipal Boundary"

    # C. Town of Pantego Enclave (via NCTCOG Regional Layer)
    pantego_gdf = query_arcgis_endpoint(
        NCTCOG_MUNIS_ENDPOINT,
        params={
            "where": "UPPER(CITY_NAME) = 'PANTEGO' OR UPPER(NAME) = 'PANTEGO'",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="Town of Pantego Enclave"
    )

    if not pantego_gdf.empty:
        pantego_gdf["Jurisdiction"] = "Town of Pantego"
        pantego_gdf["Type"] = "Incorporated Town (Enclave in Arlington)"

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
    # Layer 1: Fort Worth Council Districts (Sapphire Blue)
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

    # Layer 2: Arlington Boundary (Warm Terracotta / Coral)
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

    # Layer 3: Town of Pantego Enclave (Emerald Green)
    if not pantego_gdf.empty:
        pantego_group = folium.FeatureGroup(name="Town of Pantego (Enclave)", show=True)
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
            tooltip=folium.GeoJsonTooltip(
                fields=["Jurisdiction", "Type"],
                aliases=["Community:", "Boundary Status:"],
                style=(
                    "background: rgba(255, 255, 255, 0.95); font-family: -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, sans-serif; font-size: 12px; padding: 10px; border-radius: 6px; "
                    "box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
                ),
                sticky=True
            ),
            popup=folium.Popup(
                "<strong>Town of Pantego</strong><br>Incorporated Town (Enclave within Arlington).<br>Governed by an at-large Town Council.",
                max_width=300
            )
        ).add_to(pantego_group)
        pantego_group.add_to(m)

    # -----------------------------------------------------------------------
    # 4. Interactive GIS Tools
    # -----------------------------------------------------------------------
    # Address Search / Geocoder
    Geocoder(add_marker=True, collapsed=False, position="topleft").add_to(m)

    # Fullscreen Button
    Fullscreen(position="topleft", title="Full Screen", title_cancel="Exit Full Screen").add_to(m)

    # Distance and Area Measurement Ruler
    MeasureControl(
        position="topleft",
        primary_length_unit="miles",
        secondary_length_unit="feet",
        primary_area_unit="sqmiles",
        secondary_area_unit="acres"
    ).add_to(m)

    # GPS Geolocation / "Locate Me" Button
    LocateControl(auto_start=False, position="topleft").add_to(m)

    # Corner Overview MiniMap
    MiniMap(
        toggle_display=True,
        tile_layer=folium.TileLayer(
            tiles=BASEMAPS["Esri Light Gray"]["url"],
            attr=BASEMAPS["Esri Light Gray"]["attr"]
        ),
        position="bottomright"
    ).add_to(m)

    # Layer Toggle Menu (Top Right)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    # -----------------------------------------------------------------------
    # 5. Floating Title & Legend HUD
    # -----------------------------------------------------------------------
    title_html = """
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.94);
        padding: 14px 18px;
        border-radius: 8px;
        box-shadow: 0 4px 18px rgba(0,0,0,0.25);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.4;
        max-width: 330px;
        backdrop-filter: blur(4px);
    ">
        <h4 style="margin: 0 0 6px 0; color: #111; font-size: 15px; font-weight: 700;">
            Tarrant County Municipal Explorer
        </h4>
        <div style="font-size: 12px; color: #444; margin-bottom: 8px;">
            Boundary comparison: <b>Fort Worth</b>, <b>Arlington</b>, &amp; <b>Pantego</b>.
        </div>
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
    m.get_root().html.add_child(folium.Element(title_html))

    print(f"Exporting compiled web map to {OUTPUT_FILE}...")
    m.save(OUTPUT_FILE)
    print("Execution complete! Open index.html to view the updated map.")


if __name__ == "__main__":
    build_regional_map()