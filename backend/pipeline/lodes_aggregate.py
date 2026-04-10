"""Aggregate LODES WAC data to H3 hexes using pygris block geometries.

Downloads census block geometries for the 5-county Atlanta metro,
maps block geocodes to H3 hexes, and sums jobs per hex.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pygris


# Atlanta 5-county FIPS codes
COUNTIES = ["121", "089", "067", "135", "063"]
STATE_FIPS = "13"


def get_block_crosswalk() -> gpd.GeoDataFrame:
    """Download census block geometries and build geocode-to-H3 crosswalk."""
    frames = []
    for county in COUNTIES:
        print(f"  Downloading blocks for county {county}...")
        try:
            blocks = pygris.blocks(state=STATE_FIPS, county=county, year=2020)
            frames.append(blocks)
        except Exception as exc:
            print(f"  Warning: failed for county {county}: {exc}")

    if not frames:
        raise RuntimeError("No block geometries downloaded.")

    all_blocks = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    all_blocks = all_blocks.to_crs("EPSG:4326")

    # GEOID20 is the 15-digit block geocode
    geocode_col = "GEOID20" if "GEOID20" in all_blocks.columns else "GEOID"
    all_blocks = all_blocks[[geocode_col, "geometry"]].rename(
        columns={geocode_col: "w_geocode"}
    )

    # Assign each block centroid to an H3 hex
    centroids = all_blocks.geometry.centroid
    all_blocks["h3_index"] = [
        h3.latlng_to_cell(pt.y, pt.x, 8) for pt in centroids
    ]

    print(f"Built crosswalk: {len(all_blocks)} blocks → H3 hexes")
    return all_blocks[["w_geocode", "h3_index"]]


def aggregate_wac_to_hex(
    wac_path: str | Path = "data/lodes_wac.parquet",
    output_path: str | Path = "data/lodes_hex.parquet",
) -> pd.DataFrame:
    """Load WAC data and aggregate jobs to H3 hexes."""
    wac = pd.read_parquet(wac_path)
    wac["w_geocode"] = wac["w_geocode"].astype(str).str.zfill(15)
    print(f"Loaded {len(wac)} WAC records, {wac['C000'].sum():,} total jobs")

    crosswalk = get_block_crosswalk()
    crosswalk["w_geocode"] = crosswalk["w_geocode"].astype(str).str.zfill(15)

    # Join WAC to crosswalk
    merged = wac.merge(crosswalk, on="w_geocode", how="inner")
    print(f"Matched {len(merged)} of {len(wac)} records to H3 hexes")

    # Aggregate jobs per hex
    hex_jobs = (
        merged.groupby("h3_index")
        .agg(
            daytime_population=("C000", "sum"),
            commute_inflow=("C000", "sum"),  # Approximation without OD data
        )
        .reset_index()
    )
    hex_jobs["daytime_population"] = hex_jobs["daytime_population"].astype(int)
    hex_jobs["commute_inflow"] = hex_jobs["commute_inflow"].astype(int)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    hex_jobs.to_parquet(output_path, index=False)

    print(
        f"Saved {len(hex_jobs)} hex records to {output_path}\n"
        f"  Total daytime pop: {hex_jobs['daytime_population'].sum():,}"
    )
    return hex_jobs


if __name__ == "__main__":
    aggregate_wac_to_hex()
