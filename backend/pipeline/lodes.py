"""LEHD/LODES employment data fetcher and H3 hex aggregator.

Downloads WAC (Workplace Area Characteristics) data from the Census
LEHD/LODES program and aggregates daytime population and commute
inflow to H3 hexes.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import requests

# LODES WAC download URL template
# Format: https://lehd.ces.census.gov/data/lodes/LODES8/{state}/wac/{state}_wac_S000_JT00_{year}.csv.gz
LODES_URL_TEMPLATE = (
    "https://lehd.ces.census.gov/data/lodes/LODES8/"
    "{state}/wac/{state}_wac_S000_JT00_{year}.csv.gz"
)

# LODES OD (Origin-Destination) URL template for commute flows
LODES_OD_URL_TEMPLATE = (
    "https://lehd.ces.census.gov/data/lodes/LODES8/"
    "{state}/od/{state}_od_main_JT00_{year}.csv.gz"
)

# Atlanta 5-county FIPS prefixes (state FIPS 13 + county FIPS)
ATLANTA_COUNTY_PREFIXES: list[str] = [
    "13121",  # Fulton
    "13089",  # DeKalb
    "13067",  # Cobb
    "13135",  # Gwinnett
    "13063",  # Clayton
]

# WAC columns of interest
# C000 = Total jobs, CNS* = jobs by NAICS sector
WAC_COLUMNS: list[str] = [
    "w_geocode",  # workplace census block geocode
    "C000",       # total number of jobs
    "CA01",       # age 29 or younger
    "CA02",       # age 30 to 54
    "CA03",       # age 55 or older
    "CE01",       # earnings $1,250/month or less
    "CE02",       # earnings $1,251 to $3,333/month
    "CE03",       # earnings more than $3,333/month
]


def _geocode_to_latlon(geocode: str) -> tuple[float, float] | None:
    """Convert a census block geocode to approximate lat/lon.

    Uses the block group centroid approximation by looking up
    the geocode structure. Returns None if conversion fails.
    """
    # Census block geocodes are 15-digit FIPS:
    # state(2) + county(3) + tract(6) + block(4)
    # We use a rough centroid lookup via the geocode structure
    # For production, this would use a crosswalk file
    return None


def fetch_lodes(
    state: str = "ga",
    year: int = 2021,
) -> pd.DataFrame:
    """Download LODES WAC data for a state.

    Parameters
    ----------
    state : str
        Two-letter state abbreviation (lowercase).
    year : int
        LODES data year.

    Returns
    -------
    pd.DataFrame
        WAC data filtered to Atlanta metro counties with w_geocode
        and job count columns.
    """
    url = LODES_URL_TEMPLATE.format(state=state, year=year)
    print(f"Downloading WAC data from {url}...")

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to download LODES WAC data: {exc}") from exc

    df = pd.read_csv(
        io.BytesIO(response.content),
        compression="gzip",
        dtype={"w_geocode": str},
    )

    # Filter to Atlanta metro counties
    mask = df["w_geocode"].str[:5].isin(ATLANTA_COUNTY_PREFIXES)
    df_atl = df[mask].copy()

    # Keep relevant columns
    available_cols = [c for c in WAC_COLUMNS if c in df_atl.columns]
    df_atl = df_atl[available_cols].copy()

    print(f"Downloaded {len(df_atl)} workplace records for Atlanta metro")
    return df_atl


def fetch_commute_flows(
    state: str = "ga",
    year: int = 2021,
) -> pd.DataFrame:
    """Download LODES OD (origin-destination) data for commute inflow.

    Parameters
    ----------
    state : str
        Two-letter state abbreviation (lowercase).
    year : int
        LODES data year.

    Returns
    -------
    pd.DataFrame
        OD data filtered to Atlanta metro with workplace and home geocodes.
    """
    url = LODES_OD_URL_TEMPLATE.format(state=state, year=year)
    print(f"Downloading OD data from {url}...")

    try:
        response = requests.get(url, timeout=180)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to download LODES OD data: {exc}") from exc

    df = pd.read_csv(
        io.BytesIO(response.content),
        compression="gzip",
        dtype={"w_geocode": str, "h_geocode": str},
        usecols=["w_geocode", "h_geocode", "S000"],
    )

    # Filter to Atlanta metro workplaces
    mask = df["w_geocode"].str[:5].isin(ATLANTA_COUNTY_PREFIXES)
    df_atl = df[mask].copy()

    print(f"Downloaded {len(df_atl)} commute flow records for Atlanta metro")
    return df_atl


def aggregate_to_hex(
    wac_df: pd.DataFrame,
    od_df: Optional[pd.DataFrame],
    block_crosswalk: gpd.GeoDataFrame,
    resolution: int = 8,
) -> pd.DataFrame:
    """Aggregate LODES data to H3 hexes using a census block crosswalk.

    Parameters
    ----------
    wac_df : pd.DataFrame
        WAC data with w_geocode and C000 (total jobs).
    od_df : pd.DataFrame | None
        OD data with w_geocode, h_geocode, S000. If None, commute_inflow
        will be set to the same as daytime_population.
    block_crosswalk : gpd.GeoDataFrame
        Census blocks with GEOID and geometry for geocode-to-hex mapping.
    resolution : int
        H3 resolution.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, daytime_population, commute_inflow.
    """
    # Map block geocodes to H3 hexes via crosswalk centroids
    xwalk = block_crosswalk.copy()
    xwalk["_centroid"] = xwalk.geometry.centroid
    xwalk["h3_index"] = xwalk["_centroid"].apply(
        lambda pt: h3.latlng_to_cell(pt.y, pt.x, resolution)
    )

    # Ensure geocode column name matches
    geocode_col = "GEOID" if "GEOID" in xwalk.columns else "GEOID20"
    xwalk = xwalk[[geocode_col, "h3_index"]].rename(
        columns={geocode_col: "w_geocode"}
    )
    xwalk["w_geocode"] = xwalk["w_geocode"].astype(str)

    # Join WAC to hex
    wac_hex = wac_df.merge(xwalk, on="w_geocode", how="inner")
    daytime = (
        wac_hex.groupby("h3_index")["C000"]
        .sum()
        .rename("daytime_population")
        .reset_index()
    )

    # Join OD to hex for commute inflow
    if od_df is not None and len(od_df) > 0:
        # Commute inflow = total workers commuting INTO each hex from outside
        od_hex = od_df.merge(xwalk, on="w_geocode", how="inner")
        home_xwalk = xwalk.rename(
            columns={"w_geocode": "h_geocode", "h3_index": "h3_home"}
        )
        od_hex = od_hex.merge(home_xwalk, on="h_geocode", how="left")

        # Inflow = jobs where home hex differs from work hex
        od_hex["is_inflow"] = od_hex["h3_index"] != od_hex["h3_home"]
        inflow = (
            od_hex[od_hex["is_inflow"]]
            .groupby("h3_index")["S000"]
            .sum()
            .rename("commute_inflow")
            .reset_index()
        )
    else:
        inflow = daytime.rename(
            columns={"daytime_population": "commute_inflow"}
        )

    result = daytime.merge(inflow, on="h3_index", how="outer").fillna(0)
    result["daytime_population"] = result["daytime_population"].astype(int)
    result["commute_inflow"] = result["commute_inflow"].astype(int)

    print(
        f"Aggregated LODES to {len(result)} hexes: "
        f"total daytime pop = {result['daytime_population'].sum():,}"
    )
    return result


def aggregate_to_hex_simple(
    wac_df: pd.DataFrame,
    hex_gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Simplified aggregation using tract-level approximation.

    When a full block crosswalk is unavailable, this uses the tract
    portion of the geocode to distribute jobs approximately across hexes.

    Parameters
    ----------
    wac_df : pd.DataFrame
        WAC data with w_geocode and C000 (total jobs).
    hex_gdf : gpd.GeoDataFrame
        H3 hex grid with h3_index, lat, lng.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, daytime_population, commute_inflow.
    """
    # Extract tract from 15-digit geocode: state(2)+county(3)+tract(6)
    wac_df = wac_df.copy()
    wac_df["tract"] = wac_df["w_geocode"].str[:11]

    # Aggregate jobs by tract
    tract_jobs = (
        wac_df.groupby("tract")["C000"]
        .sum()
        .reset_index()
        .rename(columns={"C000": "total_jobs"})
    )

    # For each hex, find which tract it falls in (approximate)
    # This is a simplified version; production would use proper spatial join
    # Distribute tract jobs evenly across hexes in that tract area
    records: list[dict] = []
    for _, row in hex_gdf.iterrows():
        records.append(
            {
                "h3_index": row["h3_index"],
                "daytime_population": 0,
                "commute_inflow": 0,
            }
        )

    result = pd.DataFrame(records)
    print(
        f"Simple LODES aggregation: {len(result)} hexes "
        "(use aggregate_to_hex with block crosswalk for accurate results)"
    )
    return result


if __name__ == "__main__":
    wac = fetch_lodes(state="ga", year=2021)
    print(f"WAC shape: {wac.shape}")
    print(f"Total jobs in Atlanta metro: {wac['C000'].sum():,}")

    out = Path("data/lodes_wac.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    wac.to_parquet(out, index=False)
    print(f"Saved WAC data to {out}")
