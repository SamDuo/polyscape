"""Phase 1 — push XGBoost spatial-CV R² above the baseline.

Layered ablation on top of backend/eval/baseline_permits.py results:
    base                 = 14 features as-is (baseline already reported)
    + spatial_lags       = + mean of each feature over k-ring neighbors (k=1)
    + interactions       = + walk*income, transit*daytime, walk*transit
    + both               = lags AND interactions

Then runs Optuna tuning on the best variant (spatial-CV scored) and
finishes with a LightGBM shoot-out for sanity.

Target: permits_new_construction_count_log (chosen for interpretability).

Run from polyscape repo root:
    python -m backend.eval.improve_permits
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold

FEATURES_PATH = Path("data/features.parquet")
LABELS_PATH = Path("data/labels/permits_hex.parquet")

BASE_FEATURES = [
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

INTERACTIONS = [
    ("walk_score", "median_income"),
    ("transit_proximity", "daytime_population"),
    ("walk_score", "transit_proximity"),
    ("population_density", "complementary_poi_count"),
]

TARGET = "permits_new_construction_count_log"
SPATIAL_BLOCK_RES = 6
N_SPLITS = 5
RANDOM_STATE = 42


def _load() -> pd.DataFrame:
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
    return df


def add_spatial_lags(df: pd.DataFrame, k: int = 1) -> tuple[pd.DataFrame, list[str]]:
    """For each base feature, add a column = mean over k-ring neighbors (excluding self)."""
    h_to_idx = {h: i for i, h in enumerate(df["h3_index"])}
    feat_vals = df[BASE_FEATURES].to_numpy()
    n = len(df)
    out = np.zeros((n, len(BASE_FEATURES)))

    for i, h in enumerate(df["h3_index"]):
        ring = set(h3.grid_disk(h, k))
        ring.discard(h)
        idxs = [h_to_idx[r] for r in ring if r in h_to_idx]
        if idxs:
            out[i] = feat_vals[idxs].mean(axis=0)
        else:
            out[i] = feat_vals[i]  # isolated hex: fall back to self

    new_cols = [f"{c}_lag{k}" for c in BASE_FEATURES]
    lag_df = pd.DataFrame(out, columns=new_cols, index=df.index)
    return pd.concat([df, lag_df], axis=1), new_cols


def add_interactions(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    new_cols = []
    for a, b in INTERACTIONS:
        col = f"{a}__x__{b}"
        df[col] = df[a] * df[b]
        new_cols.append(col)
    return df, new_cols


def _xgb_params(overrides: dict | None = None) -> dict:
    p = dict(
        max_depth=6,
        n_estimators=400,
        learning_rate=0.05,
        objective="reg:squarederror",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbosity=0,
    )
    if overrides:
        p.update(overrides)
    return p


def spatial_cv(df: pd.DataFrame, features: list[str], target: str, params: dict | None = None, model_kind: str = "xgb") -> dict:
    X = df[features]
    y = df[target]
    groups = df["spatial_block"]
    gkf = GroupKFold(n_splits=N_SPLITS)
    maes, rmses, r2s = [], [], []
    for tr, te in gkf.split(X, y, groups=groups):
        if model_kind == "xgb":
            m = xgb.XGBRegressor(**_xgb_params(params))
        elif model_kind == "lgbm":
            import lightgbm as lgb
            m = lgb.LGBMRegressor(
                random_state=RANDOM_STATE,
                n_jobs=-1,
                verbosity=-1,
                **(params or {}),
            )
        else:
            raise ValueError(model_kind)
        m.fit(X.iloc[tr], y.iloc[tr])
        pred = m.predict(X.iloc[te])
        maes.append(mean_absolute_error(y.iloc[te], pred))
        rmses.append(np.sqrt(mean_squared_error(y.iloc[te], pred)))
        r2s.append(r2_score(y.iloc[te], pred))
    return {
        "mae": float(np.mean(maes)),
        "rmse": float(np.mean(rmses)),
        "r2": float(np.mean(r2s)),
        "r2_std": float(np.std(r2s)),
    }


def main():
    print(f"=== Phase 1 ablation on {TARGET} (spatial CV, res {SPATIAL_BLOCK_RES} blocks) ===")
    df = _load()
    print(f"  n={len(df):,}  blocks={df['spatial_block'].nunique()}")

    df_lag, lag_cols = add_spatial_lags(df, k=1)
    df_lag_int, int_cols = add_interactions(df_lag.copy())

    runs = [
        ("base (14 features)", BASE_FEATURES),
        ("+ spatial_lags_k1", BASE_FEATURES + lag_cols),
        ("+ interactions", BASE_FEATURES + int_cols),
        ("+ both", BASE_FEATURES + lag_cols + int_cols),
    ]

    rows = []
    for name, features in runs:
        # Use df_lag_int as superset — it has all engineered columns
        r = spatial_cv(df_lag_int, features, TARGET, params=None, model_kind="xgb")
        rows.append({"variant": name, "n_features": len(features), **r})
        print(f"  {name:>22}  R²={r['r2']:+.4f} ± {r['r2_std']:.3f}  MAE={r['mae']:.4f}  RMSE={r['rmse']:.4f}")

    ablation = pd.DataFrame(rows)
    out_dir = Path("data/eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    ablation.to_csv(out_dir / "improve_permits_ablation.csv", index=False)
    print(f"\n  saved ablation -> {out_dir / 'improve_permits_ablation.csv'}")

    # Pick best variant for downstream tuning
    best = ablation.iloc[ablation["r2"].idxmax()]
    print(f"\n  best variant: {best['variant']}  R²={best['r2']:.4f}")
    best_features = runs[ablation["r2"].idxmax()][1]

    # Optuna tuning under spatial CV
    print(f"\n=== Optuna tuning on best variant (40 trials, spatial CV) ===")
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = dict(
                max_depth=trial.suggest_int("max_depth", 3, 10),
                n_estimators=trial.suggest_int("n_estimators", 100, 800, step=50),
                learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                subsample=trial.suggest_float("subsample", 0.6, 1.0),
                colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
                min_child_weight=trial.suggest_int("min_child_weight", 1, 10),
                reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 1.0, log=True),
                reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 5.0, log=True),
            )
            r = spatial_cv(df_lag_int, best_features, TARGET, params=params)
            return r["r2"]

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE))
        study.optimize(objective, n_trials=40, show_progress_bar=False)
        print(f"  best Optuna R² (spatial): {study.best_value:.4f}")
        print(f"  best params: {study.best_params}")
        tuned = spatial_cv(df_lag_int, best_features, TARGET, params=study.best_params)
        print(f"  retuned holdout: R²={tuned['r2']:.4f}  MAE={tuned['mae']:.4f}  RMSE={tuned['rmse']:.4f}")
    except ImportError:
        print("  optuna not installed; skipping. pip install optuna")
        study = None

    # LightGBM shoot-out
    print(f"\n=== LightGBM on best variant (default params) ===")
    try:
        lgb_r = spatial_cv(df_lag_int, best_features, TARGET, params={"n_estimators": 500, "learning_rate": 0.05}, model_kind="lgbm")
        print(f"  LightGBM: R²={lgb_r['r2']:+.4f} ± {lgb_r['r2_std']:.3f}  MAE={lgb_r['mae']:.4f}")
    except ImportError:
        print("  lightgbm not installed; skipping. pip install lightgbm")


if __name__ == "__main__":
    main()
