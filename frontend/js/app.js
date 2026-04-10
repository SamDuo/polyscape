/**
 * PolyScape — Main entry point
 * Map-first architecture. The CORE innovation:
 * zooming changes the visual encoding, not just the magnification.
 *
 * Scale bands:
 *   City    (z < 12):  H3 hex density fills + contour lines
 *   District (12-15):  SHAP radial-bar lenses
 *   Street  (z >= 15): Popup profile cards on click
 */

let map = null;
let zoomController = null;
let cityLayer = null;
let districtLayer = null;
let streetLayer = null;
let scenarioManager = null;
let is3D = false;

// ── SemanticZoomController ──────────────────────────────────
// Enforces EXACTLY ONE band visible at a time.
// Every transition explicitly shows the target band and hides ALL others.
class SemanticZoomController {
  constructor(m) {
    this.map = m;
    this.currentBand = null;
    this.transitionInProgress = false;
    this.map.on('zoom', () => this._onZoom());
    this.map.on('moveend', () => this._onMoveEnd());
  }

  _getBand(z) { return z < 12 ? 'city' : z < 15 ? 'district' : 'street'; }

  _onZoom() {
    const z = this.map.getZoom();
    const band = this._getBand(z);
    updateBriefBar(band, z);
    if (band !== this.currentBand && !this.transitionInProgress) {
      this._transition(band);
    }
  }

  async _transition(toBand) {
    this.transitionInProgress = true;
    const prev = this.currentBand;
    this.currentBand = toBand;

    // ── HIDE everything that is NOT the target band ──
    if (toBand !== 'city'    && cityLayer)     cityLayer.hide();
    if (toBand !== 'district' && districtLayer) districtLayer.hide();
    if (toBand !== 'street'  && streetLayer)   streetLayer.hide();

    // ── SHOW the target band ──
    if (toBand === 'city'     && cityLayer)     cityLayer.show();
    if (toBand === 'district' && districtLayer) districtLayer.show();
    if (toBand === 'street'   && streetLayer)   streetLayer.show();

    // Load data for the new band
    this._loadBandData(toBand);

    // Debounce rapid transitions
    await new Promise(r => setTimeout(r, 350));
    this.transitionInProgress = false;
  }

  _loadBandData(band) {
    const bbox = getMapBbox();
    if (band === 'city'     && cityLayer)     cityLayer.loadHexData(bbox);
    if (band === 'district' && districtLayer) districtLayer.loadForBbox(bbox);
    // Street band loads on click, not on pan
  }

  _onMoveEnd() {
    if (this.currentBand) this._loadBandData(this.currentBand);
  }
}

// ── Helpers ─────────────────────────────────────────────────
function getMapBbox() {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

function updateBriefBar(band, zoom) {
  const el = document.getElementById('brief-band');
  if (el) el.textContent = band.charAt(0).toUpperCase() + band.slice(1) + ' (z' + zoom.toFixed(0) + ')';
}

// ── 3D Toggle ───────────────────────────────────────────────
function toggle3D() {
  is3D = !is3D;
  document.getElementById('btn-3d')?.classList.toggle('active', is3D);
  map.easeTo(is3D ? { pitch: 55, bearing: -25, duration: 800 } : { pitch: 0, bearing: 0, duration: 800 });
  if (cityLayer) cityLayer.set3D(is3D);
}

// ── Toolbar ─────────────────────────────────────────────────
function setupToolbar() {
  const btnFilters = document.getElementById('btn-filters');
  const btnLayers  = document.getElementById('btn-layers');
  const filtersDD  = document.getElementById('filters-dropdown');
  const layersDD   = document.getElementById('layers-dropdown');

  btnFilters.addEventListener('click', (e) => {
    e.stopPropagation();
    const show = filtersDD.style.display === 'none';
    filtersDD.style.display = show ? 'block' : 'none';
    layersDD.style.display = 'none';
    btnFilters.classList.toggle('active', show);
    btnLayers.classList.remove('active');
  });

  btnLayers.addEventListener('click', (e) => {
    e.stopPropagation();
    const show = layersDD.style.display === 'none';
    layersDD.style.display = show ? 'block' : 'none';
    filtersDD.style.display = 'none';
    btnLayers.classList.toggle('active', show);
    btnFilters.classList.remove('active');
  });

  document.getElementById('btn-3d').addEventListener('click', toggle3D);

  // Close dropdowns when clicking the map
  map.getCanvas().addEventListener('click', () => {
    filtersDD.style.display = 'none';
    layersDD.style.display = 'none';
    btnFilters.classList.remove('active');
    btnLayers.classList.remove('active');
  });

  // ── Layer toggles ──
  document.getElementById('layer-hexes')?.addEventListener('change', (e) => {
    if (cityLayer) cityLayer.setHexVisible(e.target.checked);
  });
  document.getElementById('layer-contours')?.addEventListener('change', (e) => {
    if (cityLayer) cityLayer.setContoursVisible(e.target.checked);
  });
  document.getElementById('layer-lenses')?.addEventListener('change', (e) => {
    if (districtLayer) {
      if (e.target.checked) districtLayer.show();
      else districtLayer.hide();
    }
  });
  document.getElementById('layer-satellite')?.addEventListener('change', (e) => {
    const style = e.target.checked
      ? 'mapbox://styles/mapbox/satellite-streets-v12'
      : 'mapbox://styles/mapbox/dark-v11';
    map.setStyle(style);
    // Re-add contour source/layers after style change
    map.once('style.load', () => {
      if (cityLayer) cityLayer.readdMapboxLayers();
    });
  });
}

// ── Compare Panel ───────────────────────────────────────────
function updateCompareButton() {
  if (!streetLayer) return;
  const count = streetLayer.pinnedCards.length;
  const el = document.getElementById('brief-pinned-count');
  const btn = document.getElementById('btn-compare');
  if (el) el.textContent = count + ' pinned';
  if (btn) btn.style.display = count >= 2 ? 'block' : 'none';
}

function showComparePanel() {
  if (!streetLayer || streetLayer.pinnedCards.length < 2) return;
  const panel = document.getElementById('compare-panel');
  const body = document.getElementById('compare-body');
  if (!panel || !body) return;

  const cards = streetLayer.pinnedCards;
  const metrics = ['Score', 'Pop Density', 'Competitors', 'Income', 'Walk Score'];

  const rows = {};
  cards.forEach(m => {
    const d = m._siteData || {};
    rows[m._h3Index] = {
      'Score': d.scoreA?.toFixed(3) ?? '--',
      'Pop Density': d.pop_density ? Math.round(d.pop_density).toLocaleString() : '--',
      'Competitors': d.competitors ?? '--',
      'Income': d.income ? '$' + Math.round(d.income).toLocaleString() : '--',
      'Walk Score': d.walk_score ?? '--',
    };
  });

  let html = '<table class="compare-table"><thead><tr><th></th>';
  cards.forEach(m => { html += `<th>${m._h3Index?.slice(0, 10)}...</th>`; });
  html += '</tr></thead><tbody>';
  metrics.forEach(metric => {
    html += `<tr><td>${metric}</td>`;
    cards.forEach(m => { html += `<td>${rows[m._h3Index]?.[metric] ?? '--'}</td>`; });
    html += '</tr>';
  });
  html += '</tbody></table>';
  body.innerHTML = html;
  panel.style.display = 'block';
}

// ── Init ────────────────────────────────────────────────────
async function initApp() {
  let token = '';
  try { const r = await fetch('/api/config'); if (r.ok) { token = (await r.json()).mapboxToken || ''; } } catch {}
  if (!token) { document.body.innerHTML = '<div style="color:#ef5350;padding:40px;font-family:system-ui">MAPBOX_TOKEN not set.</div>'; return; }

  mapboxgl.accessToken = token;
  map = new mapboxgl.Map({
    container: 'map', style: 'mapbox://styles/mapbox/dark-v11',
    center: [-84.388, 33.749], zoom: 10,
    pitch: 0, bearing: 0, antialias: true,
  });
  map.addControl(new mapboxgl.NavigationControl(), 'top-left');

  map.on('load', () => {
    cityLayer = new CityScaleLayer();
    cityLayer.init(map);

    districtLayer = new DistrictScaleLayer();
    districtLayer.init(map);

    streetLayer = new StreetScaleLayer();
    streetLayer.init(map);

    scenarioManager = new ScenarioManager();
    scenarioManager.init();

    setupToolbar();

    document.getElementById('btn-compare')?.addEventListener('click', showComparePanel);
    document.getElementById('close-compare')?.addEventListener('click', () => {
      document.getElementById('compare-panel').style.display = 'none';
    });

    // Start zoom controller — initial band is 'city' at z=10
    zoomController = new SemanticZoomController(map);
    zoomController._transition('city');
  });
}

document.addEventListener('DOMContentLoaded', initApp);
