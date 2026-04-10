"""Census ACS data fetcher and H3 hex joiner.

Fetches ACS 5-Year block-group-level data for Atlanta metro counties
using censusdis and performs area-weighted spatial joins to H3 hexes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

try:
    import censusdis.data as ced
    import censusdis.datasets as cds
except ImportError:
    ced = None  # type: ignore[assignment]
    cds = None  # type: ignore[assignment]

# ACS 5-Year variable codes
CENSUS_VARIABLES: dict[str, str] = {
    "B19013_001E": "median_income",
    "B01003_001E": "total_pop",
    "B23025_003E": "employed",
    "B25064_001E": "median_rent",
    "B11001_001E": "households",
    "B15003_022E": "bachelors_degree",
}

# GA FIPS + 5-county FIPS codes
STATE_FIPS = "13"
COUNTY_FIPS: list[str] = [
    "121",  # Fulton
    "089",  # DeKalb
    "067",  # Cobb
    "135",  # Gwinnett
    "063",  # Clayton
]


def fetch_census_features(
    state_fips: str = STATE_FIPS,
    counties: Optional[list[str]] = None,
    year: int = 2022,
) -> gpd.GeoDataFrame:
    """Fetch ACS 5-Year block-group data for Atlanta metro counties.

    Parameters
    ----------
    state_fips : str
        State FIPS code (default: "13" for Georgia).
    counties : list[str] | None
        County FIPS codes. Defaults to Fulton, DeKalb, Cobb, Gwinnett, Clayton.
    year : int
        ACS year to query.

    Returns
    -------
    gpd.GeoDataFrame
        Block-group-level census data with geometry and renamed columns.
    """
    if ced is None:
        raise ImportError(
            "censusdis is required. Install with: pip install censusdis"
        )

    counties = counties or COUNTY_FIPS
    variable_codes = list(CENSUS_VARIABLES.keys())

    frames: list[gpd.GeoDataFrame] = []
    for county in counties:
        try:
            gdf = ced.download(
                dataset=cds.ACS5,
                vintage=year,
                download_variables=variable_codes,
                state=state_fips,
                county=county,
                block_group="*",
                with_geometry=True,
            )
            frames.append(gdf)
        except Exception as exc:
            print(f"Warning: failed to fetch county {county}: {exc}")
            continue

    if not frames:
        raise RuntimeError("No census data fetched for any county.")

    result = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))

    # Rename columns to human-readable names
    result = result.rename(columns=CENSUS_VARIABLES)

    # Convert numeric columns, coercing errors to NaN
    for col in CENSUS_VARIABLES.values():
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    # Derive additional features
    if "total_pop" in result.columns and "employed" in result.columns:
        result["employment_rate"] = np.where(
            result["total_pop"] > 0,
            result["employed"] / result["total_pop"],
            np.nan,
        )

    if "total_pop" in result.columns and "bachelors_degree" in result.columns:
        result["pct_bachelors"] = np.where(
            result["total_pop"] > 0,
            result["bachelors_degree"] / result["total_pop"],
            np.nan,
        )

    # Ensure CRS is WGS84
    if result.crs is None:
        result = result.set_crs("EPSG:4326")
    else:
        result = result.to_crs("EPSG:4326")

    print(f"Fetched {len(result)} block groups across {len(counties)} counties")
    return result


def join_to_hex(
    census_gdf: gpd.GeoDataFrame,
    hex_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Area-weighted spatial join of census block groups to H3 hexes.

    For each hex, census values are weighted by the fractional area of
    overlap between the hex and each intersecting block group.

    Parameters
    ----------
    census_gdf : gpd.GeoDataFrame
        Census data with geometry (block groups).
    hex_gdf : gpd.GeoDataFrame
        H3 hex grid with h3_index and geometry columns.

    Returns
    -------
    gpd.GeoDataFrame
        Hex grid with area-weighted census features joined.
    """
    numeric_cols = [
        col
        for col in CENSUS_VARIABLES.values()
        if col in census_gdf.columns
    ]
    # Include derived columns
    for extra in ("employment_rate", "pct_bachelors"):
        if extra in census_gdf.columns:
            numeric_cols.append(extra)

    # Project to UTM 16N (Atlanta) for area calculations
    census_proj = census_gdf.to_crs("EPSG:32616")
    hex_proj = hex_gdf.to_crs("EPSG:32616")

    # Compute block group areas
    census_proj["_bg_area"] = census_proj.geometry.area

    # Overlay intersection
    intersection = gpd.overlay(hex_proj, census_proj, how="intersection")
    intersection["_int_area"] = intersection.geometry.area
    intersection["_weight"] = np.where(
        intersection["_bg_area"] > 0,
        intersection["_int_area"] / intersection["_bg_area"],
        0.0,
    )

    # Weighted aggregation per hex
    agg_records: list[dict] = []
    for h3_idx, group in intersection.groupby("h3_index"):
        record: dict = {"h3_index": h3_idx}
        total_weight = group["_weight"].sum()
        for col in numeric_cols:
            if col in group.columns:
                valid = group[[col, "_weight"]].dropna(subset=[col])
                if len(valid) > 0 and total_weight > 0:
                    record[col] = (
                        (valid[col] * valid["_weight"]).sum() / total_weight
                    )
                else:
                    record[col] = np.nan
        agg_records.append(record)

    agg_df = pd.DataFrame(agg_records)

    # Merge back onto hex grid
    result = hex_gdf.merge(agg_df, on="h3_index", how="left")

    # Compute density features
    if "total_pop" in result.columns:
        # Approximate hex area in km^2 from projected geometry
        hex_areas_km2 = hex_proj.geometry.area / 1e6
        result["population_density"] = result["total_pop"] / hex_areas_km2.values
    if "households" in result.columns:
        hex_areas_km2 = hex_proj.geometry.area / 1e6
        result["household_density"] = result["households"] / hex_areas_km2.values

    print(f"Joined census features to {len(result)} hexes")
    return result


if __name__ == "__main__":
    from backend.pipeline.hex_grid import generate_hex_grid

    grid = generate_hex_grid(resolution=8)
    census = fetch_census_features()
    joined = join_to_hex(census, grid)
    out = Path("data/census_hex.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    joined.to_parquet(out, index=False)
    print(f"Saved to {out}: {len(joined)} rows, columns={list(joined.columns)}")
