"""Build per-hex POI churn labels from Overture's GERS changelog.

Uses the Overture changelog to find places that were ADDED or MODIFIED
in the current release vs prior history within the Atlanta bbox, then
joins those IDs to the current places snapshot to get coordinates, and
aggregates to H3 res 8.

Outputs (data/labels/poi_openings_hex.parquet):
    h3_index                            str   matches hex_grid_res8
    new_openings_count                  int   total new POIs in hex
    new_openings_count_log              float log1p(...)
    new_food_openings_count             int   restaurants + cafes + bars
    new_retail_openings_count           int   shops + retail + entertainment
    modified_poi_count                  int   POIs with any change record
    modified_poi_count_log              float log1p(...)
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc
from pyarrow import fs

from overturemaps import core
from overturemaps.changelog import query_changelog_ids

from backend.pipeline.overture import (
    ATLANTA_BBOX,
    COMPETITOR_CATEGORIES,
    COMPLEMENTARY_CATEGORIES,
)

HEX_GRID = Path("data/hex_grid_res8.parquet")
OUT_PATH = Path("data/labels/poi_openings_hex.parquet")
SNAPSHOT_PATH = Path("data/labels/poi_added_snapshot.parquet")

H3_RES = 8


def _bbox_obj():
    return core.BBox(
        xmin=ATLANTA_BBOX[0],
        ymin=ATLANTA_BBOX[1],
        xmax=ATLANTA_BBOX[2],
        ymax=ATLANTA_BBOX[3],
    )


def _classify(category: str) -> str:
    c = (category or "").lower().strip()
    if any(k in c for k in COMPETITOR_CATEGORIES):
        return "food"
    if any(k in c for k in COMPLEMENTARY_CATEGORIES):
        return "retail"
    return "other"


def fetch_changed_pois(release: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Get IDs of POIs added + modified in this release within Atlanta bbox,
    then join back to current places dataset for coordinates + categories.
    Returns (added_df, modified_df)."""
    bbox = _bbox_obj()
    print(f"  querying changelog for release {release}...")
    change_ids = query_changelog_ids(release, "places", "place", bbox)
    added = change_ids.get("added", set())
    # Overture's raw change_type for modifications is "data_changed"
    # (the CLI summary displays it as "Modified" but the parquet value
    # is "data_changed"). "unchanged" + "removed" are also keys we ignore.
    modified = change_ids.get("data_changed", set()) | change_ids.get("modified", set())
    print(f"  added IDs: {len(added):,}  modified IDs: {len(modified):,}")

    if not added and not modified:
        empty = pd.DataFrame(columns=["id", "lat", "lng", "category"])
        return empty, empty.copy()

    of_interest = added | modified
    print(f"  loading current places snapshot to resolve coords for {len(of_interest):,} POIs...")
    records_added, records_modified = [], []
    reader = core.record_batch_reader("place", bbox=ATLANTA_BBOX)
    from shapely import wkb

    for batch in reader:
        tbl = batch.to_pydict()
        n = len(tbl.get("id", []))
        ids = tbl["id"]
        cats = tbl.get("categories", [None] * n)
        geoms = tbl.get("geometry", [None] * n)
        for i in range(n):
            pid = ids[i]
            if pid not in of_interest:
                continue
            cat = ""
            ce = cats[i]
            if isinstance(ce, dict):
                cat = ce.get("primary", "") or ""
            elif isinstance(ce, str):
                cat = ce
            raw = geoms[i]
            if not raw:
                continue
            try:
                geom = wkb.loads(raw) if isinstance(raw, bytes) else None
            except Exception:
                geom = None
            if geom is None or geom.is_empty:
                continue
            rec = {"id": pid, "lat": geom.y, "lng": geom.x, "category": cat}
            if pid in added:
                records_added.append(rec)
            else:
                records_modified.append(rec)

    df_a = pd.DataFrame(records_added)
    df_m = pd.DataFrame(records_modified)
    print(f"  resolved coords for added={len(df_a):,}/{len(added):,}  modified={len(df_m):,}/{len(modified):,}")
    return df_a, df_m


def main():
    print("=== Building POI openings + churn labels ===")
    release = core.get_latest_release()
    print(f"  latest release: {release}")

    added, modified = fetch_changed_pois(release)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    added.to_parquet(SNAPSHOT_PATH, index=False)
    modified.to_parquet(SNAPSHOT_PATH.with_name("poi_modified_snapshot.parquet"), index=False)

    if added.empty and modified.empty:
        print("  no changed POIs; nothing to label.")
        return

    grid = pd.read_parquet(HEX_GRID)[["h3_index"]]

    def _hex_counts(df: pd.DataFrame, count_col: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame({"h3_index": [], count_col: []})
        df = df.copy()
        df["h3_index"] = [
            h3.latlng_to_cell(lat, lng, H3_RES)
            for lat, lng in zip(df["lat"], df["lng"])
        ]
        return df.groupby("h3_index").size().rename(count_col).reset_index()

    added["bucket"] = added["category"].apply(_classify) if not added.empty else []
    added["h3_index"] = [
        h3.latlng_to_cell(lat, lng, H3_RES) for lat, lng in zip(added["lat"], added["lng"])
    ] if not added.empty else []

    by_hex_added = added.groupby("h3_index").agg(
        new_openings_count=("id", "size"),
        new_food_openings_count=("bucket", lambda s: (s == "food").sum()),
        new_retail_openings_count=("bucket", lambda s: (s == "retail").sum()),
    ).reset_index() if not added.empty else pd.DataFrame(columns=["h3_index", "new_openings_count", "new_food_openings_count", "new_retail_openings_count"])

    by_hex_modified = _hex_counts(modified, "modified_poi_count")

    labels = grid.merge(by_hex_added, on="h3_index", how="left")\
                 .merge(by_hex_modified, on="h3_index", how="left").fillna(0)
    int_cols = [
        "new_openings_count",
        "new_food_openings_count",
        "new_retail_openings_count",
        "modified_poi_count",
    ]
    labels[int_cols] = labels[int_cols].astype(int)
    labels["new_openings_count_log"] = np.log1p(labels["new_openings_count"])
    labels["modified_poi_count_log"] = np.log1p(labels["modified_poi_count"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(OUT_PATH, index=False)
    print(
        f"\n  output: {len(labels):,} hexes  "
        f"nonzero_added={(labels['new_openings_count'] > 0).sum():,}  "
        f"nonzero_modified={(labels['modified_poi_count'] > 0).sum():,}"
    )
    print(f"  saved -> {OUT_PATH}")
    print(labels[int_cols + ["new_openings_count_log", "modified_poi_count_log"]].describe().to_string())


if __name__ == "__main__":
    main()
