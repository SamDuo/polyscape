/**
 * PolyScape — Main entry point + SemanticZoomController
 *
 * Initializes Mapbox GL JS, manages zoom-driven semantic transitions
 * across three scale bands: city (z<12), district (12<=z<15), street (z>=15).
 */

// ── Mapbox Token ────────────────────────────────────────────
// Get a free token at https://account.mapbox.com/access-tokens/
const MAPBOX_TOKEN_PLACEHOLDER = 'YOUR_MAPBOX_TOKEN';

let map = null;
let zoomController = null;

// Scale layer instances (populated after map load)
let cityLayer = null;
let districtLayer = null;
let streetLayer = null;
let scenarioManager = null;

/**
 * SemanticZoomController
 * Monitors map zoom level and triggers visual transitions between
 * city / district / street scale bands.
 */
class SemanticZoomController {
  constructor(mapInstance) {
    this.map = mapInstance;
    this.currentBand = null;
    this.transitionInProgress = false;
    this._indicatorEl = document.getElementById('scale-indicator');

    this.map.on('zoom', () => this.update());
    this.map.on('moveend', () => this._onMoveEnd());
  }

  /** Determine band from current zoom level. */
  _getBand(zoom) {
    if (zoom < 12) return 'city';
    if (zoom < 15) return 'district';
    return 'street';
  }

  /** Called on every zoom event. */
  update() {
    const zoom = this.map.getZoom();
    const newBand = this._getBand(zoom);

    this._updateIndicator(newBand);
    this._updateStats(newBand, zoom);

    if (newBand !== this.currentBand && !this.transitionInProgress) {
      this.transition(this.currentBand, newBand);
    }
  }

  /** Orchestrate layer visibility changes with smooth fades. */
  async transition(fromBand, toBand) {
    this.transitionInProgress = true;

    // Hide outgoing layers
    if (fromBand === 'city' && cityLayer) cityLayer.hide();
    if (fromBand === 'district' && districtLayer) districtLayer.hide();
    if (fromBand === 'street' && streetLayer) streetLayer.hide();

    // Show incoming layers
    if (toBand === 'city' && cityLayer) cityLayer.show();
    if (toBand === 'district' && districtLayer) districtLayer.show();
    if (toBand === 'street' && streetLayer) streetLayer.show();

    this.currentBand = toBand;

    // Allow transition animation to settle
    await new Promise((r) => setTimeout(r, 450));
    this.transitionInProgress = false;
  }

  /** Update the scale indicator badge. */
  _updateIndicator(band) {
    if (!this._indicatorEl) return;
    const labels = { city: 'City', district: 'District', street: 'Street' };
    this._indicatorEl.textContent = labels[band] || '';
  }

  /** Update the stats bar. */
  _updateStats(band, zoom) {
    const bandEl = document.getElementById('stat-band');
    const zoomEl = document.getElementById('stat-zoom');
    if (bandEl) bandEl.textContent = band.charAt(0).toUpperCase() + band.slice(1);
    if (zoomEl) zoomEl.textContent = zoom.toFixed(1);
  }

  /** Refresh visible data after map stops moving. */
  _onMoveEnd() {
    const band = this._getBand(this.map.getZoom());
    if (band === 'city' && cityLayer) {
      const bounds = this.map.getBounds();
      const bbox = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ];
      cityLayer.loadHexData(bbox);
    }
    if (band === 'district' && districtLayer) {
      districtLayer.updateVisibility();
    }
  }
}

/**
 * Fetch Mapbox token from backend, with placeholder fallback.
 */
async function fetchMapboxToken() {
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    return data.mapboxToken || data.MAPBOX_TOKEN || MAPBOX_TOKEN_PLACEHOLDER;
  } catch {
    console.warn(
      'Could not fetch token from /api/config — using placeholder. ' +
      'Set your Mapbox token at https://account.mapbox.com/access-tokens/'
    );
    return MAPBOX_TOKEN_PLACEHOLDER;
  }
}

/**
 * Boot the application.
 */
async function initApp() {
  const token = await fetchMapboxToken();
  mapboxgl.accessToken = token;

  map = new mapboxgl.Map({
    container: 'map',
    style: 'mapbox://styles/mapbox/dark-v11',
    center: [-84.388, 33.749],
    zoom: 10,
    pitch: 0,
    bearing: 0,
    antialias: true,
  });

  map.addControl(new mapboxgl.NavigationControl(), 'top-left');

  map.on('load', () => {
    // Initialize scale layers
    cityLayer = new CityScaleLayer();
    cityLayer.init(map);

    districtLayer = new DistrictScaleLayer();
    districtLayer.init(map);

    streetLayer = new StreetScaleLayer();
    streetLayer.init(map);

    // Initialize scenario controls
    scenarioManager = new ScenarioManager();
    scenarioManager.init();

    // Start zoom controller (triggers initial transition)
    zoomController = new SemanticZoomController(map);
    zoomController.update();
  });
}

// ── Kick off ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initApp);
