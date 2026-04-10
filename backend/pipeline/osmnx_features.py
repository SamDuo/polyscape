"""OSMnx-based network features for H3 hexes.

Computes walk score (amenity count within 800m network distance),
transit proximity (distance to nearest MARTA stop), and road density
(km of road per hex area) for each H3 hex cell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import Point

# Network distance threshold for walk score (meters)
WALK_DISTANCE_M: int = 800

# Amenity tags to count for walk score
WALK_AMENITY_TAGS: dict[str, list[str]] = {
    "amenity": [
        "restaurant",
        "cafe",
        "pharmacy",
        "bank",
        "school",
        "library",
        "hospital",
        "clinic",
        "supermarket",
        "marketplace",
        "post_office",
        "community_centre",
    ],
    "shop": ["supermarket", "convenience", "bakery", "grocery"],
}

# MARTA transit stop tags
TRANSIT_TAGS: dict[str, str | list[str]] = {
    "public_transport": "stop_position",
    "railway": ["station", "halt"],
    "highway": "bus_stop",
}


def compute_walk_score(
    hex_gdf: gpd.GeoDataFrame,
    distance_m: int = WALK_DISTANCE_M,
) -> pd.DataFrame:
    """Count amenities within network walking distance of each hex centroid.

    Parameters
    ----------
    hex_gdf : gpd.GeoDataFrame
        H3 hex grid with h3_index, lat, lng columns.
    distance_m : int
        Network distance threshold in meters.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, walk_score (amenity count).
    """
    records: list[dict] = []

    for _, row in hex_gdf.iterrows():
        h3_idx = row["h3_index"]
        lat, lng = row["lat"], row["lng"]
        try:
            amenities = ox.features_from_point(
                (lat, lng),
                tags={"amenity": True, "shop": True},
                dist=distance_m,
            )
            score = len(amenities)
        except Exception:
            score = 0

        records.append({"h3_index": h3_idx, "walk_score": score})

    result = pd.DataFrame(records)
    print(f"Computed walk scores for {len(result)} hexes")
    return result


def compute_transit_proximity(
    hex_gdf: gpd.GeoDataFrame,
    search_radius_m: int = 2000,
) -> pd.DataFrame:
    """Compute distance from each hex centroid to nearest transit stop.

    Parameters
    ----------
    hex_gdf : gpd.GeoDataFrame
        H3 hex grid with h3_index, lat, lng columns.
    search_radius_m : int
        Search radius in meters for finding transit stops.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, transit_proximity (meters to nearest stop).
    """
    # Download all MARTA stops within the hex grid extent
    bounds = hex_gdf.total_bounds  # [minx, miny, maxx, maxy]
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lng = (bounds[0] + bounds[2]) / 2

    try:
        # Fetch transit stops for the whole metro area
        transit_stops = ox.features_from_bbox(
            bbox=(bounds[3], bounds[1], bounds[2], bounds[0]),  # north, south, east, west
            tags=TRANSIT_TAGS,
        )
        # Get point geometries (centroids for non-point features)
        stop_points = transit_stops.geometry.centroid
        stop_gdf = gpd.GeoDataFrame(
            geometry=stop_points, crs="EPSG:4326"
        ).to_crs("EPSG:32616")
    except Exception as exc:
        print(f"Warning: could not fetch transit stops: {exc}")
        # Return NaN for all hexes
        return pd.DataFrame(
            {
                "h3_index": hex_gdf["h3_index"],
                "transit_proximity": np.nan,
            }
        )

    # Project hex centroids to UTM
    hex_points = gpd.GeoDataFrame(
        {"h3_index": hex_gdf["h3_index"]},
        geometry=[Point(lng, lat) for lng, lat in zip(hex_gdf["lng"], hex_gdf["lat"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32616")

    records: list[dict] = []
    for _, row in hex_points.iterrows():
        distances = stop_gdf.geometry.distance(row.geometry)
        min_dist = distances.min() if len(distances) > 0 else np.nan
        records.append(
            {"h3_index": row["h3_index"], "transit_proximity": min_dist}
        )

    result = pd.DataFrame(records)
    print(f"Computed transit proximity for {len(result)} hexes")
    return result


def compute_road_density(hex_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute road density (km of road per km^2) for each hex.

    Parameters
    ----------
    hex_gdf : gpd.GeoDataFrame
        H3 hex grid with h3_index, lat, lng, geometry columns.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, road_density (km road / km^2 hex area).
    """
    # Project hex grid to UTM for area/length calculations
    hex_proj = hex_gdf.to_crs("EPSG:32616")

    records: list[dict] = []
    for _, row in hex_gdf.iterrows():
        h3_idx = row["h3_index"]
        lat, lng = row["lat"], row["lng"]
        try:
            graph = ox.graph_from_point(
                (lat, lng),
                dist=500,
                network_type="drive",
            )
            edges = ox.graph_to_gdfs(graph, nodes=False)
            total_length_m = edges["length"].sum() if "length" in edges.columns else 0.0
            total_length_km = total_length_m / 1000.0
        except Exception:
            total_length_km = 0.0

        # Hex area in km^2
        hex_row_proj = hex_proj[hex_proj["h3_index"] == h3_idx]
        if len(hex_row_proj) > 0:
            hex_area_km2 = hex_row_proj.geometry.area.values[0] / 1e6
        else:
            hex_area_km2 = 1.0  # fallback to avoid division by zero

        density = total_length_km / hex_area_km2 if hex_area_km2 > 0 else 0.0
        records.append({"h3_index": h3_idx, "road_density": density})

    result = pd.DataFrame(records)
    print(f"Computed road density for {len(result)} hexes")
    return result


if __name__ == "__main__":
    from backend.pipeline.hex_grid import generate_hex_grid

    grid = generate_hex_grid(resolution=7)  # Use res 7 for faster testing
    sample = grid.head(10)  # Small sample for testing

    walk = compute_walk_score(sample)
    print(f"Walk scores:\n{walk}")

    transit = compute_transit_proximity(sample)
    print(f"Transit proximity:\n{transit}")

    roads = compute_road_density(sample)
    print(f"Road density:\n{roads}")
