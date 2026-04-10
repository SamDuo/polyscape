"""Overture Maps POI extraction and H3 hex aggregation.

Downloads Overture Places within the Atlanta metro bounding box and
counts competitor (restaurant) and complementary (retail + entertainment)
POIs per H3 hex cell.
"""

from __future__ import annotations

from typing import Optional

import geopandas as gpd
import h3
import pandas as pd

try:
    import overturemaps
except ImportError:
    overturemaps = None  # type: ignore[assignment]

# Atlanta metro bounding box (west, south, east, north)
ATLANTA_BBOX: tuple[float, float, float, float] = (
    -84.90,  # west
    33.40,   # south
    -83.80,  # east
    34.16,   # north
)

# Overture category mappings
COMPETITOR_CATEGORIES: set[str] = {
    "restaurant",
    "fast_food",
    "cafe",
    "coffee_shop",
    "food_court",
    "diner",
}

COMPLEMENTARY_CATEGORIES: set[str] = {
    "retail",
    "shop",
    "shopping_mall",
    "entertainment",
    "cinema",
    "theater",
    "gym",
    "fitness_center",
    "bar",
    "nightclub",
    "bowling_alley",
    "amusement_park",
}


def fetch_pois(
    bbox: Optional[tuple[float, float, float, float]] = None,
) -> gpd.GeoDataFrame:
    """Download Overture Places within the Atlanta metro bounding box.

    Parameters
    ----------
    bbox : tuple[float, float, float, float] | None
        Bounding box as (west, south, east, north).
        Defaults to ATLANTA_BBOX.

    Returns
    -------
    gpd.GeoDataFrame
        POI data with geometry, category, and name columns.
    """
    if overturemaps is None:
        raise ImportError(
            "overturemaps is required. Install with: pip install overturemaps"
        )
    from shapely import wkb
    from shapely.geometry import shape

    bbox = bbox or ATLANTA_BBOX

    records: list[dict] = []
    reader = overturemaps.record_batch_reader("place", bbox=bbox)

    for batch in reader:
        tbl = batch.to_pydict()
        n_rows = len(tbl.get("id", []))
        for i in range(n_rows):
            record: dict = {}
            record["id"] = tbl["id"][i] if "id" in tbl else None
            record["name"] = (
                tbl["names"][i].get("primary", "")
                if "names" in tbl and tbl["names"][i]
                else ""
            )

            # Extract primary category
            categories = tbl.get("categories", [None] * n_rows)
            cat_entry = categories[i] if i < len(categories) else None
            if isinstance(cat_entry, dict):
                record["category"] = cat_entry.get("primary", "")
            elif isinstance(cat_entry, str):
                record["category"] = cat_entry
            else:
                record["category"] = ""

            # Extract and convert geometry from WKB bytes to Shapely
            geom_raw = tbl.get("geometry", [None] * n_rows)
            raw = geom_raw[i] if i < len(geom_raw) else None
            if raw is not None:
                try:
                    if isinstance(raw, bytes):
                        record["geometry"] = wkb.loads(raw)
                    elif isinstance(raw, dict):
                        record["geometry"] = shape(raw)
                    else:
                        record["geometry"] = None
                except Exception:
                    record["geometry"] = None
            else:
                record["geometry"] = None

            records.append(record)

    if not records:
        print("Warning: no POIs fetched from Overture Maps.")
        return gpd.GeoDataFrame(
            columns=["id", "name", "category", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    # Filter out records with no valid geometry
    records = [r for r in records if r.get("geometry") is not None]
    if not records:
        print("Warning: all POI geometries failed to parse.")
        return gpd.GeoDataFrame(
            columns=["id", "name", "category", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    print(f"Fetched {len(gdf)} POIs from Overture Maps")
    return gdf


def _classify_poi(category: str) -> str:
    """Classify a POI category as competitor, complementary, or other."""
    cat_lower = category.lower().strip() if category else ""
    if any(c in cat_lower for c in COMPETITOR_CATEGORIES):
        return "competitor"
    if any(c in cat_lower for c in COMPLEMENTARY_CATEGORIES):
        return "complementary"
    return "other"


def count_pois_per_hex(
    pois_gdf: gpd.GeoDataFrame,
    resolution: int = 8,
) -> pd.DataFrame:
    """Count competitor and complementary POIs per H3 hex.

    Parameters
    ----------
    pois_gdf : gpd.GeoDataFrame
        POI data with geometry and category columns.
    resolution : int
        H3 resolution for hex assignment.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, competitor_count, complementary_poi_count.
    """
    if pois_gdf.empty:
        return pd.DataFrame(
            columns=["h3_index", "competitor_count", "complementary_poi_count"]
        )

    # Assign each POI to an H3 hex
    pois_gdf = pois_gdf.copy()
    pois_gdf["_lat"] = pois_gdf.geometry.y
    pois_gdf["_lng"] = pois_gdf.geometry.x
    pois_gdf["h3_index"] = pois_gdf.apply(
        lambda row: h3.latlng_to_cell(row["_lat"], row["_lng"], resolution),
        axis=1,
    )

    # Classify POIs
    pois_gdf["_poi_type"] = pois_gdf["category"].apply(_classify_poi)

    # Aggregate counts per hex
    competitors = (
        pois_gdf[pois_gdf["_poi_type"] == "competitor"]
        .groupby("h3_index")
        .size()
        .rename("competitor_count")
    )
    complementary = (
        pois_gdf[pois_gdf["_poi_type"] == "complementary"]
        .groupby("h3_index")
        .size()
        .rename("complementary_poi_count")
    )

    result = pd.DataFrame({"competitor_count": competitors, "complementary_poi_count": complementary})
    result = result.fillna(0).astype(int).reset_index()
    result.columns = ["h3_index", "competitor_count", "complementary_poi_count"]

    print(
        f"Counted POIs in {len(result)} hexes: "
        f"{result['competitor_count'].sum()} competitors, "
        f"{result['complementary_poi_count'].sum()} complementary"
    )
    return result


if __name__ == "__main__":
    from pathlib import Path

    pois = fetch_pois()
    counts = count_pois_per_hex(pois, resolution=8)
    out = Path("data/overture_pois_hex.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    counts.to_parquet(out, index=False)
    print(f"Saved to {out}: {len(counts)} rows")
