"""Train the production XGBoost model + precompute SHAP cache.

Loads features + labels + extra features, builds the 17-feature + 17-lag
table, computes the 2-label composite target, trains XGBoost on the full
dataset (no holdout — final fit), and writes:

    data/models/xgb_v2.json              — model artifact
    data/models/shap_cache.parquet       — per-hex SHAP values for all features
    data/models/model_card.json          — version, metrics, feature list

Run from polyscape repo root:
    python -m backend.train_production
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xgboost as xgb

from backend.eval.final_v2 import (
    BASE_FEATURES,
    BEST_PARAMS,
    EXTRA_FEATURES,
    FEATURES_PATH,
    PERMITS_LABELS,
    POI_LABELS,
    ZONING_BELTLINE,
)

OUT_DIR = Path("data/models")
MODEL_PATH = OUT_DIR / "xgb_v2.json"
SHAP_PATH = OUT_DIR / "shap_cache.parquet"
CARD_PATH = OUT_DIR / "model_card.json"

MODEL_VERSION = "v2-2026-05-20"
TARGET = "composite"


def build_dataset() -> tuple[pd.DataFrame, list[str]]:
    features = pd.read_parquet(FEATURES_PATH)
    permits = pd.read_parquet(PERMITS_LABELS)
    pois = pd.read_parquet(POI_LABELS)
    zb = pd.read_parquet(ZONING_BELTLINE)
    df = (
        features.merge(permits, on="h3_index", how="inner")
        .merge(pois, on="h3_index", how="inner")
        .merge(zb, on="h3_index", how="left")
    )

    feature_cols = list(BASE_FEATURES) + list(EXTRA_FEATURES)
    for c in feature_cols:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = df[c].astype(float).fillna(df[c].median())

    df["rank_permits"] = df["permits_new_construction_count_log"].rank(method="average") / len(df)
    df["rank_pois"] = df["new_openings_count_log"].rank(method="average") / len(df)
    df[TARGET] = (df["rank_permits"] + df["rank_pois"]) / 2.0

    # Add spatial lags (k=1, all features)
    h_to_idx = {h: i for i, h in enumerate(df["h3_index"])}
    feat_vals = df[feature_cols].to_numpy()
    out = np.zeros((len(df), len(feature_cols)))
    for i, h in enumerate(df["h3_index"]):
        ring = set(h3.grid_disk(h, 1))
        ring.discard(h)
        idxs = [h_to_idx[r] for r in ring if r in h_to_idx]
        out[i] = feat_vals[idxs].mean(axis=0) if idxs else feat_vals[i]
    lag_cols = [f"{c}_lag1" for c in feature_cols]
    df = pd.concat([df, pd.DataFrame(out, columns=lag_cols, index=df.index)], axis=1)
    return df, feature_cols + lag_cols


def main():
    print(f"=== Training production model {MODEL_VERSION} ===")
    df, features = build_dataset()
    print(f"  n_hexes={len(df):,}  n_features={len(features)}")

    model = xgb.XGBRegressor(**BEST_PARAMS)
    model.fit(df[features], df[TARGET])
    print(f"  trained on full data ({len(df):,} hexes)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    print(f"  saved model -> {MODEL_PATH}")

    # SHAP cache: per-hex per-feature contribution
    print(f"  computing SHAP values (TreeSHAP)...")
    booster = model.get_booster()
    dmatrix = xgb.DMatrix(df[features])
    shap_vals = booster.predict(dmatrix, pred_contribs=True)
    # Last column is bias term
    shap_df = pd.DataFrame(
        shap_vals[:, :-1], columns=[f"shap__{c}" for c in features]
    )
    shap_df.insert(0, "h3_index", df["h3_index"].values)
    shap_df["shap_bias"] = shap_vals[:, -1]
    shap_df["predicted_score"] = model.predict(df[features])
    shap_df.to_parquet(SHAP_PATH, index=False)
    print(f"  saved SHAP cache -> {SHAP_PATH}  ({len(shap_df):,} hexes × {len(features)} features)")

    # Model card
    card = {
        "version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "target": TARGET,
        "target_definition": (
            "rank_avg(permits_new_construction_count_log, new_openings_count_log) "
            "where permits = Atlanta building permits 2019-2024 (issued/completed/closed) "
            "and new_openings = Overture POIs added in release 2026-04-15.0 changelog "
            "within Atlanta metro bbox"
        ),
        "algorithm": "xgboost.XGBRegressor",
        "hyperparameters": {
            k: v for k, v in BEST_PARAMS.items() if not k.startswith("_") and k != "n_jobs"
        },
        "features": features,
        "n_features": len(features),
        "n_training_hexes": len(df),
        "metrics_spatial_cv": {
            "r2_mean": 0.644,
            "r2_std": 0.042,
            "mae": 0.076,
            "spearman": 0.734,
            "top_10_pct_precision": 0.679,
            "cv_strategy": "GroupKFold(n=5) on H3 res-6 spatial blocks (196 blocks)",
        },
        "label_sources": {
            "permits": "City of Atlanta Open Data — Building Permits 2019-2024 CSV (38,107 records → 34,729 issued+)",
            "poi_openings": "Overture Maps Places, GERS changelog release 2026-04-15.0 (21,443 added IDs in Atlanta bbox)",
        },
        "known_limitations": [
            "Conservative on extreme hot spots — top permit hexes underpredicted by ~10-30% on average",
            "Permit labels capped at April 2024 (CSV is a static snapshot, not live Accela feed)",
            "Zoning indicators not used (sparse across metro; only 6% of hexes have city zoning data)",
            "Atlanta-only training set — generalization to other metros untested",
        ],
    }
    CARD_PATH.write_text(json.dumps(card, indent=2))
    print(f"  saved model card -> {CARD_PATH}")

    print(f"\n  done.")


if __name__ == "__main__":
    main()
