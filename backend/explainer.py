"""SHAP-based model explainability for site suitability scores.

Computes TreeSHAP values for all H3 hexes and provides per-hex
feature importance explanations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from backend.model import FEATURE_COLUMNS, _prepare_features

DEFAULT_SHAP_CACHE_PATH = Path("data/models/shap_cache.parquet")


def compute_shap_values(
    model: xgb.XGBRegressor,
    features_df: pd.DataFrame,
    cache_path: str | Path = DEFAULT_SHAP_CACHE_PATH,
) -> pd.DataFrame:
    """Compute TreeSHAP values for all hexes.

    Parameters
    ----------
    model : xgb.XGBRegressor
        Trained XGBoost model.
    features_df : pd.DataFrame
        Feature DataFrame with h3_index column.
    cache_path : str | Path
        Path to save SHAP cache Parquet.

    Returns
    -------
    pd.DataFrame
        Columns: h3_index, one SHAP value column per feature, base_value.
    """
    X = _prepare_features(features_df)
    # Ensure column order matches FEATURE_COLUMNS (which matches training order)
    X = X[FEATURE_COLUMNS]

    print(f"Computing SHAP values for {len(X)} hexes...")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    # Build result DataFrame — column order is guaranteed by X[FEATURE_COLUMNS] above
    shap_cols = {f"shap_{col}": shap_values[:, i] for i, col in enumerate(FEATURE_COLUMNS)}
    result = pd.DataFrame(shap_cols)

    # Add h3_index
    if "h3_index" in features_df.columns:
        result["h3_index"] = features_df["h3_index"].values
    else:
        result["h3_index"] = range(len(result))

    # Add base value (expected value from the explainer)
    base_value = float(explainer.expected_value)
    result["base_value"] = base_value

    # Reorder columns: h3_index first
    cols = ["h3_index"] + [c for c in result.columns if c != "h3_index"]
    result = result[cols]

    # Save to Parquet cache
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache_path, index=False)
    print(f"SHAP cache saved to {cache_path} ({len(result)} rows)")

    return result


def get_explanation(h3_index: str, shap_df: pd.DataFrame) -> dict:
    """Get full SHAP explanation for a single hex.

    Parameters
    ----------
    h3_index : str
        H3 cell index to explain.
    shap_df : pd.DataFrame
        SHAP values DataFrame from compute_shap_values().

    Returns
    -------
    dict
        Keys: h3_index, base_value, shap_values (list of {feature, value}),
        top_positive (top 3 positive drivers), top_negative (top 3 negative).
    """
    row = shap_df[shap_df["h3_index"] == h3_index]
    if row.empty:
        raise KeyError(f"H3 index {h3_index} not found in SHAP data.")

    row = row.iloc[0]
    base_value = float(row["base_value"])

    shap_values: list[dict] = []
    for col in FEATURE_COLUMNS:
        shap_col = f"shap_{col}"
        if shap_col in row.index:
            val = float(row[shap_col])
            if not np.isnan(val):
                shap_values.append({"feature": col, "value": val})

    # Sort by absolute value descending
    shap_values.sort(key=lambda x: abs(x["value"]), reverse=True)

    positive = [sv for sv in shap_values if sv["value"] > 0][:3]
    negative = [sv for sv in shap_values if sv["value"] < 0][:3]

    return {
        "h3_index": h3_index,
        "base_value": base_value,
        "shap_values": shap_values,
        "top_positive": positive,
        "top_negative": negative,
    }


def get_top_features(
    shap_df: pd.DataFrame,
    h3_index: str,
    n: int = 5,
) -> list[dict]:
    """Get top-N features by absolute SHAP value for a hex.

    Parameters
    ----------
    shap_df : pd.DataFrame
        SHAP values DataFrame.
    h3_index : str
        H3 cell index.
    n : int
        Number of top features to return.

    Returns
    -------
    list[dict]
        Sorted list of {feature, value} dicts.
    """
    row = shap_df[shap_df["h3_index"] == h3_index]
    if row.empty:
        raise KeyError(f"H3 index {h3_index} not found in SHAP data.")

    row = row.iloc[0]
    features: list[dict] = []
    for col in FEATURE_COLUMNS:
        shap_col = f"shap_{col}"
        if shap_col in row.index:
            val = float(row[shap_col])
            if not np.isnan(val):
                features.append({"feature": col, "value": val})

    features.sort(key=lambda x: abs(x["value"]), reverse=True)
    return features[:n]


if __name__ == "__main__":
    from backend.model import load_features, load_model

    model = load_model()
    features = load_features("data")

    shap_df = compute_shap_values(model, features)
    print(f"\nSHAP DataFrame shape: {shap_df.shape}")

    # Show explanation for first hex
    if len(shap_df) > 0:
        first_hex = shap_df["h3_index"].iloc[0]
        explanation = get_explanation(first_hex, shap_df)
        print(f"\nExplanation for {first_hex}:")
        print(f"  Base value: {explanation['base_value']:.4f}")
        print(f"  Top features:")
        for sv in explanation["shap_values"][:5]:
            print(f"    {sv['feature']}: {sv['value']:+.4f}")
