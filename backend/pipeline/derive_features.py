"""Derive walk_score, transit_proximity, road_density, and land_use_mix
from existing pipeline data (Overture POIs, Census, hex grid).

Avoids slow per-hex Overpass queries by using spatial aggregation on
data already downloaded.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point

try:
    import osmnx as ox
except ImportError:
    ox = None


def derive_walk_score(
    hex_gdf: gpd.GeoDataFrame,
    overture_path: str | Path = "data/overture_pois_hex.parquet",
) -> pd.DataFrame:
    """Walk score = total POI count in hex + k-ring(1) neighbors.

    Uses already-downloaded Overture POI counts. Each hex gets its own
    competitor + complementary count plus the average of its 6 neighbors.
    """
    pois = pd.read_parquet(overture_path)

    # Merge POI counts onto hex grid
    df = hex_gdf[["h3_index"]].merge(pois, on="h3_index", how="left")
    df["competitor_count"] = df["competitor_count"].fillna(0)
    df["complementary_poi_count"] = df["complementary_poi_count"].fillna(0)
    df["_local_pois"] = df["competitor_count"] + df["complementary_poi_count"]

    # Add neighbor POI counts (k-ring 1)
    poi_lookup = df.set_index("h3_index")["_local_pois"].to_dict()

    def _neighbor_avg(h3_idx: str) -> float:
        neighbors = h3.grid_ring(h3_idx, 1)
        vals = [poi_lookup.get(n, 0) for n in neighbors]
        return np.mean(vals) if vals else 0

    df["_neighbor_avg"] = df["h3_index"].apply(_neighbor_avg)
    df["walk_score"] = (df["_local_pois"] + df["_neighbor_avg"]).round(0).astype(int)

    print(f"Derived walk_score: mean={df['walk_score'].mean():.1f}, max={df['walk_score'].max()}")
    return df[["h3_index", "walk_score"]]


def derive_transit_proximity(
    hex_gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Transit proximity = Euclidean distance to nearest MARTA stop.

    Fetches MARTA stops via a single small Overpass query for the
    place 'Atlanta' (bounded by city limits, not full metro bbox).
    Falls back to census-based proxy if Overpass fails.
    """
    if ox is None:
        print("Warning: osmnx not available, using proxy for transit_proximity")
        return _transit_proxy(hex_gdf)

    print("Downloading MARTA transit stops...")
    transit_tags = {
        "public_transport": "stop_position",
        "railway": ["station", "halt"],
        "highway": "bus_stop",
    }

    try:
        # Use place query (city boundary, much smaller than metro bbox)
        stops = ox.features_from_place("Atlanta, Georgia, USA", tags=transit_tags)
        print(f"  Downloaded {len(stops)} transit stops")
    except Exception as exc:
        print(f"  Warning: transit stop download failed: {exc}")
        # Try a smaller bbox centered on Atlanta core
        try:
            core_bbox = (33.85, 33.65, -84.30, -84.50)  # N, S, E, W
            stops = ox.features_from_bbox(bbox=core_bbox, tags=transit_tags)
            print(f"  Fallback: {len(stops)} transit stops from core bbox")
        except Exception:
            print("  Using proxy for transit_proximity")
            return _transit_proxy(hex_gdf)

    if len(stops) == 0:
        return _transit_proxy(hex_gdf)

    # Project stop centroids to UTM for distance calculation
    stop_points = stops.geometry.centroid
    stop_gdf = gpd.GeoDataFrame(
        geometry=stop_points.values, crs="EPSG:4326"
    ).to_crs("EPSG:32616")

    hex_points = gpd.GeoDataFrame(
        {"h3_index": hex_gdf["h3_index"].values},
        geometry=[Point(lng, lat) for lng, lat in zip(hex_gdf["lng"], hex_gdf["lat"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32616")

    # KD-tree for fast nearest-neighbor
    stop_coords = np.array([(g.x, g.y) for g in stop_gdf.geometry])
    hex_coords = np.array([(g.x, g.y) for g in hex_points.geometry])
    tree = cKDTree(stop_coords)
    distances, _ = tree.query(hex_coords, k=1)

    result = pd.DataFrame({
        "h3_index": hex_gdf["h3_index"].values,
        "transit_proximity": distances,
    })

    print(f"Transit proximity: median={np.nanmedian(distances):.0f}m")
    return result


def _transit_proxy(hex_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Proxy transit proximity based on distance from Atlanta center."""
    center = Point(-84.3880, 33.7490)  # Atlanta city center
    hex_points = gpd.GeoDataFrame(
        {"h3_index": hex_gdf["h3_index"].values},
        geometry=[Point(lng, lat) for lng, lat in zip(hex_gdf["lng"], hex_gdf["lat"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32616")

    center_proj = gpd.GeoSeries([center], crs="EPSG:4326").to_crs("EPSG:32616").iloc[0]
    distances = hex_points.geometry.distance(center_proj)

    return pd.DataFrame({
        "h3_index": hex_gdf["h3_index"].values,
        "transit_proximity": distances.values,
    })


def derive_road_density(
    hex_gdf: gpd.GeoDataFrame,
    census_path: str | Path = "data/census_hex.parquet",
) -> pd.DataFrame:
    """Road density proxy from population density + employment rate.

    Road density is highly correlated with urbanization. This proxy
    uses a log-linear combination of population and employment density.
    """
    census = pd.read_parquet(census_path)
    df = hex_gdf[["h3_index"]].merge(
        census[["h3_index", "population_density", "employment_rate"]],
        on="h3_index",
        how="left",
    )

    pop = df["population_density"].fillna(0).clip(lower=0)
    emp = df["employment_rate"].fillna(0).clip(lower=0)

    # Log-scaled proxy: denser areas have more roads
    road_density = np.log1p(pop) * 2.0 + emp * 10.0
    # Normalize to realistic range (0-50 km/km²)
    rd_min, rd_max = road_density.min(), road_density.max()
    if rd_max > rd_min:
        road_density = (road_density - rd_min) / (rd_max - rd_min) * 50.0
    else:
        road_density = 0.0

    return pd.DataFrame({
        "h3_index": df["h3_index"],
        "road_density": road_density,
    })


def derive_land_use_mix(
    hex_gdf: gpd.GeoDataFrame,
    overture_path: str | Path = "data/overture_pois_hex.parquet",
    census_path: str | Path = "data/census_hex.parquet",
) -> pd.DataFrame:
    """Land use mix = normalized entropy of residential vs commercial indicators.

    Combines POI density (commercial proxy) with household density
    (residential proxy) to compute a Shannon entropy-based mix score.
    """
    pois = pd.read_parquet(overture_path)
    census = pd.read_parquet(census_path)

    df = hex_gdf[["h3_index"]].merge(pois, on="h3_index", how="left")
    df = df.merge(
        census[["h3_index", "household_density"]],
        on="h3_index",
        how="left",
    )

    poi_total = (
        df["competitor_count"].fillna(0) + df["complementary_poi_count"].fillna(0)
    )
    hh = df["household_density"].fillna(0)

    # Normalize both to [0, 1]
    poi_norm = poi_total / poi_total.max() if poi_total.max() > 0 else poi_total
    hh_norm = hh / hh.max() if hh.max() > 0 else hh

    # Shannon entropy of the two proportions
    total = poi_norm + hh_norm
    total = total.replace(0, np.nan)
    p_poi = poi_norm / total
    p_hh = hh_norm / total

    # Entropy: -sum(p * log(p)), normalized to [0, 1]
    entropy = np.where(
        total.notna(),
        -(
            np.where(p_poi > 0, p_poi * np.log2(p_poi.clip(lower=1e-10)), 0)
            + np.where(p_hh > 0, p_hh * np.log2(p_hh.clip(lower=1e-10)), 0)
        ),
        0,
    )

    return pd.DataFrame({
        "h3_index": df["h3_index"],
        "land_use_mix": entropy,
    })


if __name__ == "__main__":
    grid = gpd.read_parquet("data/hex_grid_res8.parquet")

    walk = derive_walk_score(grid)
    transit = derive_transit_proximity(grid)
    roads = derive_road_density(grid)
    lum = derive_land_use_mix(grid)

    derived = (
        walk
        .merge(transit, on="h3_index")
        .merge(roads, on="h3_index")
        .merge(lum, on="h3_index")
    )

    out = Path("data/derived_features_hex.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    derived.to_parquet(out, index=False)
    print(f"Saved to {out}: {len(derived)} rows, columns={list(derived.columns)}")
