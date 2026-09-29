"""Final v2 evaluation — 2-label composite target with modified-POI count
promoted from label to feature.

Compares:
  A. Baseline (Phase 1 best): 14 base features + spatial lags, target = 2-label composite
  B. +modified_poi: 15 base features (adds modified_poi_count_log) + spatial lags, same target

If B materially beats A, the production model uses the 15-feature set.
If not, the modified-POI signal was tautological even when reframed as a
feature, and we ship the 14-feature model.

Run from polyscape repo root:
    python -m backend.eval.final_v2
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from backend.eval.improve_permits import (
    BASE_FEATURES,
    FEATURES_PATH,
    LABELS_PATH as PERMITS_LABELS,
    SPATIAL_BLOCK_RES,
    add_spatial_lags,
)

POI_LABELS = Path("data/labels/poi_openings_hex.parquet")
ZONING_BELTLINE = Path("data/features_extra/zoning_beltline_hex.parquet")

EXTRA_FEATURES = [
    "modified_poi_count_log",
    "beltline_distance_m",
    "beltline_proximity_log",
]

BEST_PARAMS = {
    "max_depth": 4,
    "n_estimators": 250,
    "learning_rate": 0.010427814680514964,
    "subsample": 0.743407556544269,
    "colsample_bytree": 0.632823121820934,
    "min_child_weight": 7,
    "reg_alpha": 0.021650549253316182,
    "reg_lambda": 0.16738652916776128,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": 0,
}

N_SPLITS = 5
RANDOM_STATE = 42
TARGET = "composite"


def load_data(extended_features: bool) -> tuple[pd.DataFrame, list[str]]:
    features = pd.read_parquet(FEATURES_PATH)
    permits = pd.read_parquet(PERMITS_LABELS)
    pois = pd.read_parquet(POI_LABELS)
    zb = pd.read_parquet(ZONING_BELTLINE)
    df = (
        features.merge(permits, on="h3_index", how="inner")
        .merge(pois, on="h3_index", how="inner")
        .merge(zb, on="h3_index", how="left")
    )

    feature_cols = list(BASE_FEATURES)
    if extended_features:
        feature_cols.extend(EXTRA_FEATURES)
    for c in feature_cols:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = df[c].astype(float).fillna(df[c].median())

    df["spatial_block"] = [
        h3.cell_to_parent(h, SPATIAL_BLOCK_RES) for h in df["h3_index"]
    ]

    # 2-label composite (permits + added POIs, no modified) ∈ [0, 1]
    df["rank_permits"] = df["permits_new_construction_count_log"].rank(method="average") / len(df)
    df["rank_pois"] = df["new_openings_count_log"].rank(method="average") / len(df)
    df["composite"] = (df["rank_permits"] + df["rank_pois"]) / 2.0

    # Patch add_spatial_lags to use the requested feature_cols
    h_to_idx = {h: i for i, h in enumerate(df["h3_index"])}
    feat_vals = df[feature_cols].to_numpy()
    n = len(df)
    out = np.zeros((n, len(feature_cols)))
    for i, h in enumerate(df["h3_index"]):
        ring = set(h3.grid_disk(h, 1))
        ring.discard(h)
        idxs = [h_to_idx[r] for r in ring if r in h_to_idx]
        out[i] = feat_vals[idxs].mean(axis=0) if idxs else feat_vals[i]
    lag_cols = [f"{c}_lag1" for c in feature_cols]
    lag_df = pd.DataFrame(out, columns=lag_cols, index=df.index)
    df = pd.concat([df, lag_df], axis=1)
    return df, feature_cols + lag_cols


def cv_score(df: pd.DataFrame, features: list[str]) -> dict:
    X, y = df[features], df[TARGET]
    gkf = GroupKFold(n_splits=N_SPLITS)
    maes, rmses, r2s, rhos = [], [], [], []
    for tr, te in gkf.split(X, y, groups=df["spatial_block"]):
        m = xgb.XGBRegressor(**BEST_PARAMS)
        m.fit(X.iloc[tr], y.iloc[tr])
        pred = m.predict(X.iloc[te])
        maes.append(mean_absolute_error(y.iloc[te], pred))
        rmses.append(np.sqrt(mean_squared_error(y.iloc[te], pred)))
        r2s.append(r2_score(y.iloc[te], pred))
        rho, _ = spearmanr(y.iloc[te], pred)
        rhos.append(rho)
    return {
        "mae": float(np.mean(maes)),
        "rmse": float(np.mean(rmses)),
        "r2": float(np.mean(r2s)),
        "r2_std": float(np.std(r2s)),
        "spearman": float(np.mean(rhos)),
    }


def top_decile_precision(df: pd.DataFrame, features: list[str]) -> tuple[int, int]:
    sp = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    tr, te = next(sp.split(df, groups=df["spatial_block"]))
    m = xgb.XGBRegressor(**BEST_PARAMS)
    m.fit(df.iloc[tr][features], df.iloc[tr][TARGET])
    test = df.iloc[te].copy()
    test["pred"] = m.predict(test[features])
    n = len(test)
    k = int(n * 0.10)
    pred_top = set(test.nlargest(k, "pred")["h3_index"])
    actual_top = set(test.nlargest(k, TARGET)["h3_index"])
    return len(pred_top & actual_top), k


def main():
    print(f"=== Final v2: 2-label composite, modified-POI feature ablation ===")
    print(f"  target: {TARGET} (rank-avg of permits_new_construction + new_openings)\n")

    for label, extended in [("A: 14 base features (Phase 1 best)", False), ("B: +modified_poi +zoning +beltline", True)]:
        df, features = load_data(extended_features=extended)
        r = cv_score(df, features)
        hits, k = top_decile_precision(df, features)
        print(f"  {label}")
        print(f"    n_features={len(features):<3}  R²={r['r2']:+.4f} ± {r['r2_std']:.3f}  MAE={r['mae']:.4f}  Spearman={r['spearman']:+.3f}")
        print(f"    top-10% precision: {hits}/{k} = {hits/k:.1%}\n")

    # Feature importance for the extended-feature model
    df, features = load_data(extended_features=True)
    m = xgb.XGBRegressor(**BEST_PARAMS)
    m.fit(df[features], df[TARGET])
    fi = pd.Series(m.feature_importances_, index=features).sort_values(ascending=False)
    print(f"  Feature importance (top 10, model B):")
    for name, val in fi.head(10).items():
        print(f"    {name:<40} {val:.4f}")


if __name__ == "__main__":
    main()
