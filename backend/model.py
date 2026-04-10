"""XGBoost model training and prediction for site suitability scoring.

Loads feature Parquet files, trains an XGBoost regressor on a composite
suitability target, and provides prediction and model persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb

# Ordered feature list used by the model
FEATURE_COLUMNS: list[str] = [
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

# Default model hyperparameters
DEFAULT_PARAMS: dict = {
    "max_depth": 6,
    "n_estimators": 500,
    "learning_rate": 0.05,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": 42,
    "n_jobs": -1,
}

DEFAULT_MODEL_PATH = Path("data/models/xgb_model.json")


def load_features(data_dir: str | Path) -> pd.DataFrame:
    """Load and merge all feature Parquet files into a unified DataFrame.

    Expects Parquet files in data_dir with an 'h3_index' column for joining.

    Parameters
    ----------
    data_dir : str | Path
        Directory containing feature Parquet files.

    Returns
    -------
    pd.DataFrame
        Merged feature DataFrame keyed by h3_index.
    """
    data_dir = Path(data_dir)
    parquet_files = sorted(data_dir.glob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found in {data_dir}")

    dfs: list[pd.DataFrame] = []
    for f in parquet_files:
        try:
            df = pd.read_parquet(f)
            if "h3_index" in df.columns:
                dfs.append(df)
                print(f"  Loaded {f.name}: {len(df)} rows, {list(df.columns)}")
            else:
                print(f"  Skipped {f.name}: no h3_index column")
        except Exception as exc:
            print(f"  Warning: failed to load {f.name}: {exc}")

    if not dfs:
        raise RuntimeError("No valid feature files loaded.")

    # Merge all DataFrames on h3_index
    merged = dfs[0]
    for df in dfs[1:]:
        merged = merged.merge(df, on="h3_index", how="outer", suffixes=("", "_dup"))
        # Drop duplicate columns from overlapping joins
        dup_cols = [c for c in merged.columns if c.endswith("_dup")]
        merged = merged.drop(columns=dup_cols)

    print(f"Merged features: {len(merged)} hexes, {len(merged.columns)} columns")
    return merged


def _compute_target(df: pd.DataFrame) -> pd.Series:
    """Compute composite suitability score as the training target.

    Target = normalized composite of:
      + population_density
      + complementary_poi_count
      + walk_score
      - competitor_count

    Each component is min-max normalized before combining.
    """

    def _normalize(series: pd.Series) -> pd.Series:
        s_min, s_max = series.min(), series.max()
        if s_max - s_min == 0:
            return pd.Series(0.5, index=series.index)
        return (series - s_min) / (s_max - s_min)

    components = {
        "population_density": 1.0,
        "complementary_poi_count": 1.0,
        "walk_score": 1.0,
        "competitor_count": -1.0,
    }

    target = pd.Series(0.0, index=df.index)
    n_valid = 0
    for col, weight in components.items():
        if col in df.columns:
            normalized = _normalize(df[col].fillna(0))
            target += weight * normalized
            n_valid += 1

    if n_valid > 0:
        target = _normalize(target)

    return target


def _prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract and fill model feature columns from a DataFrame."""
    features = pd.DataFrame(index=df.index)
    for col in FEATURE_COLUMNS:
        if col in df.columns:
            features[col] = df[col].astype(float)
        else:
            features[col] = 0.0

    # Fill NaN with column medians, then zero
    features = features.fillna(features.median()).fillna(0.0)
    return features


def train_model(
    features_df: pd.DataFrame,
    params: Optional[dict] = None,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> xgb.XGBRegressor:
    """Train an XGBoost regressor on the composite suitability score.

    Parameters
    ----------
    features_df : pd.DataFrame
        Feature DataFrame with h3_index and feature columns.
    params : dict | None
        XGBoost hyperparameters. Uses DEFAULT_PARAMS if None.
    model_path : str | Path
        Path to save the trained model JSON.

    Returns
    -------
    xgb.XGBRegressor
        Trained model.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}

    X = _prepare_features(features_df)
    y = _compute_target(features_df)

    # Remove rows with all-zero features (likely missing data)
    valid_mask = X.sum(axis=1) > 0
    X_valid = X[valid_mask]
    y_valid = y[valid_mask]

    if len(X_valid) == 0:
        raise ValueError("No valid training samples after filtering.")

    print(f"Training XGBoost on {len(X_valid)} samples, {len(FEATURE_COLUMNS)} features")

    model = xgb.XGBRegressor(**params)
    model.fit(
        X_valid,
        y_valid,
        eval_set=[(X_valid, y_valid)],
        verbose=50,
    )

    # Save model
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    print(f"Model saved to {model_path}")

    # Report feature importance
    importance = dict(zip(FEATURE_COLUMNS, model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    print("Feature importance (top 5):")
    for feat, imp in sorted_imp[:5]:
        print(f"  {feat}: {imp:.4f}")

    return model


def predict(model: xgb.XGBRegressor, features: pd.DataFrame) -> np.ndarray:
    """Generate suitability scores for hex features.

    Parameters
    ----------
    model : xgb.XGBRegressor
        Trained XGBoost model.
    features : pd.DataFrame
        Feature DataFrame (may contain h3_index and extra columns).

    Returns
    -------
    np.ndarray
        Predicted suitability scores (0-1 range).
    """
    X = _prepare_features(features)
    scores = model.predict(X)
    # Clip to [0, 1]
    scores = np.clip(scores, 0.0, 1.0)
    return scores


def load_model(path: str | Path = DEFAULT_MODEL_PATH) -> xgb.XGBRegressor:
    """Load a saved XGBoost model from JSON.

    Parameters
    ----------
    path : str | Path
        Path to model JSON file.

    Returns
    -------
    xgb.XGBRegressor
        Loaded model.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")

    model = xgb.XGBRegressor()
    model.load_model(str(path))
    print(f"Loaded model from {path}")
    return model


if __name__ == "__main__":
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"

    print(f"Loading features from {data_dir}/...")
    features = load_features(data_dir)

    print("\nTraining model...")
    model = train_model(features)

    print("\nPredicting on training set...")
    scores = predict(model, features)
    print(f"Score stats: min={scores.min():.3f}, max={scores.max():.3f}, "
          f"mean={scores.mean():.3f}, median={np.median(scores):.3f}")
