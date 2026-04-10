# PolyScape — Claude Code Instructions

## Project Overview
Multi-scale GeoAI visualization for comparative site selection. Zoom level drives semantic visual transitions across 3 scale bands: city (hex density + contours), district (SHAP lenses), street (profile cards).

## Tech Stack
- **Frontend:** Mapbox GL JS v3.9, Deck.gl v9.1, D3.js v7, d3-contour v4, h3-js v4
- **Backend:** FastAPI, XGBoost, SHAP/TreeSHAP, GeoShapley, H3, Redis
- **Data:** Census ACS (censusdis), Overture Maps, OSMnx, LODES (pygris)

## Key Files
| File | Purpose |
|------|---------|
| `frontend/index.html` | PolyScape main app |
| `frontend/js/app.js` | SemanticZoomController + Mapbox init |
| `frontend/js/city-scale.js` | Deck.gl hex layers + d3-contour pipeline |
| `frontend/js/district-scale.js` | SHAP radial lenses |
| `frontend/js/street-scale.js` | Profile cards + waterfall charts |
| `backend/main.py` | FastAPI endpoints |
| `backend/model.py` | XGBoost training + prediction |
| `backend/explainer.py` | SHAP computation + cache |
| `backend/pipeline/` | Data fetching (census, overture, osmnx, lodes, hex_grid) |

## Design Tokens
| Token | Value | Usage |
|-------|-------|-------|
| --bg | #07090f | Page background |
| --surface | #111722 | Panels, cards |
| --teal | #00bfa5 | Primary accent |
| --critical | #ef5350 | Negative SHAP, critical |
| --stable | #66bb6a | Positive SHAP, stable |
| --muted | #5a6a7e | Secondary text |

## Scale Bands
- **City (z < 12):** H3HexagonLayer (Deck.gl) + contour lines (d3-contour → Mapbox GeoJSON)
- **District (12 ≤ z < 15):** Radial SHAP lenses (d3.arc + mapboxgl.Marker)
- **Street (z ≥ 15):** Profile cards (custom DOM + mapboxgl.Marker), max 4 pinned

## Dev Server
```bash
uvicorn backend.main:app --reload --port 8080
# Frontend: http://localhost:8080
```

## CCG Harness
Multi-model orchestration available via `~/.claude/bin/codeagent-wrapper`:
- Codex backend: `--backend codex` (backend logic authority)
- Gemini backend: `--backend gemini --gemini-model gemini-3-pro-preview` (frontend design authority)
