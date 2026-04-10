# Implementation Plan: PolyScape Prototype

## Task Type
- [x] Frontend (Mapbox GL JS + Deck.gl + D3.js)
- [x] Backend (Python FastAPI + XGBoost + SHAP)
- [x] Fullstack

---

## Technical Solution

### Architecture Overview

```
                        PolyScape System
 ┌──────────────────────────────────────────────────────┐
 │                    FRONTEND                          │
 │  Mapbox GL JS v3.9 (base map + vector labels)        │
 │  ├── Deck.gl MapboxOverlay (interleaved)             │
 │  │   ├── H3HexagonLayer   (city: hex density)        │
 │  │   └── HexagonLayer     (city: scenario overlays)  │
 │  ├── Mapbox GeoJSON Layers                           │
 │  │   └── Contour lines    (city: divergence iso)     │
 │  ├── mapboxgl.Marker + D3 SVG                        │
 │  │   ├── Radial bar charts (district: SHAP lenses)   │
 │  │   └── Profile cards     (street: pinned sites)    │
 │  └── SemanticZoomController                          │
 │      └── Listens to zoom → toggles layers/markers    │
 ├──────────────────────────────────────────────────────┤
 │                    BACKEND (FastAPI)                  │
 │  GET /predict?bbox=...&res=8 → H3 hex score grid     │
 │  GET /explain/{h3_index}    → TreeSHAP per-feature    │
 │  GET /scenarios/diff?a=...&b=... → difference grid    │
 │  POST /predict/custom       → what-if overrides       │
 │  ├── XGBoost model (trained on Atlanta metro data)   │
 │  ├── TreeSHAP (fast per-request)                     │
 │  ├── GeoShapley (pre-computed, cached)               │
 │  └── Redis cache (H3-keyed SHAP values)              │
 ├──────────────────────────────────────────────────────┤
 │                    DATA PIPELINE                      │
 │  Census ACS 5-Year → block group demographics         │
 │  Overture Maps     → POI / competitor counts          │
 │  OSMnx             → walk score, transit proximity    │
 │  Census LODES      → daytime population, commute flow │
 │  H3 (res 7/8/9)   → spatial index for all features   │
 └──────────────────────────────────────────────────────┘
```

### Key Technology Choices

| Component | Technology | Why |
|-----------|-----------|-----|
| Base map | Mapbox GL JS v3.9 | Zoom expressions, WebGL, industry standard |
| City-scale hex grids | Deck.gl v9.1 `H3HexagonLayer` | GPU-accelerated, handles 50K+ hexes |
| Contour lines | `d3-contour` v4 → Mapbox GeoJSON layer | Native WebGL rendering, no sync overhead |
| SHAP lenses | `d3.arc()` + `mapboxgl.Marker` | DOM-based interactivity, auto-repositioning |
| Profile cards | Custom DOM + `mapboxgl.Marker` | Pinnable, persistent, full CSS control |
| SHAP waterfall | Custom D3 (no JS library exists) | Horizontal diverging stacked bar |
| API framework | FastAPI v0.115+ | 5x faster than Flask, async, auto-docs |
| ML model | XGBoost v2.1+ | GPU TreeSHAP, proven for site selection |
| Explainability | SHAP v0.46 + GeoShapley v0.1 | TreeSHAP (fast) + GeoShapley (spatial decomposition) |
| Hex spatial index | H3 v4.2 | Multi-resolution, parent/child hierarchy |
| Census data | censusdis | Pythonic, returns GeoDataFrame with geometry |
| POI data | Overture Maps | 64M+ POIs, free, GeoParquet, replaces SafeGraph |
| Network analysis | OSMnx v2.1 | Walk score, isochrones, transit proximity |
| Cache | Redis v7 | O(1) lookup by H3 index |

---

## Implementation Steps

### Phase 1: Data Pipeline & Model Training (Week 1-2)

#### Step 1.1: Set Up Project Structure
- Expected deliverable: Scaffolded project with frontend + backend directories

```
polyscape/
├── frontend/
│   ├── index.html          # PolyScape app
│   ├── baseline.html       # Multi-panel dashboard (study baseline)
│   ├── js/
│   │   ├── app.js          # Entry point, SemanticZoomController
│   │   ├── city-scale.js   # Deck.gl hex layers + contour generation
│   │   ├── district-scale.js # SHAP lenses (radial bar charts)
│   │   ├── street-scale.js # Profile cards + waterfall charts
│   │   └── study-logger.js # Task timing + interaction logging
│   └── css/
│       └── polyscape.css
├── backend/
│   ├── main.py             # FastAPI app
│   ├── model.py            # XGBoost model loading + prediction
│   ├── explainer.py        # SHAP computation
│   ├── data_pipeline/
│   │   ├── census.py       # ACS data fetcher
│   │   ├── overture.py     # POI extraction
│   │   ├── osmnx_features.py # Walk score, transit
│   │   ├── lodes.py        # Employment flows
│   │   └── hex_grid.py     # H3 grid generation + feature join
│   └── cache.py            # Redis caching layer
├── data/
│   ├── raw/                # Downloaded census, POI, LODES
│   ├── processed/          # H3-indexed feature tables (Parquet)
│   └── models/             # Trained XGBoost model + SHAP cache
├── study/
│   ├── tasks.json          # 9 study tasks with ground truth
│   ├── surveys/            # NASA-TLX, SUS, Likert templates
│   └── analysis.py         # Statistical analysis script
└── requirements.txt
```

#### Step 1.2: Build H3 Hex Grid for Atlanta Metro
- Generate H3 hexes at res 7, 8, 9 for the 5-county Atlanta metro area
- Expected: ~2K (res 7), ~14K (res 8), ~95K (res 9) hexes
- Output: GeoJSON + Parquet files keyed by H3 index

```python
import h3
import geopandas as gpd
from shapely.geometry import Polygon

# Atlanta metro bounding polygon (5-county: Fulton, DeKalb, Cobb, Gwinnett, Clayton)
atlanta_poly = gpd.read_file("data/raw/atlanta_metro.geojson").geometry[0]
hexes_r8 = h3.geo_to_cells(atlanta_poly, res=8)
# ~14,000 hexes
```

#### Step 1.3: Fetch & Join Census ACS Data
- Variables: `B19013` (income), `B01003` (population), `B01001` (age), `B23025` (employment), `B25064` (rent), `B11001` (households), `B15003` (education)
- Spatial join: Census block groups → H3 hexes via area-weighted interpolation
- Expected deliverable: `features_census.parquet` with 14K rows x 8 features

#### Step 1.4: Extract POI Features (Overture Maps + OSMnx)
- Overture Maps Places theme: competitor_count, complementary_poi_count per hex
- OSMnx: walk_score (amenities within 800m network), transit_proximity (dist to MARTA), road_density
- Expected deliverable: `features_poi.parquet` with 14K rows x 6 features

#### Step 1.5: Fetch LODES Employment Data
- Census LEHD/LODES: daytime_population (WAC), commute_inflow per hex
- Expected deliverable: `features_lodes.parquet` with 14K rows x 2 features

#### Step 1.6: Merge Features & Train XGBoost Model
- Merge all feature Parquets into unified `hex_features.parquet` (14K rows x ~14 features)
- Define target variable: composite site suitability score (e.g., revenue proxy from POI density + foot traffic)
- Train XGBoost with `max_depth=6, n_estimators=500`
- Compute TreeSHAP values for all 14K hexes → `shap_cache.parquet`
- Optionally run GeoShapley for spatial decomposition → `geoshap_cache.parquet`

**Key features (14 total):**
1. `median_income` 2. `population_density` 3. `pct_age_25_44`
4. `employment_rate` 5. `daytime_population` 6. `commute_inflow`
7. `competitor_count` 8. `complementary_poi_count` 9. `walk_score`
10. `transit_proximity` 11. `road_density` 12. `median_rent`
13. `household_density` 14. `land_use_mix`

#### Step 1.7: Build FastAPI Backend
- `/predict` endpoint: returns H3 hex grid with scores as GeoJSON FeatureCollection
- `/explain/{h3_index}` endpoint: returns per-feature SHAP values from Redis cache
- `/scenarios/diff` endpoint: computes score difference grid between two what-if scenarios
- `/predict/custom` endpoint: accepts feature overrides for what-if analysis
- Redis cache layer for O(1) SHAP lookups

---

### Phase 2: PolyScape Frontend (Week 3)

#### Step 2.1: Base Map + Semantic Zoom Controller
- Initialize Mapbox GL JS v3.9 with dark basemap
- Implement `SemanticZoomController` class that listens to `map.on('zoom')` and determines current band:
  - `z < 12` → city band
  - `12 <= z < 15` → district band
  - `z >= 15` → street band
- Implement 1-zoom-level fade transitions between bands (not hard cuts)

```javascript
class SemanticZoomController {
  constructor(map) {
    this.map = map;
    this.currentBand = null;
    map.on('zoom', () => this.update());
  }
  update() {
    const z = this.map.getZoom();
    const band = z < 12 ? 'city' : z < 15 ? 'district' : 'street';
    if (band !== this.currentBand) {
      this.transition(this.currentBand, band);
      this.currentBand = band;
    }
  }
}
```

#### Step 2.2: City Scale — Hex Density Surfaces + Contour Lines (z < 12)
- **Deck.gl `H3HexagonLayer`**: Two scenario overlays (blue ramp for Scenario A, orange for Scenario B) at 40% opacity
- **Contour lines**: Compute difference grid (A - B), rasterize to 200x200 rectangular grid via IDW, run `d3.contours()`, transform to GeoJSON, render as Mapbox `line` layer
- Contour labels showing "+12%", "-18%" at divergence peaks
- **What-if scenario panel**: Sliders for adjusting scenario parameters (budget, competitor mix)

```javascript
// Contour pipeline (runs ~20-50ms, fully real-time)
const diffGrid = rasterizeHexDiffs(hexDataA, hexDataB, 200, 200);
const contourGeo = d3.contours()
  .size([200, 200])
  .thresholds([-0.5, -0.2, 0.2, 0.5])
  .smooth(true)(diffGrid);
// Transform to geographic coords and add to Mapbox source
map.getSource('contours').setData(toFeatureCollection(contourGeo));
```

#### Step 2.3: District Scale — SHAP Explanation Lenses (12 <= z < 15)
- Fetch SHAP values for visible census tracts from `/explain` endpoint
- Render radial bar charts using `d3.arc()` inside `mapboxgl.Marker` elements
- Top-5 features per tract: green outward (positive SHAP), red inward (negative)
- Hover: expand lens + show feature names tooltip
- Click: zoom to street level for that tract
- Budget: ~50-100 simultaneous markers (well under 700 threshold)

#### Step 2.4: Street Scale — Profile Cards (z >= 15)
- Individual candidate sites resolve into floating cards
- Each card contains:
  - (a) Predicted score per scenario (header)
  - (b) Horizontal SHAP waterfall chart (custom D3, `d3.scaleLinear` + `rect` + connector lines)
  - (c) 12-month sparkline (`d3.line()` with `d3.curveMonotoneX`)
  - (d) Raw metrics (population density, competitor count, income, walk score)
- Pin/unpin up to 4 cards (oldest auto-evicts)
- Cards persist across pan/zoom via `mapboxgl.Marker`

#### Step 2.5: Scenario Controls + Integration
- Scenario panel (left sidebar): define Scenario A and B with parameter sliders
- When scenario changes → re-fetch predictions → update hex layers + contours + SHAP lenses
- Stats bar (bottom): live feature counts, active scenario summary
- Smooth animated transitions between all scale band changes (~400ms D3 transitions)

---

### Phase 3: Baseline Dashboard + Pilot Test (Week 3-4)

#### Step 3.1: Build Multi-Panel Baseline Dashboard
- **Same data, same tech stack, different layout** (fair comparison)
- Panel 1: Choropleth map (single scenario at a time, toggle between A/B)
- Panel 2: Ranked table of candidate sites (sortable by score)
- Panel 3: Bar chart of demographic breakdown for selected area
- Panel 4: SHAP explanation sidebar (bar chart, not spatial)
- Linked brushing: selecting on map highlights in table/charts
- Standard coordinated multiple views (CMV) pattern

#### Step 3.2: Implement Study Logger
- `performance.now()` for task timing (sub-ms precision)
- Log interactions: `{timestamp, eventType, zoomLevel, center, viewport}`
- POST batches to Flask/SQLite backend every 5 seconds
- Embed in-task 7-point Likert confidence scale (radio buttons, all points labeled)

#### Step 3.3: Pilot Test (3 volunteers)
- Run through all 9 study tasks with think-aloud
- Identify usability issues, confusing interactions, timing problems
- Iterate on both PolyScape and baseline based on feedback

---

### Phase 4: User Study (Week 4-5)

#### Step 4.1: Study Setup
- Between-subjects: 12 participants per condition (PolyScape vs baseline)
- Recruitment: GT participant pool (SONA) or Prolific (~$300)
- Counterbalancing: 6 task-type orderings (3! = 6), 2 participants each

#### Step 4.2: 9 Study Tasks (3 types x 3 instances)
- **Identification** (city scale): "Which neighborhood has the highest predicted revenue under Scenario A?"
- **Comparison** (district scale): "For Midtown vs Decatur, which features cause the largest score difference?"
- **Justification** (street scale): "Select the best site from three candidates and name the two features most supporting your choice."

#### Step 4.3: Surveys
- **Per-task**: 7-point Likert confidence (immediately after each task answer)
- **Post-session**: Raw NASA-TLX (6 sliders, 0-100 step 5) + SUS (10 items, 5-point)
- All embedded in the study app, logged to same SQLite backend

#### Step 4.4: Data Collection
- Auto-log: task accuracy, completion time, interaction traces
- Manual: survey responses
- Expected output: `study_results.db` (SQLite)

---

### Phase 5: Analysis & Report (Week 5)

#### Step 5.1: Statistical Analysis

```python
import pingouin as pg
from scipy.stats import mannwhitneyu, shapiro, ttest_ind
from statsmodels.stats.multitest import multipletests
import numpy as np

# Mann-Whitney U for accuracy (non-parametric, appropriate for N=12)
stat, p = mannwhitneyu(polyscape_accuracy, baseline_accuracy)

# Log-transformed t-test for completion time
log_ps = np.log(polyscape_times)
log_bl = np.log(baseline_times)
t, p = ttest_ind(log_ps, log_bl)

# Effect sizes
d = pg.compute_effsize(polyscape, baseline, eftype='cohen')
# rank-biserial for Mann-Whitney
result = pg.mwu(polyscape, baseline)  # returns r_rb

# Bonferroni correction for multiple comparisons
reject, p_corrected, _, _ = multipletests(p_values, method='holm')
```

#### Step 5.2: Write Report
- Technique description: scale-linked encoding paradigm formalization
- Prototype implementation details
- Study results: H1-H4 hypothesis testing
- Discussion: limitations (N=12 detects only large effects d >= 1.2), future work

---

## Key Files

| File | Operation | Description |
|------|-----------|-------------|
| `frontend/js/app.js` | Create | Main entry, SemanticZoomController, Mapbox init |
| `frontend/js/city-scale.js` | Create | Deck.gl hex layers, d3-contour pipeline |
| `frontend/js/district-scale.js` | Create | SHAP radial lenses via mapboxgl.Marker |
| `frontend/js/street-scale.js` | Create | Profile cards, waterfall charts, sparklines |
| `frontend/js/study-logger.js` | Create | Task timing, interaction logging, survey UI |
| `frontend/index.html` | Create | PolyScape single-page app |
| `frontend/baseline.html` | Create | Multi-panel dashboard baseline |
| `backend/main.py` | Create | FastAPI endpoints (/predict, /explain, /scenarios) |
| `backend/model.py` | Create | XGBoost model + TreeSHAP computation |
| `backend/explainer.py` | Create | SHAP + GeoShapley wrapper |
| `backend/data_pipeline/census.py` | Create | Census ACS fetcher via censusdis |
| `backend/data_pipeline/overture.py` | Create | Overture Maps POI extraction |
| `backend/data_pipeline/osmnx_features.py` | Create | Walk score, transit, road density |
| `backend/data_pipeline/hex_grid.py` | Create | H3 grid generation + feature join |
| `backend/cache.py` | Create | Redis caching layer |
| `study/tasks.json` | Create | 9 study tasks with ground truth answers |
| `study/analysis.py` | Create | scipy + pingouin statistical analysis |

---

## Risks and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SafeGraph data unavailable (paid) | High | High | Use Census LODES + Overture Maps as free alternatives (validated in research) |
| GeoShapley too slow for real-time | Medium | Low | Pre-compute offline, cache in Redis; use TreeSHAP for interactive `/explain` endpoint |
| N=12 per condition underpowered | High | Medium | Report effect sizes (Cohen's d, rank-biserial r) regardless of p-values; consider mixed-effects models with per-task repetitions |
| Mapbox token costs at scale | Low | Low | Free tier (50K map loads/month) sufficient for study; use dark-gray-vector style |
| D3 contour computation too slow | Low | Low | 200x200 grid = ~20-50ms; can offload to Web Worker if needed |
| Deck.gl + Mapbox integration issues | Medium | Medium | Use `MapboxOverlay({ interleaved: true })` pattern; fallback to pure Mapbox GeoJSON layers for hex grid |
| No JS SHAP waterfall library | Confirmed | Low | Build custom in D3 (~80 lines of code, pattern is horizontal diverging stacked bar) |
| Census ACS data freshness | Low | Low | ACS 5-Year 2020-2024 is most current; sufficient for prototype |

---

## Dependencies (requirements.txt)

### Python Backend
```
fastapi>=0.115.0
uvicorn>=0.30.0
xgboost>=2.1.0
shap>=0.46.0
geoshapley>=0.1.0
h3>=4.1.0
geopandas>=1.0.0
censusdis
overturemaps
osmnx>=2.1.0
pygris
redis>=5.0.0
pyarrow>=14.0.0
pandas>=2.2.0
numpy>=1.26.0
scikit-learn>=1.4.0
scipy>=1.12.0
pingouin>=0.5.4
statsmodels>=0.14.0
```

### Frontend (CDN or npm)
```
mapbox-gl@^3.9.0
@deck.gl/core@^9.1.0
@deck.gl/aggregation-layers@^9.1.0
@deck.gl/mapbox@^9.1.0
d3@^7.9.0
d3-contour@^4.0.2
h3-js@^4.2.0
@turf/turf@^7.1.0
```

---

## Timeline Summary

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 1 | Data pipeline: H3 grid, Census, Overture, LODES | `hex_features.parquet` (14K hexes x 14 features) |
| 2 | Model training: XGBoost + SHAP + FastAPI | Working API with `/predict` and `/explain` |
| 3 | PolyScape frontend: 3 scale bands fully functional | Interactive prototype with semantic zoom |
| 3-4 | Baseline dashboard + pilot test (3 volunteers) | Both conditions ready for study |
| 4-5 | Formal user study (N=24) + data collection | `study_results.db` |
| 5 | Analysis + final report | Paper with technique description + study findings |
