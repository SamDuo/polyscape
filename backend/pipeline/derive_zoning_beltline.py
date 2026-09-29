"""Derive zoning indicators + BeltLine distance per H3 hex.

Inputs:
    data/hex_grid_res8.parquet                       (8,234 hexes)
    data/features_extra/zoning_districts.geojson     (2,971 polygons)
    data/features_extra/beltline.geojson             (18 polylines)

Outputs:
    data/features_extra/zoning_beltline_hex.parquet
      h3_index
      zoning_spi_flag        — 1 if hex centroid in any SPI district
      zoning_mixed_use_flag  — 1 if MRC* / MR-* / MR (mixed-residential)
      zoning_commercial_flag — 1 if C-*
      zoning_industrial_flag — 1 if I-*
      zoning_pud_flag        — 1 if PD-*
      zoning_residential_high_flag — 1 if RG-*, R-4A, R-5
      beltline_distance_m    — min distance from centroid to nearest BeltLine line (meters)
      beltline_proximity_log — log1p(1/(1+distance_km)) for an inverted-distance feature

Run:
    python -m backend.pipeline.derive_zoning_beltline
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

HEX_GRID = Path("data/hex_grid_res8.parquet")
ZONING_GEOJSON = Path("data/features_extra/zoning_districts.geojson")
BELTLINE_GEOJSON = Path("data/features_extra/beltline.geojson")
OUT_PATH = Path("data/features_extra/zoning_beltline_hex.parquet")

# Regex patterns for zoning class buckets (matched against ZONECLASS)
PATTERNS = {
    "zoning_spi_flag": re.compile(r"^SPI", re.I),
    "zoning_mixed_use_flag": re.compile(r"^(MRC|MR-|MR$|LW)", re.I),
    "zoning_commercial_flag": re.compile(r"^C-", re.I),
    "zoning_industrial_flag": re.compile(r"^I-", re.I),
    "zoning_pud_flag": re.compile(r"^PD-", re.I),
    "zoning_residential_high_flag": re.compile(r"^(RG-|R-4A|R-5)", re.I),
}


def load_zoning() -> tuple[STRtree, list[str]]:
    g = json.load(open(ZONING_GEOJSON))
    geoms, classes = [], []
    for feat in g["features"]:
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        zc = (feat["properties"].get("ZONECLASS") or "").strip()
        geoms.append(geom)
        classes.append(zc)
    tree = STRtree(geoms)
    print(f"  loaded {len(geoms):,} zoning polygons")
    return tree, geoms, classes


def load_beltline_metric():
    """Return BeltLine geometries reprojected to EPSG:3857 (web mercator,
    meters) for distance computation."""
    g = json.load(open(BELTLINE_GEOJSON))
    transformer = Transformer.from_crs(4326, 3857, always_xy=True)
    lines = []
    for feat in g["features"]:
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        # Reproject each coordinate
        def project_coords(coords):
            return [transformer.transform(x, y) for x, y in coords]

        if geom.geom_type == "LineString":
            from shapely.geometry import LineString
            lines.append(LineString(project_coords(list(geom.coords))))
        elif geom.geom_type == "MultiLineString":
            from shapely.geometry import LineString
            for line in geom.geoms:
                lines.append(LineString(project_coords(list(line.coords))))
    tree = STRtree(lines)
    print(f"  loaded {len(lines):,} BeltLine line segments")
    return tree, lines, transformer


def main():
    print("=== Deriving zoning + BeltLine features ===")
    grid = pd.read_parquet(HEX_GRID)[["h3_index", "lat", "lng"]]
    print(f"  {len(grid):,} hexes")

    tree_zoning, zoning_geoms, zoning_classes = load_zoning()
    tree_beltline, beltline_lines, transformer = load_beltline_metric()

    rows = []
    for _, r in grid.iterrows():
        pt = Point(r["lng"], r["lat"])
        # Find which zoning polygon contains this point (might be multiple due to overlaps)
        candidates = tree_zoning.query(pt)
        # tree.query returns indices in shapely 2.x
        zone_class = ""
        for idx in candidates:
            if zoning_geoms[idx].contains(pt):
                zone_class = zoning_classes[idx]
                break

        flags = {key: int(bool(pat.match(zone_class))) for key, pat in PATTERNS.items()}

        # BeltLine distance (projected to meters)
        x_m, y_m = transformer.transform(r["lng"], r["lat"])
        pt_m = Point(x_m, y_m)
        # Query nearest line
        nearest_idx = tree_beltline.nearest(pt_m)
        dist_m = pt_m.distance(beltline_lines[nearest_idx])
        # Inverted-distance proximity (more useful for the model than raw distance)
        proximity_log = np.log1p(1.0 / (1.0 + dist_m / 1000.0))  # km

        rows.append({
            "h3_index": r["h3_index"],
            **flags,
            "zone_class": zone_class,
            "beltline_distance_m": dist_m,
            "beltline_proximity_log": proximity_log,
        })

    out = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.drop(columns=["zone_class"]).to_parquet(OUT_PATH, index=False)
    print(f"\n  saved -> {OUT_PATH}")
    print(out.drop(columns=["h3_index", "zone_class"]).describe().to_string())
    print()
    print(f"  zone_class top 10:")
    print(out["zone_class"].value_counts().head(10).to_string())
    print()
    flag_cols = list(PATTERNS.keys())
    print(f"  hexes per flag: {out[flag_cols].sum().to_dict()}")


if __name__ == "__main__":
    main()
