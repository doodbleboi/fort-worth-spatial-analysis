#!/usr/bin/env python3
"""
Regional Tarrant County Spatial Explorer: Fort Worth, Arlington & Town of Pantego
Production-grade spatial aggregation, analytical enrichment, and multi-layer web visualization.
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

ARLINGTON_ENDPOINT = (
    "https://gis.arlingtontx.gov/arcgis/rest/services/OpenData/"
    "OpenData/FeatureServer/0/query"
)

TARRANT_MUNIS_ENDPOINT = (
    "https://gisweb.tarrantcounty.com/arcgis/rest/services/Boundaries/"
    "City_Limits/FeatureServer/0/query"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Regional-GIS-Expert/2.0 (Spatial Analytics Pipeline)"
    )
}

OUTPUT_FILE = "index.html"
REGIONAL_CENTER = [32.7357, -97.2000]  # Balanced centroid of FW / Arlington / Pantego

# Area conversion constants (from sq ft)
SQ_FT_TO_SQ_MILES = 1 / 27878400
SQ_FT_TO_ACRES = 1 / 43560

# Reliable open-access basemaps (Zero API key required, zero file:// watermark)
BASEMAPS = {
    "Esri Light Gray": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
    },
    "Esri Streets": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Sources: Esri, DeLorme, USGS, NPS"
    },
    "Esri World Imagery (Satellite)": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
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
            print(f"Server warning for {label}: {payload['error'].get('message', payload['error'])}", file=sys.stderr)
            return gpd.GeoDataFrame()

        features = payload.get("features", [])
        if not features:
            print(f"Warning: No features returned for {label}.", file=sys.stderr)
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        print(f"Successfully processed {len(gdf)} features for {label}.")
        return gdf

    except Exception as err:
        print(f"Notice: Failed to fetch {label} ({err}). Skipping layer gracefully.", file=sys.stderr)
        return gpd.GeoDataFrame()


def build_regional_map():
    # -----------------------------------------------------------------------
    # 1. Fetch & Enrich Layers
    # -----------------------------------------------------------------------
    # A. Fort Worth
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

    # B. Arlington
    arlington_gdf = query_arcgis_endpoint(
        ARLINGTON_ENDPOINT,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="Arlington Council Districts"
    )

    if not arlington_gdf.empty:
        arlington_gdf["Jurisdiction"] = "City of Arlington"
        dist_col = next((c for c in ["DISTRICT", "COUNCIL_DISTRICT", "DIST_NUM", "NAME"] if c in arlington_gdf.columns), None)
        arlington_gdf["District_Display"] = (
            "District " + arlington_gdf[dist_col].astype(str) if dist_col else "Council District"
        )

    # C. Pantego
    pantego_gdf = query_arcgis_endpoint(
        TARRANT_MUNIS_ENDPOINT,
        params={
            "where": "UPPER(NAME) LIKE '%PANTEGO%' OR UPPER(CITY) LIKE '%PANTEGO%'",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true"
        },
        label="Town of Pantego Enclave"
    )

    if not pantego_gdf.empty:
        pantego_gdf["Jurisdiction"] = "Town of Pantego"
        pantego_gdf["Type"] = "Incorporated Town (Tarrant County)"

    # -----------------------------------------------------------------------
    # 2. Map Initialization & Multiple Basemaps
    # -----------------------------------------------------------------------
    print("Assembling multi-layer canvas...")
    m = folium.Map(
        location=REGIONAL_CENTER,
        zoom_start=11,
        tiles=None,
        control_scale=True
    )

    # Add selectable basemaps
    for name, config in BASEMAPS.items():
        folium.TileLayer(
            tiles=config["url"],
            attr=config["attr"],
            name=name,
            overlay=False,
            control=True
        ).add_to(m)

    # -----------------------------------------------------------------------
    # 3. Layer Vector Overlays
    # -----------------------------------------------------------------------
    # Layer 1: Fort Worth (Slate Sapphire)
    if not fw_gdf.empty:
        fw_group = folium.FeatureGroup(name="Fort Worth Council Districts", show=True)
        folium.GeoJson(
            fw_gdf,
            style_function=lambda x: {
                "fillColor": "#1f77b4",
                "color": "#0d47a1",
                "weight": 1.5,
                "fillOpacity": 0.40
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
                    "background: rgba(255, 255, 255, 0.96); font-family: -apple-system, BlinkMacSystemFont, "
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

    # Layer 2: Arlington (Warm Ochre / Coral)
    if not arlington_gdf.empty:
        arl_group = folium.FeatureGroup(name="Arlington Council Districts", show=True)
        folium.GeoJson(
            arlington_gdf,
            style_function=lambda x: {
                "fillColor": "#d95f02",
                "color": "#a63603",
                "weight": 1.5,
                "fillOpacity": 0.45
            },
            highlight_function=lambda x: {
                "fillColor": "#ffaa00",
                "color": "#ffffff",
                "weight": 3.0,
                "fillOpacity": 0.75
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["Jurisdiction", "District_Display"],
                aliases=["Jurisdiction:", "Council Zone:"],
                style=(
                    "background: rgba(255, 255, 255, 0.96); font-family: -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, sans-serif; font-size: 12px; padding: 10px; border-radius: 6px; "
                    "box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
                ),
                sticky=True
            )
        ).add_to(arl_group)
        arl_group.add_to(m)

    # Layer 3: Pantego (High-Contrast Emerald Enclave)
    if not pantego_gdf.empty:
        pantego_group = folium.FeatureGroup(name="Town of Pantego", show=True)
        folium.GeoJson(
            pantego_gdf,
            style_function=lambda x: {
                "fillColor": "#00a86b",
                "color": "#004d30",
                "weight": 2.5,
                "fillOpacity": 0.65
            },
            highlight_function=lambda x: {
                "fillColor": "#39ff14",
                "color": "#000000",
                "weight": 3.5,
                "fillOpacity": 0.85
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["Jurisdiction", "Type"],
                aliases=["Community:", "Status:"],
                style=(
                    "background: rgba(255, 255, 255, 0.96); font-family: -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, sans-serif; font-size: 12px; padding: 10px; border-radius: 6px; "
                    "box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
                ),
                sticky=True
            ),
            popup=folium.Popup(
                "<strong>Town of Pantego</strong><br>Incorporated Town surrounded by Arlington.<br>Governed by an at-large Town Council.",
                max_width=300
            )
        ).add_to(pantego_group)
        pantego_group.add_to(m)

    # -----------------------------------------------------------------------
    # 4. Expert GIS Tooling & Add-ons
    # -----------------------------------------------------------------------
    # Address Search (Geocoder)
    Geocoder(add_marker=True, collapsed=False, position="topleft").add_to(m)

    # Fullscreen Toggle Button
    Fullscreen(position="topleft", title="Full Screen", title_cancel="Exit Full Screen").add_to(m)

    # Spatial Measuring Ruler Tool (Area & Distance)
    MeasureControl(
        position="topleft",
        primary_length_unit="miles",
        secondary_length_unit="feet",
        primary_area_unit="sqmiles",
        secondary_area_unit="acres"
    ).add_to(m)

    # Geolocation / "Find Me" Control
    LocateControl(auto_start=False, position="topleft").add_to(m)

    # Corner Navigation MiniMap
    MiniMap(
        toggle_display=True,
        tile_layer=folium.TileLayer(
            tiles=BASEMAPS["Esri Light Gray"]["url"],
            attr=BASEMAPS["Esri Light Gray"]["attr"]
        ),
        position="bottomright"
    ).add_to(m)

    # Master Layer Control (Top Right)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    # -----------------------------------------------------------------------
    # 5. Floating UI Banner / Title Legend Card
    # -----------------------------------------------------------------------
    title_html = """
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.92);
        padding: 14px 18px;
        border-radius: 8px;
        box-shadow: 0 4px 18px rgba(0,0,0,0.25);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.4;
        max-width: 320px;
        backdrop-filter: blur(4px);
    ">
        <h4 style="margin: 0 0 6px 0; color: #111; font-size: 15px; font-weight: 700;">
            North Texas Municipal Explorer
        </h4>
        <div style="font-size: 12px; color: #444; margin-bottom: 8px;">
            Comparative boundary coverage: <b>Fort Worth</b>, <b>Arlington</b>, &amp; <b>Pantego</b>.
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px; font-size: 11px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 14px; height: 14px; background: #1f77b4; opacity: 0.7; border: 1px solid #0d47a1; border-radius: 2px;"></span>
                <span>Fort Worth Council Districts</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 14px; height: 14px; background: #d95f02; opacity: 0.7; border: 1px solid #a63603; border-radius: 2px;"></span>
                <span>Arlington Council Districts</span>
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
    print("Process complete! Open index.html to explore.")


if __name__ == "__main__":
    build_regional_map()