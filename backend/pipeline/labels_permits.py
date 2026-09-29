"""Build per-hex permit-issuance labels from Atlanta Open Data CSV.

Reads data/labels/atl_permits_2019_2024.csv (City of Atlanta dump, Jan
2019 – Apr 2024), filters to permits that actually progressed (issued or
beyond), aggregates to H3 res 8, and writes a labels parquet that joins
on h3_index with the rest of the feature table.

Outputs (data/labels/permits_hex.parquet):
    h3_index                              str   matches hex_grid_res8
    permits_all_count                     int   all issued+ permits 2019-2024
    permits_all_count_log                 float log1p(permits_all_count)
    permits_new_construction_count        int   new-build permits only
    permits_new_construction_count_log    float log1p(...)
    permits_recent_count                  int   issued 2022-2024 (2yr window)
    permits_recent_count_log              float log1p(...)
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd

PERMITS_CSV = Path("data/labels/atl_permits_2019_2024.csv")
HEX_GRID = Path("data/hex_grid_res8.parquet")
OUT_PATH = Path("data/labels/permits_hex.parquet")

H3_RES = 8

# Statuses that represent a permit that at least cleared review.
# Excludes "ACA Pending", "Routed for Review", "Additional Materials Required",
# etc. — these may never have been built.
ISSUED_STATUSES = {
    "Issued",
    "CO Issued",
    "Complete",
    "Completed",
    "Closed",
    "No CO Required",
    "Temp CO Issued",
}

# Permit types that represent net-new building (not renovations or demos).
NEW_CONSTRUCTION_TYPES = {
    "Residential New",
    "Multi Family New",
    "Commercial New",
    "Multi Family Land Development",
}

RECENT_WINDOW_START = pd.Timestamp("2022-01-01")


def _to_h3(lat: float, lng: float, res: int = H3_RES) -> str | None:
    if pd.isna(lat) or pd.isna(lng):
        return None
    return h3.latlng_to_cell(lat, lng, res)


def build_labels() -> pd.DataFrame:
    df = pd.read_csv(PERMITS_CSV, encoding="utf-8-sig", low_memory=False)
    df["DATE OPENED"] = pd.to_datetime(df["DATE OPENED"], errors="coerce")

    n_total = len(df)
    df = df[df["RECORD STATUS"].isin(ISSUED_STATUSES)].copy()
    n_issued = len(df)
    print(f"  permits total={n_total:,}  issued+={n_issued:,}  dropped={n_total - n_issued:,}")

    df["h3_index"] = [
        _to_h3(lat, lng) for lat, lng in zip(df["latitude"], df["longitude"])
    ]
    df = df.dropna(subset=["h3_index"])
    print(f"  geocoded to h3 res={H3_RES}: {len(df):,} permits")

    df["is_new_construction"] = df["RECORD TYPE"].isin(NEW_CONSTRUCTION_TYPES)
    df["is_recent"] = df["DATE OPENED"] >= RECENT_WINDOW_START

    agg = (
        df.groupby("h3_index")
        .agg(
            permits_all_count=("RECORD ID", "size"),
            permits_new_construction_count=("is_new_construction", "sum"),
            permits_recent_count=("is_recent", "sum"),
        )
        .reset_index()
    )

    # Reattach zero-permit hexes from the full grid so the label table
    # covers the whole study area (the model needs negatives, not just
    # the hexes that had any activity).
    grid = pd.read_parquet(HEX_GRID)[["h3_index"]]
    labels = grid.merge(agg, on="h3_index", how="left").fillna(0)

    int_cols = [
        "permits_all_count",
        "permits_new_construction_count",
        "permits_recent_count",
    ]
    labels[int_cols] = labels[int_cols].astype(int)

    for col in int_cols:
        labels[f"{col}_log"] = np.log1p(labels[col])

    print(
        f"  output: {len(labels):,} hexes  "
        f"nonzero_all={(labels['permits_all_count'] > 0).sum():,}  "
        f"nonzero_new={(labels['permits_new_construction_count'] > 0).sum():,}"
    )
    return labels


def main():
    print(f"=== Building permits labels (res {H3_RES}) ===")
    labels = build_labels()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(OUT_PATH, index=False)
    print(f"\nSaved to {OUT_PATH}")
    print("\nSummary stats:")
    print(labels.describe().to_string())


if __name__ == "__main__":
    main()
