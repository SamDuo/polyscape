"""OSMnx-based network features for H3 hexes.

Computes walk score (amenity count within 800m buffer), transit proximity
(distance to nearest MARTA stop), and road density (km of road per hex area)
for each H3 hex cell.

Uses BULK downloads (one API call per feature type for the entire bbox)
followed by in-memory spatial joins — orders of magnitude faster than
per-hex queries.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point

# Buffer radius for walk score (meters, in projected CRS)
WALK_BUFFER_M: int = 800

# MARTA transit stop tags
TRANSIT_TAGS: dict[str, str | list[str]] = {
    "public_transport": "stop_position",
    "railway": ["station", "halt"],
    "highway": "bus_stop",
}


def _tile_bbox(
    hex_gdf: gpd.GeoDataFrame,
    step_deg: float = 0.15,
) -> list[tuple[float, float, float, float]]:
    """Split hex grid extent into manageable Overpass tiles (N, S, E, W)."""
    bounds = hex_gdf.total_bounds  # [minx, miny, maxx, maxy]
    west, south, east, north = bounds[0], bounds[1], bounds[2], bounds[3]
    tiles = []
    lat = south
    while lat < north:
        lng = west
        while lng < east:
            t_north = min(lat + step_deg, north)
            t_east = min(lng + step_deg, east)
            tiles.append((t_north, lat, t_east, lng))  # N, S, E, W
            lng += step_deg
        lat += step_deg
    return tiles


def _fetch_features_tiled(
    hex_gdf: gpd.GeoDataFrame,
    tags: dict,
    label: str,
    step_deg: float = 0.15,
) -> gpd.GeoDataFrame:
    """Download OSM features across tiled bboxes, dedup, return one GDF."""
    tiles = _tile_bbox(hex_gdf, step_deg)
    print(f"Downloading {label} across {len(tiles)} tiles...")

    frames = []
    for i, bbox in enumerate(tiles):
        try:
            gdf = ox.features_from_bbox(bbox=bbox, tags=tags)
            if len(gdf) > 0:
                frames.append(gdf)
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(tiles)} tiles done")

    if not frames:
        print(f"  Warning: no {label} found in any tile")
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")

    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    # Dedup on geometry centroid (tiles overlap at edges)
    merged["_cx"] = merged.geometry.centroid.x.round(6)
    merged["_cy"] = merged.geometry.centroid.y.round(6)
    merged = merged.drop_duplicates(subset=["_cx", "_cy"]).drop(columns=["_cx", "_cy"])
    merged = merged.set_crs("EPSG:4326", allow_override=True)
    print(f"  Total {label}: {len(merged)} features (deduped)")
    return merged


def compute_walk_score(hex_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Count amenities within 800m Euclidean buffer of each hex centroid.

    Downloads amenities/shops via tiled Overpass queries, then uses
    a spatial join to count per hex.
    """
    amenities = _fetch_features_tiled(
        hex_gdf, tags={"amenity": True, "shop": True}, label="amenities"
    )

    if amenities.empty:
        return pd.DataFrame({"h3_index": hex_gdf["h3_index"], "walk_score": 0})

    amenity_points = amenities.copy()
    amenity_points["geometry"] = amenity_points.geometry.centroid
    amenity_gdf = gpd.GeoDataFrame(
        amenity_points[["geometry"]], crs="EPSG:4326"
    ).to_crs("EPSG:32616")

    hex_points = gpd.GeoDataFrame(
        {"h3_index": hex_gdf["h3_index"].values},
        geometry=[Point(lng, lat) for lng, lat in zip(hex_gdf["lng"], hex_gdf["lat"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32616")

    hex_points["buffer"] = hex_points.geometry.buffer(WALK_BUFFER_M)
    hex_buffers = hex_points.set_geometry("buffer")

    joined = gpd.sjoin(
        amenity_gdf,
        hex_buffers[["h3_index", "buffer"]].set_geometry("buffer"),
        predicate="within",
    )
    counts = joined.groupby("h3_index").size().rename("walk_score").reset_index()

    result = hex_gdf[["h3_index"]].merge(counts, on="h3_index", how="left")
    result["walk_score"] = result["walk_score"].fillna(0).astype(int)

    print(f"Walk score: {len(result)} hexes (mean={result['walk_score'].mean():.1f})")
    return result[["h3_index", "walk_score"]]


def compute_transit_proximity(hex_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute distance from each hex centroid to nearest transit stop.

    Downloads transit stops via tiled queries, then uses a KD-tree.
    """
    transit_stops = _fetch_features_tiled(
        hex_gdf, tags=TRANSIT_TAGS, label="transit stops", step_deg=0.25,
    )

    if transit_stops.empty:
        return pd.DataFrame({"h3_index": hex_gdf["h3_index"], "transit_proximity": np.nan})

    stop_gdf = gpd.GeoDataFrame(
        geometry=transit_stops.geometry.centroid.values, crs="EPSG:4326"
    ).to_crs("EPSG:32616")

    hex_points = gpd.GeoDataFrame(
        {"h3_index": hex_gdf["h3_index"].values},
        geometry=[Point(lng, lat) for lng, lat in zip(hex_gdf["lng"], hex_gdf["lat"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32616")

    stop_coords = np.array([(g.x, g.y) for g in stop_gdf.geometry])
    hex_coords = np.array([(g.x, g.y) for g in hex_points.geometry])
    tree = cKDTree(stop_coords)
    distances, _ = tree.query(hex_coords, k=1)

    result = pd.DataFrame({
        "h3_index": hex_gdf["h3_index"].values,
        "transit_proximity": distances,
    })

    print(f"Transit proximity: {len(result)} hexes (median={np.nanmedian(distances):.0f}m)")
    return result


def compute_road_density(hex_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute road density (km of road per km^2) for each hex.

    Downloads the road network via tiled graph queries, converts to
    edges GeoDataFrame, then does spatial join to sum lengths per hex.
    """
    tiles = _tile_bbox(hex_gdf, step_deg=0.15)
    print(f"Downloading road network across {len(tiles)} tiles...")

    edge_frames = []
    for i, bbox in enumerate(tiles):
        try:
            graph = ox.graph_from_bbox(bbox=bbox, network_type="drive")
            edges = ox.graph_to_gdfs(graph, nodes=False)
            edge_frames.append(edges[["geometry", "length"]])
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(tiles)} tiles done")

    if not edge_frames:
        print("  Warning: no road segments downloaded")
        return pd.DataFrame({"h3_index": hex_gdf["h3_index"], "road_density": 0.0})

    all_edges = gpd.GeoDataFrame(pd.concat(edge_frames, ignore_index=True), crs="EPSG:4326")
    all_edges = all_edges.to_crs("EPSG:32616")
    print(f"  Total road segments: {len(all_edges)}")

    hex_proj = hex_gdf[["h3_index", "geometry"]].to_crs("EPSG:32616")
    hex_proj["hex_area_km2"] = hex_proj.geometry.area / 1e6

    joined = gpd.sjoin(
        all_edges[["geometry", "length"]],
        hex_proj[["h3_index", "geometry"]],
        predicate="intersects",
    )

    road_km = (
        joined.groupby("h3_index")["length"]
        .sum()
        .div(1000.0)
        .rename("road_length_km")
        .reset_index()
    )

    result = hex_proj[["h3_index", "hex_area_km2"]].merge(road_km, on="h3_index", how="left")
    result["road_length_km"] = result["road_length_km"].fillna(0.0)
    result["road_density"] = result["road_length_km"] / result["hex_area_km2"]
    result = result[["h3_index", "road_density"]]

    print(f"Road density: {len(result)} hexes (mean={result['road_density'].mean():.1f} km/km²)")
    return result


if __name__ == "__main__":
    from backend.pipeline.hex_grid import generate_hex_grid

    grid = generate_hex_grid(resolution=8)

    walk = compute_walk_score(grid)
    transit = compute_transit_proximity(grid)
    roads = compute_road_density(grid)

    osmnx_df = walk.merge(transit, on="h3_index").merge(roads, on="h3_index")

    out = Path("data/osmnx_features_hex.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    osmnx_df.to_parquet(out, index=False)
    print(f"Saved to {out}: {len(osmnx_df)} rows, columns={list(osmnx_df.columns)}")
