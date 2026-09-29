"""Phase 0.4 — where does the tuned XGBoost actually fail?

Trains the Phase-1 tuned model (XGBoost + spatial lags, Optuna params)
on a spatial-block split and analyzes residuals on the held-out blocks.

Outputs:
    data/eval/failure_top_residuals.csv      — 30 worst predicted hexes
    data/eval/failure_by_feature_quartile.csv — residual by feature bucket
    data/eval/failure_by_spatial_block.csv    — residual by coarse block
    Plain-text summary printed to stdout

Run from polyscape repo root:
    python -m backend.eval.failure_analysis
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

from backend.eval.improve_permits import (
    BASE_FEATURES,
    LABELS_PATH,
    FEATURES_PATH,
    SPATIAL_BLOCK_RES,
    TARGET,
    add_spatial_lags,
)

# Best Optuna params from Phase 1
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


def _load() -> tuple[pd.DataFrame, list[str]]:
    features = pd.read_parquet(FEATURES_PATH)
    labels = pd.read_parquet(LABELS_PATH)
    df = features.merge(labels, on="h3_index", how="inner")
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].astype(float).fillna(df[col].median())
    df["spatial_block"] = [
        h3.cell_to_parent(h, SPATIAL_BLOCK_RES) for h in df["h3_index"]
    ]
    df, lag_cols = add_spatial_lags(df, k=1)
    return df, BASE_FEATURES + lag_cols


def main():
    out_dir = Path("data/eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== Phase 0.4 — failure analysis on tuned model ===")
    df, features = _load()
    print(f"  n={len(df):,}  features={len(features)}  blocks={df['spatial_block'].nunique()}")

    # 80/20 spatial-block split (no hex from a test block appears in train)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    tr_idx, te_idx = next(splitter.split(df, groups=df["spatial_block"]))
    train, test = df.iloc[tr_idx].copy(), df.iloc[te_idx].copy()
    print(f"  train={len(train):,} hexes ({train['spatial_block'].nunique()} blocks)")
    print(f"  test ={len(test):,} hexes ({test['spatial_block'].nunique()} blocks)")

    X_train, y_train = train[features], train[TARGET]
    X_test, y_test = test[features], test[TARGET]

    model = xgb.XGBRegressor(**BEST_PARAMS)
    model.fit(X_train, y_train)
    test["pred"] = model.predict(X_test)
    test["residual"] = test["pred"] - test[TARGET]   # +ve = overprediction
    test["abs_residual"] = test["residual"].abs()

    r2 = r2_score(y_test, test["pred"])
    mae = mean_absolute_error(y_test, test["pred"])
    print(f"\n  holdout R²={r2:.4f}  MAE={mae:.4f}")

    # --- 1. Top-30 worst residuals ---
    worst = test.nlargest(30, "abs_residual")[
        ["h3_index", "lat", "lng", TARGET, "pred", "residual",
         "median_income", "population_density", "daytime_population",
         "walk_score", "complementary_poi_count", "competitor_count"]
    ].copy()
    worst["sign"] = np.where(worst["residual"] > 0, "OVER", "UNDER")
    worst.to_csv(out_dir / "failure_top_residuals.csv", index=False)
    print(f"\n  top-30 worst residuals -> {out_dir / 'failure_top_residuals.csv'}")
    print(f"    overpredict: {(worst['residual'] > 0).sum()} / {len(worst)}")
    print(f"    underpredict: {(worst['residual'] < 0).sum()} / {len(worst)}")

    # --- 2. Residual by feature-quartile (check for systemic bias) ---
    rows = []
    for col in ["population_density", "daytime_population", "walk_score",
                "median_income", "complementary_poi_count", "competitor_count"]:
        if col not in test.columns:
            continue
        try:
            q = pd.qcut(test[col], 4, labels=False, duplicates="drop")
            q = q.map(lambda v: f"Q{int(v)+1}" if pd.notna(v) else "Q1")
        except ValueError:
            continue
        grp = test.groupby(q, observed=True).agg(
            n=("residual", "size"),
            mean_actual=(TARGET, "mean"),
            mean_pred=("pred", "mean"),
            mean_residual=("residual", "mean"),
            mae=("abs_residual", "mean"),
        ).reset_index()
        grp["feature"] = col
        rows.append(grp.rename(columns={col: "quartile"}))
    by_feat = pd.concat(rows, ignore_index=True)[
        ["feature", "quartile", "n", "mean_actual", "mean_pred", "mean_residual", "mae"]
    ]
    by_feat.to_csv(out_dir / "failure_by_feature_quartile.csv", index=False)
    print(f"\n  residual by feature quartile -> {out_dir / 'failure_by_feature_quartile.csv'}")
    print(by_feat.to_string(index=False, float_format=lambda x: f"{x:7.4f}"))

    # --- 3. Residual by spatial block ---
    by_block = test.groupby("spatial_block").agg(
        n=("residual", "size"),
        mean_actual=(TARGET, "mean"),
        mean_pred=("pred", "mean"),
        mean_residual=("residual", "mean"),
        mae=("abs_residual", "mean"),
        lat=("lat", "mean"),
        lng=("lng", "mean"),
    ).reset_index().sort_values("mae", ascending=False)
    by_block.to_csv(out_dir / "failure_by_spatial_block.csv", index=False)
    print(f"\n  residual by spatial block -> {out_dir / 'failure_by_spatial_block.csv'}")
    print(f"  worst 5 blocks by MAE:")
    print(by_block.head(5)[["spatial_block", "n", "mean_actual", "mean_pred", "mae", "lat", "lng"]].to_string(index=False, float_format=lambda x: f"{x:7.4f}"))

    # --- 4. Quartile confusion (do we get the hot hexes right?) ---
    def _qbucket(s):
        q = pd.qcut(s, 4, labels=False, duplicates="drop")
        return q.map(lambda v: f"Q{int(v)+1}" if pd.notna(v) else "Q1")

    test["actual_q"] = _qbucket(test[TARGET])
    test["pred_q"] = _qbucket(test["pred"])
    confusion = pd.crosstab(test["actual_q"], test["pred_q"], margins=True, margins_name="total")
    print(f"\n  actual vs predicted quartile (test set):")
    print(confusion.to_string())

    # Diagonal hit rate
    diag = sum(confusion.loc[q, q] for q in ["Q1", "Q2", "Q3", "Q4"] if q in confusion.index and q in confusion.columns)
    total = confusion.loc["total", "total"]
    print(f"\n  diagonal hit rate (correct quartile): {diag}/{total} = {diag/total:.1%}")

    # Q4 (true hot) → predicted Q? Where do real winners end up?
    if "Q4" in confusion.index:
        q4_row = confusion.loc["Q4"]
        q4_correct = q4_row.get("Q4", 0)
        q4_total = q4_row.get("total", 0)
        print(f"  of true Q4 (hot) hexes: predicted Q4 = {q4_correct}/{q4_total} = {q4_correct/q4_total:.1%}")


if __name__ == "__main__":
    main()
