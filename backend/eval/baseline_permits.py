"""Phase 0.2 + 0.3 — Baseline benchmarks on the permits label.

Joins data/features.parquet to data/labels/permits_hex.parquet on h3_index,
trains three models on log-permit-count targets, and reports random-CV
versus spatial-CV metrics. The gap quantifies how much the model is
memorizing geography vs learning a transferable pattern.

Run from polyscape repo root:
    python -m backend.eval.baseline_permits
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, GroupKFold

FEATURES_PATH = Path("data/features.parquet")
LABELS_PATH = Path("data/labels/permits_hex.parquet")

FEATURE_COLUMNS = [
    "median_income",
    "population_density",
    "pct_age_25_44",
    "employment_rate",
    "daytime_population",
    "commute_inflow",
    "competitor_count",
    "complementary_poi_count",
    "walk_score",
    "transit_proximity",
    "road_density",
    "median_rent",
    "household_density",
    "land_use_mix",
]

# Targets we'll evaluate. Each is a log-count to tame the right tail.
TARGETS = [
    "permits_all_count_log",
    "permits_new_construction_count_log",
    "permits_recent_count_log",
]

# Coarse H3 resolution for spatial blocking. Res 6 gives ~36 km² blocks —
# coarse enough to break local spatial correlation, fine enough that each
# fold still has enough training data.
SPATIAL_BLOCK_RES = 6

N_SPLITS = 5
RANDOM_STATE = 42


def load_data() -> pd.DataFrame:
    features = pd.read_parquet(FEATURES_PATH)
    labels = pd.read_parquet(LABELS_PATH)
    df = features.merge(labels, on="h3_index", how="inner")

    # Fill missing features with column medians (matches model.py convention)
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].astype(float).fillna(df[col].median())

    # Spatial block: coarse hex ID used to group hexes that are
    # geographically near each other into the same CV fold.
    df["spatial_block"] = [
        h3.cell_to_parent(h, SPATIAL_BLOCK_RES) for h in df["h3_index"]
    ]
    return df


def _models() -> dict:
    return {
        "naive_mean": DummyRegressor(strategy="mean"),
        "ridge_linear": Ridge(alpha=1.0, random_state=RANDOM_STATE),
        "xgboost": xgb.XGBRegressor(
            max_depth=6,
            n_estimators=400,
            learning_rate=0.05,
            objective="reg:squarederror",
            tree_method="hist",
            random_state=RANDOM_STATE,
            n_jobs=-1,
            verbosity=0,
        ),
    }


def _cv_score(X, y, groups, splitter, name: str) -> dict:
    rows = []
    for model_name, model in _models().items():
        maes, rmses, r2s = [], [], []
        for tr, te in splitter.split(X, y, groups=groups) if groups is not None else splitter.split(X, y):
            m = model.__class__(**model.get_params()) if model_name != "naive_mean" else DummyRegressor(strategy="mean")
            m.fit(X.iloc[tr], y.iloc[tr])
            pred = m.predict(X.iloc[te])
            maes.append(mean_absolute_error(y.iloc[te], pred))
            rmses.append(np.sqrt(mean_squared_error(y.iloc[te], pred)))
            r2s.append(r2_score(y.iloc[te], pred))
        rows.append(
            {
                "cv": name,
                "model": model_name,
                "mae": float(np.mean(maes)),
                "rmse": float(np.mean(rmses)),
                "r2": float(np.mean(r2s)),
                "r2_std": float(np.std(r2s)),
            }
        )
    return rows


def evaluate_target(df: pd.DataFrame, target: str) -> pd.DataFrame:
    print(f"\n=== Target: {target} ===")
    X = df[FEATURE_COLUMNS]
    y = df[target]
    print(
        f"  n={len(df):,}  mean={y.mean():.3f}  std={y.std():.3f}  "
        f"nonzero={(y > 0).sum():,} ({(y > 0).mean() * 100:.1f}%)"
    )

    rows = []
    rows += _cv_score(
        X,
        y,
        groups=None,
        splitter=KFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE),
        name="random_kfold",
    )
    rows += _cv_score(
        X,
        y,
        groups=df["spatial_block"],
        splitter=GroupKFold(n_splits=N_SPLITS),
        name=f"spatial_block_res{SPATIAL_BLOCK_RES}",
    )

    results = pd.DataFrame(rows)
    print(results.to_string(index=False, float_format=lambda x: f"{x:7.4f}"))
    return results


def main():
    print("=== Phase 0.2 + 0.3 — Baseline + Spatial CV on permits labels ===")
    df = load_data()
    print(f"Loaded {len(df):,} hexes  ({df['spatial_block'].nunique()} spatial blocks at res {SPATIAL_BLOCK_RES})")

    all_results = []
    for target in TARGETS:
        all_results.append(evaluate_target(df, target))

    out = pd.concat(all_results, keys=TARGETS, names=["target", "row"]).reset_index(level=1, drop=True).reset_index()
    out_path = Path("data/eval/baseline_permits_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
