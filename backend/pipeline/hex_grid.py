"""H3 hex grid generator for Atlanta metro (5-county boundary).

Generates H3 hexagonal grids at configurable resolutions for
Fulton, DeKalb, Cobb, Gwinnett, and Clayton counties.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Polygon

# Rough bounding polygon for Atlanta 5-county area
# (Fulton, DeKalb, Cobb, Gwinnett, Clayton)
# Vertices ordered counter-clockwise as (lat, lng) for H3
ATLANTA_BOUNDARY_LATLNG: list[tuple[float, float]] = [
    (34.08, -84.90),  # NW corner (Cobb)
    (34.16, -84.40),  # N (Fulton/north)
    (34.16, -83.95),  # NE (Gwinnett)
    (33.96, -83.80),  # E (Gwinnett)
    (33.75, -83.90),  # SE (DeKalb)
    (33.55, -84.10),  # S (Clayton)
    (33.40, -84.40),  # SW (Clayton/south Fulton)
    (33.55, -84.60),  # W (south Cobb)
    (33.80, -84.80),  # W (Cobb)
    (34.08, -84.90),  # close ring
]

# Approximate expected hex counts per resolution
APPROX_HEX_COUNTS: dict[int, str] = {
    7: "~2K hexes",
    8: "~14K hexes",
    9: "~95K hexes",
}


def _h3_cell_to_shapely(h3_index: str) -> Polygon:
    """Convert an H3 cell index to a Shapely Polygon."""
    boundary = h3.cell_to_boundary(h3_index)
    # h3 returns boundary as list of (lat, lng); Shapely needs (lng, lat)
    coords = [(lng, lat) for lat, lng in boundary]
    # Close the ring
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return Polygon(coords)


def generate_hex_grid(resolution: int = 8) -> gpd.GeoDataFrame:
    """Generate an H3 hex grid covering the Atlanta 5-county metro area.

    Parameters
    ----------
    resolution : int
        H3 resolution. Supported: 7 (~2K hexes), 8 (~14K), 9 (~95K).

    Returns
    -------
    gpd.GeoDataFrame
        Columns: h3_index, geometry (hex polygon), lat, lng (centroid).
    """
    if resolution not in (7, 8, 9):
        raise ValueError(
            f"Resolution {resolution} not supported. Use 7, 8, or 9. "
            f"Expected counts: {APPROX_HEX_COUNTS}"
        )

    # Build H3 LatLngPoly from the boundary
    poly = h3.LatLngPoly(ATLANTA_BOUNDARY_LATLNG)
    cells = h3.polygon_to_cells(poly, res=resolution)

    records: list[dict] = []
    for cell in cells:
        lat, lng = h3.cell_to_latlng(cell)
        records.append(
            {
                "h3_index": cell,
                "lat": lat,
                "lng": lng,
                "geometry": _h3_cell_to_shapely(cell),
            }
        )

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    print(f"Generated {len(gdf)} hexes at resolution {resolution}")
    return gdf


def save_grid(gdf: gpd.GeoDataFrame, path: str | Path) -> Path:
    """Save hex grid GeoDataFrame as GeoParquet.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Hex grid with geometry column.
    path : str | Path
        Output file path (should end in .parquet).

    Returns
    -------
    Path
        Resolved output path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out, index=False)
    print(f"Saved grid to {out} ({out.stat().st_size / 1024:.1f} KB)")
    return out


if __name__ == "__main__":
    for res in (7, 8, 9):
        grid = generate_hex_grid(resolution=res)
        save_grid(grid, f"data/hex_grid_res{res}.parquet")
        print(f"  res={res}: {len(grid)} hexes, columns={list(grid.columns)}")
