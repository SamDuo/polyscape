# PolyScape

Multi-scale GeoAI visualization technique for comparative site selection exploration.

**Core idea:** Geographic zoom level serves as the single, continuous control dimension governing what information the user sees — from aggregate prediction scores at city overview, through scenario-comparison contours at district level, to per-feature AI explanations at street level.

## Quick Start (GitHub Codespaces)

1. Open this repo in a Codespace (Code → Codespaces → Create)
2. Set environment variables in Codespace secrets:
   ```
   MAPBOX_TOKEN=pk.your_token
   CENSUS_API_KEY=your_key
   OPENAI_API_KEY=sk-your_key
   GEMINI_API_KEY=your_key
   ```
3. The devcontainer auto-installs Python deps + CCG harness
4. Run the data pipeline:
   ```bash
   python -m backend.pipeline.hex_grid
   python -m backend.pipeline.census
   python -m backend.pipeline.overture
   python -m backend.pipeline.osmnx_features
   python -m backend.pipeline.lodes
   python -m backend.model --train
   python -m backend.explainer --compute
   ```
5. Start the server:
   ```bash
   uvicorn backend.main:app --reload --port 8080
   ```
6. Open `http://localhost:8080` in browser

## Architecture

```
City Scale (z < 12)     → Hex density surfaces + divergence contour lines
District Scale (12-15)  → SHAP explanation lenses (radial bar charts)
Street Scale (z ≥ 15)   → Pinned profile cards with waterfall charts
```

## Tech Stack

- **Frontend:** Mapbox GL JS v3.9 + Deck.gl v9.1 + D3.js v7
- **Backend:** FastAPI + XGBoost + TreeSHAP + GeoShapley
- **Data:** Census ACS + Overture Maps + OSMnx + LODES + H3
- **Cache:** Redis

## CCG Multi-Model Harness

This project supports multi-model code generation via the CCG harness:
- **Codex (OpenAI):** Backend logic, API design, model training
- **Gemini (Google):** Frontend visualization, UI/UX, CSS

Run `bash scripts/setup-ccg.sh` to install the harness.
