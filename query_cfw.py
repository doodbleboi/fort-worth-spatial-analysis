#!/usr/bin/env python3
"""
Fort Worth Council Districts Spatial Analysis & Interactive Map Generator
Includes live address searching (Geocoder) and an overview MiniMap.
"""

import sys
import requests
import geopandas as gpd
import folium
from folium.plugins import Geocoder, MiniMap

# ---------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------
ENDPOINT = (
    "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/"
    "OpenData_Boundaries/MapServer/2/query"
)

PARAMS = {
    "where": "1=1",
    "outFields": "OBJECTID,NAME,DISTRICT,DATESTAMP,SHAPE.STArea()",
    "f": "geojson",
    "returnGeometry": "true",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

OUTPUT_FILE = "index.html"
FT_WORTH_COORDS = [32.7555, -97.3308]
SQ_FT_TO_SQ_MILES = 1 / 27878400

# Distinct color palette for council districts
PALETTE = [
    "#2b5c8f", "#d95f02", "#7570b3", "#e7298a",
    "#66a61e", "#e6ab02", "#a6761d", "#1b9e77",
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3"
]


def fetch_spatial_data(url: str, params: dict) -> gpd.GeoDataFrame:
    """Queries the ArcGIS MapServer endpoint and parses into a GeoDataFrame."""
    print(f"[1/4] Fetching data from {url.split('?')[0]}...")
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        print(f"Error querying endpoint: {err}", file=sys.stderr)
        sys.exit(1)

    payload = response.json()
    if "error" in payload:
        error_msg = payload["error"].get("message", payload["error"])
        print(f"ArcGIS REST Error: {error_msg}", file=sys.stderr)
        sys.exit(1)

    features = payload.get("features", [])
    if not features:
        print("Warning: No features returned from endpoint.", file=sys.stderr)
        return gpd.GeoDataFrame()

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def clean_and_enrich_data(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cleans columns, calculates area in sq miles, and assigns display styling."""
    print(f"[2/4] Processing {len(gdf)} district polygons...")
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()

    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    if "DISTRICT" in gdf.columns:
        gdf["display_district"] = gdf["DISTRICT"].astype(str).str.replace(".0", "", regex=False)
    else:
        gdf["display_district"] = gdf.index.astype(str)

    area_col = "SHAPE.STArea()"
    if area_col in gdf.columns:
        gdf["area_sq_mi"] = (gdf[area_col].astype(float) * SQ_FT_TO_SQ_MILES).round(2)
    else:
        gdf["area_sq_mi"] = "N/A"

    gdf["fill_color"] = [PALETTE[i % len(PALETTE)] for i in range(len(gdf))]
    return gdf


def build_map(gdf: gpd.GeoDataFrame, output_path: str):
    """Renders the spatial layer into an interactive Folium web map with search and minimap."""
    print("[3/4] Rendering interactive Leaflet/Folium map...")

    m = folium.Map(
        location=FT_WORTH_COORDS,
        zoom_start=11,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # 1. District Boundaries Layer
    folium.GeoJson(
        gdf,
        name="City Council Districts",
        style_function=lambda feature: {
            "fillColor": feature["properties"]["fill_color"],
            "color": "#1a1a1a",
            "weight": 1.5,
            "fillOpacity": 0.45,
        },
        highlight_function=lambda feature: {
            "fillColor": "#ffff00",
            "color": "#000000",
            "weight": 3,
            "fillOpacity": 0.7,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["display_district", "NAME", "area_sq_mi"],
            aliases=["Council District:", "Name:", "Approx. Sq Miles:"],
            style=(
                "background-color: white; color: #333333; font-family: sans-serif; "
                "font-size: 12px; padding: 8px; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);"
            ),
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(
            fields=["display_district", "NAME", "area_sq_mi", "DATESTAMP"],
            aliases=["District:", "Council Member / Title:", "Area (sq mi):", "Last Updated:"],
            localize=True,
        ),
    ).add_to(m)

    # 2. Live Search / Geocoder Plugin (Top-left search bar)
    Geocoder(add_marker=True, collapsed=False).add_to(m)

    # 3. Overview Corner MiniMap Plugin (Bottom-right inset map)
    MiniMap(toggle_display=True, tile_layer="OpenStreetMap").add_to(m)

    folium.LayerControl(position="topright").add_to(m)

    print(f"[4/4] Saving output to {output_path}...")
    m.save(output_path)
    print(f"Map successfully generated: {output_path}")


def main():
    gdf = fetch_spatial_data(ENDPOINT, PARAMS)
    if gdf.empty:
        print("Execution aborted: no spatial records available.", file=sys.stderr)
        sys.exit(1)

    enriched_gdf = clean_and_enrich_data(gdf)
    build_map(enriched_gdf, OUTPUT_FILE)


if __name__ == "__main__":
    main()
