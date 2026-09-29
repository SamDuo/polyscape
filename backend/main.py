"""FastAPI application for PolyScape GeoAI site-selection API.

Endpoints:
  GET  /              — serves frontend index.html
  GET  /api/health    — health check
  GET  /api/config    — Mapbox token + feature list
  GET  /predict       — H3 hex grid with suitability scores as GeoJSON
  GET  /explain/{h3}  — per-feature SHAP explanation for a hex
  POST /explain/batch — batch SHAP explanations for multiple hexes
  GET  /features/{h3} — raw feature values for a hex
  POST /scenarios/diff — score difference between base and modified scenario
  POST /predict/custom — predictions with custom feature overrides
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import h3
import numpy as np
import pandas as pd
import xgboost as xgb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from shapely.geometry import mapping as shapely_mapping
from shapely.geometry import Polygon

from backend.cache import SHAPCache
from backend.model import DEFAULT_MODEL_PATH, FEATURE_COLUMNS, _prepare_features, load_model, predict
from backend.v2 import V2Predictor

# ---------- Configuration ----------

DATA_DIR = Path(os.getenv("POLYSCAPE_DATA_DIR", "data"))
MODEL_PATH = Path(os.getenv("POLYSCAPE_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
SHAP_CACHE_PATH = Path(os.getenv("POLYSCAPE_SHAP_CACHE", "data/models/shap_cache.parquet"))
REDIS_URL = os.getenv("POLYSCAPE_REDIS_URL", None)
FRONTEND_DIR = Path(os.getenv("POLYSCAPE_FRONTEND_DIR", "frontend"))
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")

# ---------- Global state ----------

_model: Optional[xgb.XGBRegressor] = None
_shap_cache: Optional[SHAPCache] = None
_features_df: Optional[pd.DataFrame] = None
_v2 = V2Predictor()


# ---------- Startup / Shutdown ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model and SHAP cache on startup."""
    global _model, _shap_cache, _features_df

    # Load model
    if MODEL_PATH.exists():
        try:
            _model = load_model(MODEL_PATH)
            print(f"Model loaded from {MODEL_PATH}")
        except Exception as exc:
            print(f"Warning: failed to load model: {exc}")

    # Load SHAP cache
    _shap_cache = SHAPCache(redis_url=REDIS_URL)
    if SHAP_CACHE_PATH.exists():
        try:
            _shap_cache.load_from_parquet(SHAP_CACHE_PATH)
            print(f"SHAP cache loaded: {_shap_cache.size} entries")
        except Exception as exc:
            print(f"Warning: failed to load SHAP cache: {exc}")

    # Load features for prediction
    features_path = DATA_DIR / "features.parquet"
    if features_path.exists():
        try:
            _features_df = pd.read_parquet(features_path)
            print(f"Features loaded: {len(_features_df)} hexes")
        except Exception as exc:
            print(f"Warning: failed to load features: {exc}")

    # Load v2 (composite-target) predictor
    try:
        _v2.load()
    except Exception as exc:
        print(f"Warning: failed to load v2 predictor: {exc}")

    yield

    # Cleanup
    if _shap_cache is not None:
        _shap_cache.clear()


# ---------- App setup ----------

app = FastAPI(
    title="PolyScape",
    description="GeoAI site-selection API for Atlanta metro",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Model-Version"],
)


@app.middleware("http")
async def add_model_version_header(request: Request, call_next):
    """Stamp every response with the loaded v2 model version so clients
    can detect drift when the artifact is redeployed."""
    response = await call_next(request)
    if _v2.ready:
        response.headers["X-Model-Version"] = _v2.card.get("version", "unknown")
    return response

# ---------- Request / Response models ----------

class FeatureOverride(BaseModel):
    """Feature value overrides for custom prediction."""
    feature: str
    value: float


class CustomPredictRequest(BaseModel):
    """Request body for POST /predict/custom."""
    h3_indices: Optional[list[str]] = None
    overrides: list[FeatureOverride] = Field(default_factory=list)


class SHAPFeature(BaseModel):
    """Single feature SHAP value."""
    feature: str
    value: float


class ExplainResponse(BaseModel):
    """Response for GET /explain/{h3_index}."""
    h3_index: str
    score: Optional[float] = None
    base_value: float
    shap_values: list[SHAPFeature]


# ---------- Helpers ----------

def _h3_cell_to_geojson_polygon(h3_index: str) -> dict:
    """Convert H3 cell to GeoJSON polygon geometry."""
    boundary = h3.cell_to_boundary(h3_index)
    coords = [(lng, lat) for lat, lng in boundary]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _make_feature_collection(
    h3_indices: list[str],
    scores: np.ndarray,
    extra_properties: Optional[dict[str, list]] = None,
) -> dict:
    """Build a GeoJSON FeatureCollection from H3 indices and scores."""
    features: list[dict] = []
    for i, (h3_idx, score) in enumerate(zip(h3_indices, scores)):
        props: dict[str, Any] = {
            "h3_index": h3_idx,
            "score": round(float(score), 4),
        }
        if extra_properties:
            for key, values in extra_properties.items():
                props[key] = values[i] if i < len(values) else None

        features.append(
            {
                "type": "Feature",
                "geometry": _h3_cell_to_geojson_polygon(h3_idx),
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def _filter_by_bbox(
    df: pd.DataFrame, bbox: tuple[float, float, float, float]
) -> pd.DataFrame:
    """Filter DataFrame by bounding box (west, south, east, north)."""
    w, s, e, n = bbox
    if "lat" in df.columns and "lng" in df.columns:
        return df[
            (df["lat"] >= s) & (df["lat"] <= n) &
            (df["lng"] >= w) & (df["lng"] <= e)
        ]
    return df


class BatchExplainRequest(BaseModel):
    """Request body for POST /explain/batch."""
    h3_indices: list[str]


# ---------- Endpoints ----------

@app.get("/")
async def serve_frontend():
    """Serve the frontend index.html."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "ok", "message": "Frontend not found. API is running."}


@app.get("/api/health")
async def health_check() -> dict:
    """Health check endpoint. Reports both legacy (v1) and production (v2) state."""
    return {
        "status": "ok",
        "v1": {
            "model_loaded": _model is not None,
            "shap_cache_size": _shap_cache.size if _shap_cache else 0,
            "features_loaded": _features_df is not None and len(_features_df) > 0,
        },
        "v2": _v2.model_info(),
    }


@app.get("/v2/coverage/{h3_index}")
async def v2_coverage(h3_index: str) -> dict:
    """Return whether the v2 model has data for this hex.

    Clients should call this before /v2/explain to distinguish 'out of
    coverage' from 'service error'.
    """
    if not _v2.ready:
        raise HTTPException(status_code=503, detail="v2 predictor not loaded")
    if not _v2.is_in_coverage(h3_index):
        raise HTTPException(status_code=404, detail="hex out of model coverage")
    return {"h3_index": h3_index, "in_coverage": True}


@app.get("/v2/explain/{h3_index}")
async def v2_explain(h3_index: str) -> dict:
    """v2 SHAP explanation for a hex, served from the precomputed cache."""
    if not _v2.ready:
        raise HTTPException(status_code=503, detail="v2 predictor not loaded")
    result = _v2.explain(h3_index)
    if result is None:
        raise HTTPException(status_code=404, detail="hex out of model coverage")
    return result


@app.get("/v2/info")
async def v2_info() -> dict:
    """Model card for the loaded v2 model (version, target, metrics, label sources)."""
    if not _v2.ready:
        raise HTTPException(status_code=503, detail="v2 predictor not loaded")
    return _v2.model_info()


@app.get("/api/config")
async def get_config() -> dict:
    """Return frontend configuration including Mapbox token."""
    return {
        "mapboxToken": MAPBOX_TOKEN,
        "features": FEATURE_COLUMNS,
        "hexCount": len(_features_df) if _features_df is not None else 0,
    }


@app.get("/predict")
async def predict_endpoint(
    bbox: str = Query(
        ...,
        description="Bounding box as 'west,south,east,north'",
        examples=["-84.5,33.6,-84.2,33.9"],
    ),
    res: int = Query(
        8,
        description="H3 resolution (7, 8, or 9)",
        ge=7,
        le=9,
    ),
) -> dict:
    """Return H3 hex grid with suitability scores as GeoJSON FeatureCollection.

    Each feature contains: h3_index, score, geometry (hex polygon).
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded.")
    if _features_df is None or _features_df.empty:
        raise HTTPException(status_code=503, detail="Feature data not loaded.")

    # Parse bbox
    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        w, s, e, n = parts
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="bbox must be 'west,south,east,north' (4 comma-separated floats).",
        )

    # Filter features to bbox
    filtered = _filter_by_bbox(_features_df, (w, s, e, n))
    if filtered.empty:
        return {"type": "FeatureCollection", "features": []}

    # Predict scores
    scores = predict(_model, filtered)
    h3_indices = filtered["h3_index"].tolist()

    return _make_feature_collection(h3_indices, scores)


@app.get("/explain/{h3_index}")
async def explain_endpoint(h3_index: str) -> ExplainResponse:
    """Return per-feature SHAP values for a hex cell."""
    if _shap_cache is None:
        raise HTTPException(status_code=503, detail="SHAP cache not loaded.")

    entry = _shap_cache.get(h3_index)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"No SHAP data found for hex {h3_index}.",
        )

    base_value = entry.get("base_value", 0.0)
    shap_values = [
        SHAPFeature(feature=feat, value=round(val, 6))
        for feat, val in entry.items()
        if feat in FEATURE_COLUMNS
    ]
    # Sort by absolute value descending
    shap_values.sort(key=lambda x: abs(x.value), reverse=True)

    # Compute score if model and features are available
    score: Optional[float] = None
    if _model is not None and _features_df is not None:
        hex_row = _features_df[_features_df["h3_index"] == h3_index]
        if not hex_row.empty:
            s = predict(_model, hex_row)
            score = round(float(s[0]), 4)

    return ExplainResponse(
        h3_index=h3_index,
        score=score,
        base_value=round(base_value, 6),
        shap_values=shap_values,
    )


@app.post("/explain/batch")
async def explain_batch(request: BatchExplainRequest) -> dict:
    """Return SHAP explanations for multiple hexes with centroid coordinates."""
    if _shap_cache is None:
        raise HTTPException(status_code=503, detail="SHAP cache not loaded.")

    explanations = []
    for h3_idx in request.h3_indices[:100]:  # cap at 100
        entry = _shap_cache.get(h3_idx)
        if entry is None:
            continue

        base_value = entry.get("base_value", 0.0)
        shap_values = [
            {"feature": feat, "value": round(val, 6)}
            for feat, val in entry.items()
            if feat in FEATURE_COLUMNS
        ]
        shap_values.sort(key=lambda x: abs(x["value"]), reverse=True)

        # Get centroid
        try:
            lat, lng = h3.cell_to_latlng(h3_idx)
        except Exception:
            continue

        # Get score
        score = None
        if _model is not None and _features_df is not None:
            row = _features_df[_features_df["h3_index"] == h3_idx]
            if not row.empty:
                s = predict(_model, row)
                score = round(float(s[0]), 4)

        explanations.append({
            "h3_index": h3_idx,
            "score": score,
            "base_value": round(base_value, 6),
            "shap_values": shap_values,
            "centroid": {"lat": lat, "lng": lng},
        })

    return {"explanations": explanations}


@app.get("/features/{h3_index}")
async def get_features(h3_index: str) -> dict:
    """Return raw feature values for a hex (used by profile cards)."""
    if _features_df is None or _features_df.empty:
        raise HTTPException(status_code=503, detail="Feature data not loaded.")

    row = _features_df[_features_df["h3_index"] == h3_index]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Hex {h3_index} not found.")

    row = row.iloc[0]
    features = {}
    for col in _features_df.columns:
        if col in ("geometry",):
            continue
        val = row[col]
        if pd.isna(val):
            features[col] = None
        elif isinstance(val, (np.integer,)):
            features[col] = int(val)
        elif isinstance(val, (np.floating, float)):
            features[col] = round(float(val), 4)
        else:
            features[col] = val

    return features


class ScenarioDiffRequest(BaseModel):
    """Request body for POST /scenarios/diff."""
    bbox: str = Field(..., description="Bounding box as 'west,south,east,north'")
    overrides: list[FeatureOverride] = Field(default_factory=list)


@app.post("/scenarios/diff")
async def scenarios_diff(request: ScenarioDiffRequest) -> dict:
    """Compute score difference between base and modified scenario.

    Send feature overrides in the request body.
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded.")
    if _features_df is None or _features_df.empty:
        raise HTTPException(status_code=503, detail="Feature data not loaded.")

    # Parse bbox
    try:
        parts = [float(x.strip()) for x in request.bbox.split(",")]
        w, s, e, n = parts
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid bbox format.")

    filtered = _filter_by_bbox(_features_df, (w, s, e, n))
    if filtered.empty:
        return {"type": "FeatureCollection", "features": []}

    # Base scores
    base_scores = predict(_model, filtered)

    # Modified scores with overrides
    modified = filtered.copy()
    for override in request.overrides:
        if override.feature in FEATURE_COLUMNS:
            modified[override.feature] = override.value
    modified_scores = predict(_model, modified)

    diff_scores = modified_scores - base_scores
    h3_indices = filtered["h3_index"].tolist()

    return _make_feature_collection(
        h3_indices,
        diff_scores,
        extra_properties={
            "base_score": [round(float(s), 4) for s in base_scores],
            "modified_score": [round(float(s), 4) for s in modified_scores],
        },
    )


@app.post("/predict/custom")
async def predict_custom(request: CustomPredictRequest) -> dict:
    """Accept feature overrides and return modified predictions."""
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded.")
    if _features_df is None or _features_df.empty:
        raise HTTPException(status_code=503, detail="Feature data not loaded.")

    # Select hexes
    if request.h3_indices:
        filtered = _features_df[_features_df["h3_index"].isin(request.h3_indices)]
        if filtered.empty:
            raise HTTPException(
                status_code=404,
                detail="None of the specified H3 indices found in feature data.",
            )
    else:
        filtered = _features_df

    # Apply overrides
    modified = filtered.copy()
    for override in request.overrides:
        if override.feature in FEATURE_COLUMNS:
            modified[override.feature] = override.value
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown feature: {override.feature}. "
                       f"Valid features: {FEATURE_COLUMNS}",
            )

    scores = predict(_model, modified)
    h3_indices = modified["h3_index"].tolist() if "h3_index" in modified.columns else list(range(len(scores)))

    return _make_feature_collection(
        [str(idx) for idx in h3_indices],
        scores,
    )


# ---------- Static files (must be AFTER all API routes) ----------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ---------- Main ----------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("POLYSCAPE_PORT", "8080"))
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
