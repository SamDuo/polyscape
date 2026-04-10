"""Merge all feature parquets, train XGBoost model, compute SHAP values.

Produces:
  data/features.parquet        — unified feature table (used by FastAPI)
  data/models/xgb_model.json   — trained XGBoost model
  data/models/shap_cache.parquet — precomputed SHAP values for all hexes
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Feature parquet files to merge (order doesn't matter, all join on h3_index)
FEATURE_FILES = [
    "data/census_hex.parquet",
    "data/overture_pois_hex.parquet",
    "data/lodes_hex.parquet",
    "data/derived_features_hex.parquet",
]

# Columns to drop from the final feature table (not model inputs)
DROP_COLS = {"geometry", "lat", "lng", "total_pop", "employed", "bachelors_degree", "households"}


def merge_features() -> pd.DataFrame:
    """Load and merge all feature parquet files on h3_index."""
    # Start with hex grid as base (ensures all hexes are present)
    base = pd.read_parquet("data/hex_grid_res8.parquet")
    base = base[["h3_index", "lat", "lng"]]

    for path_str in FEATURE_FILES:
        path = Path(path_str)
        if not path.exists():
            print(f"  Warning: {path} not found, skipping")
            continue

        df = pd.read_parquet(path)
        # Drop geometry if present (it's in the base grid)
        if "geometry" in df.columns:
            df = df.drop(columns=["geometry"])
        # Drop lat/lng if present (already in base)
        for col in ("lat", "lng"):
            if col in df.columns:
                df = df.drop(columns=[col])

        # Remove duplicate columns before merge
        existing_cols = set(base.columns) - {"h3_index"}
        new_cols = set(df.columns) - {"h3_index"}
        dupes = existing_cols & new_cols
        if dupes:
            df = df.drop(columns=list(dupes))

        base = base.merge(df, on="h3_index", how="left")
        print(f"  Merged {path.name}: {len(df)} rows, new cols: {list(new_cols - dupes)}")

    print(f"\nMerged feature table: {len(base)} hexes, {len(base.columns)} columns")
    print(f"  Columns: {list(base.columns)}")

    # Report missing data
    for col in base.columns:
        if col in ("h3_index", "lat", "lng"):
            continue
        pct_null = base[col].isna().mean() * 100
        if pct_null > 0:
            print(f"  {col}: {pct_null:.1f}% missing")

    return base


def main():
    print("=== Step 1: Merge features ===")
    features = merge_features()

    # Save features.parquet (used by FastAPI at startup)
    out_features = Path("data/features.parquet")
    features.to_parquet(out_features, index=False)
    print(f"\nSaved to {out_features}")

    print("\n=== Step 2: Train XGBoost model ===")
    from backend.model import train_model, predict, FEATURE_COLUMNS

    model = train_model(features, model_path="data/models/xgb_model.json")

    # Predict on all hexes and add scores to features
    scores = predict(model, features)
    features["score"] = scores
    print(f"\nScore stats: min={scores.min():.3f}, max={scores.max():.3f}, "
          f"mean={scores.mean():.3f}, std={scores.std():.3f}")

    # Re-save with scores
    features.to_parquet(out_features, index=False)

    print("\n=== Step 3: Compute SHAP values ===")
    from backend.explainer import compute_shap_values

    shap_df = compute_shap_values(
        model, features, cache_path="data/models/shap_cache.parquet"
    )
    print(f"SHAP cache: {len(shap_df)} hexes, {len(shap_df.columns)} columns")

    # Show top global feature importance from SHAP
    shap_cols = [c for c in shap_df.columns if c.startswith("shap_")]
    mean_abs_shap = {
        col.replace("shap_", ""): shap_df[col].abs().mean()
        for col in shap_cols
    }
    sorted_shap = sorted(mean_abs_shap.items(), key=lambda x: x[1], reverse=True)
    print("\nGlobal SHAP importance (mean |SHAP|):")
    for feat, val in sorted_shap[:10]:
        print(f"  {feat}: {val:.4f}")

    print("\n=== Done ===")
    print(f"  Features: {out_features}")
    print(f"  Model:    data/models/xgb_model.json")
    print(f"  SHAP:     data/models/shap_cache.parquet")


if __name__ == "__main__":
    main()
