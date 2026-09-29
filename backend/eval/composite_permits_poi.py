"""Composite-label evaluation: permits + POI openings rank-averaged.

Compares the tuned XGBoost (Phase 1 params + spatial lags) on three
targets to decide which the production model should use:
  1. permits_new_construction_count_log (Phase 0/1 baseline)
  2. poi_openings_count_log              (new label alone)
  3. composite = rank-avg(permits_log, poi_log)  ∈ [0, 1]

Run from polyscape repo root:
    python -m backend.eval.composite_permits_poi
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


def load_data() -> tuple[pd.DataFrame, list[str]]:
    features = pd.read_parquet(FEATURES_PATH)
    permits = pd.read_parquet(PERMITS_LABELS)
    pois = pd.read_parquet(POI_LABELS)
    df = features.merge(permits, on="h3_index", how="inner").merge(
        pois, on="h3_index", how="inner"
    )
    for c in BASE_FEATURES:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = df[c].astype(float).fillna(df[c].median())
    df["spatial_block"] = [
        h3.cell_to_parent(h, SPATIAL_BLOCK_RES) for h in df["h3_index"]
    ]

    # Composites (rank-averaged, scaled to [0, 1])
    df["rank_permits"] = df["permits_new_construction_count_log"].rank(method="average") / len(df)
    df["rank_pois"] = df["new_openings_count_log"].rank(method="average") / len(df)
    df["rank_mod"] = df["modified_poi_count_log"].rank(method="average") / len(df)
    df["composite"] = (df["rank_permits"] + df["rank_pois"]) / 2.0
    df["composite_3"] = (df["rank_permits"] + df["rank_pois"] + df["rank_mod"]) / 3.0

    df, lag_cols = add_spatial_lags(df, k=1)
    return df, BASE_FEATURES + lag_cols


def evaluate(df: pd.DataFrame, features: list[str], target: str) -> dict:
    X, y = df[features], df[target]
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
        "target": target,
        "mae": float(np.mean(maes)),
        "rmse": float(np.mean(rmses)),
        "r2": float(np.mean(r2s)),
        "r2_std": float(np.std(r2s)),
        "spearman": float(np.mean(rhos)),
    }


def main():
    print("=== Composite target evaluation ===")
    df, features = load_data()
    print(f"  n={len(df):,}  features={len(features)}  blocks={df['spatial_block'].nunique()}")

    # Pairwise label correlations
    cols = [
        ("permits", "permits_new_construction_count_log"),
        ("pois_added", "new_openings_count_log"),
        ("pois_modified", "modified_poi_count_log"),
    ]
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            (a, ac), (b, bc) = cols[i], cols[j]
            rho, _ = spearmanr(df[ac], df[bc])
            print(f"  Spearman({a:>14}, {b:>14}) = {rho:+.3f}")

    # Correlation of pois_modified with existing complementary_poi_count feature
    rho_redund, _ = spearmanr(df["modified_poi_count_log"], df["complementary_poi_count"] + df["competitor_count"])
    print(f"  Spearman(pois_modified, complementary+competitor count) = {rho_redund:+.3f}   <- redundancy check")

    rows = []
    for target in [
        "permits_new_construction_count_log",
        "new_openings_count_log",
        "modified_poi_count_log",
        "composite",
        "composite_3",
    ]:
        r = evaluate(df, features, target)
        rows.append(r)
        print(
            f"  {target:>40}  R²={r['r2']:+.4f} ± {r['r2_std']:.3f}  "
            f"MAE={r['mae']:.4f}  Spearman={r['spearman']:+.3f}"
        )

    out = pd.DataFrame(rows)
    out_path = Path("data/eval/composite_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"\n  saved -> {out_path}")

    # Top-decile precision on holdout for each composite
    sp = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    tr, te = next(sp.split(df, groups=df["spatial_block"]))
    for target in ["composite", "composite_3"]:
        m = xgb.XGBRegressor(**BEST_PARAMS)
        m.fit(df.iloc[tr][features], df.iloc[tr][target])
        test = df.iloc[te].copy()
        test["pred"] = m.predict(test[features])
        n = len(test)
        k = int(n * 0.10)
        pred_top = set(test.nlargest(k, "pred")["h3_index"])
        actual_top = set(test.nlargest(k, target)["h3_index"])
        precision = len(pred_top & actual_top) / k
        print(f"  {target} top-10% precision (spatial holdout): {len(pred_top & actual_top)}/{k} = {precision:.1%}")


if __name__ == "__main__":
    main()
