"""v2 model wrapper — composite-target XGBoost with precomputed SHAP cache.

This is the production scoring layer. Loads artifacts produced by
backend/train_production.py and exposes:
    is_in_coverage(h3) -> bool
    explain(h3) -> dict | None
    model_info() -> dict

Loaded once at FastAPI startup (see main.py lifespan).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import h3
import numpy as np
import pandas as pd
import xgboost as xgb

DATA_DIR = Path("data")
MODEL_PATH = DATA_DIR / "models" / "xgb_v2.json"
SHAP_PATH = DATA_DIR / "models" / "shap_cache.parquet"
CARD_PATH = DATA_DIR / "models" / "model_card.json"


class V2Predictor:
    """Holds the v2 model + SHAP cache. Exposes coverage + explanation lookups."""

    def __init__(self):
        self.model: Optional[xgb.XGBRegressor] = None
        self.shap_df: Optional[pd.DataFrame] = None
        self.shap_index: dict[str, int] = {}
        self.card: dict = {}
        self.features: list[str] = []

    def load(self) -> None:
        if not MODEL_PATH.exists():
            print(f"  v2: model artifact {MODEL_PATH} not found; predictor disabled")
            return
        self.model = xgb.XGBRegressor()
        self.model.load_model(str(MODEL_PATH))
        self.shap_df = pd.read_parquet(SHAP_PATH)
        self.shap_index = {h: i for i, h in enumerate(self.shap_df["h3_index"])}
        if CARD_PATH.exists():
            self.card = json.loads(CARD_PATH.read_text())
            self.features = self.card.get("features", [])
        print(
            f"  v2 loaded: model={MODEL_PATH.name}, "
            f"shap_cache={len(self.shap_df):,} hexes × {len(self.features)} features, "
            f"version={self.card.get('version', '?')}"
        )

    @property
    def ready(self) -> bool:
        return self.model is not None and self.shap_df is not None

    def is_in_coverage(self, h3_index: str) -> bool:
        return self.ready and h3_index in self.shap_index

    def model_info(self) -> dict:
        if not self.card:
            return {"version": "unknown", "ready": self.ready}
        return {
            "version": self.card.get("version", "unknown"),
            "trained_at": self.card.get("trained_at"),
            "target": self.card.get("target"),
            "n_features": self.card.get("n_features"),
            "n_training_hexes": self.card.get("n_training_hexes"),
            "metrics": self.card.get("metrics_spatial_cv", {}),
            "label_sources": self.card.get("label_sources", {}),
            "ready": self.ready,
        }

    def explain(self, h3_index: str) -> Optional[dict]:
        """Return per-feature SHAP values, predicted score, and bias for a hex.

        SHAP columns in the cache are named `shap__<feature>`; we strip
        the prefix in the response and sort by |contribution| descending.
        """
        if not self.ready:
            return None
        idx = self.shap_index.get(h3_index)
        if idx is None:
            return None
        row = self.shap_df.iloc[idx]

        shap_pairs = []
        for col in self.shap_df.columns:
            if not col.startswith("shap__"):
                continue
            feat = col[len("shap__"):]
            val = float(row[col])
            shap_pairs.append({"feature": feat, "value": round(val, 6)})
        shap_pairs.sort(key=lambda p: abs(p["value"]), reverse=True)

        return {
            "h3_index": h3_index,
            "score": round(float(row["predicted_score"]), 4),
            "bias": round(float(row["shap_bias"]), 6),
            "shap_values": shap_pairs,
            "centroid": dict(zip(("lat", "lng"), h3.cell_to_latlng(h3_index))),
        }
