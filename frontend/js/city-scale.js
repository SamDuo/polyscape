/**
 * PolyScape — City Scale Layer (zoom < 12)
 *
 * VISIBLE AT THIS BAND:
 *   - H3 hex density fills (Deck.gl H3HexagonLayer, color by suitability score)
 *   - Contour lines (d3-contour → Mapbox GeoJSON line layer, A-B diff)
 *   - 3D mode: extrude hexes by score
 *
 * HIDDEN AT THIS BAND:
 *   - SHAP lens markers (district)
 *   - Profile cards (street)
 */

class CityScaleLayer {
  constructor() {
    this.map = null;
    this.overlay = null;
    this.visible = false;      // is this band currently active?
    this._hexEnabled = true;   // layer toggle from Layers dropdown
    this._contourEnabled = true;
    this._is3D = false;
    this._loading = false;
    this.hexDataA = [];        // base scenario
    this.hexDataB = [];        // what-if scenario
    this._contourSourceId = 'contour-source';
    this._contourLineId = 'contour-line';
    this._contourGlowId = 'contour-glow';
  }

  init(mapInstance) {
    this.map = mapInstance;
    this.overlay = new deck.MapboxOverlay({ interleaved: true, layers: [] });
    this.map.addControl(this.overlay);
    this._addMapboxLayers();
  }

  /** Add Mapbox source + layers for contour lines. */
  _addMapboxLayers() {
    if (this.map.getSource(this._contourSourceId)) return; // already exists
    this.map.addSource(this._contourSourceId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });
    this.map.addLayer({
      id: this._contourGlowId, type: 'line', source: this._contourSourceId,
      paint: {
        'line-color': ['interpolate', ['linear'], ['get', 'threshold'],
          -0.3, '#ef5350', 0, '#888', 0.3, '#66bb6a'],
        'line-width': 5, 'line-opacity': 0, 'line-blur': 3,
      },
    });
    this.map.addLayer({
      id: this._contourLineId, type: 'line', source: this._contourSourceId,
      paint: {
        'line-color': ['interpolate', ['linear'], ['get', 'threshold'],
          -0.3, '#ef5350', 0, '#888', 0.3, '#66bb6a'],
        'line-width': 2, 'line-opacity': 0,
      },
    });
  }

  /** Re-add Mapbox layers after a style change (e.g. satellite toggle). */
  readdMapboxLayers() {
    this._addMapboxLayers();
    if (this.visible) this._applyContourVisibility();
  }

  // ── Layer toggles (from Layers dropdown checkboxes) ──────
  setHexVisible(enabled) {
    this._hexEnabled = enabled;
    if (this.visible) this._renderHexLayers();
    else if (!enabled && this.overlay) this.overlay.setProps({ layers: [] });
  }

  setContoursVisible(enabled) {
    this._contourEnabled = enabled;
    this._applyContourVisibility();
  }

  set3D(enabled) {
    this._is3D = enabled;
    if (this.visible && this.hexDataA.length) this._renderHexLayers();
  }

  // ── Data loading ─────────────────────────────────────────
  async loadHexData(bbox) {
    if (this._loading) return;
    this._loading = true;
    try {
      const resp = await fetch(`/predict?bbox=${bbox.join(',')}&res=8`);
      if (!resp.ok) return;
      const geojson = await resp.json();
      this.hexDataA = geojson.features.map(f => ({
        hex: f.properties.h3_index,
        value: f.properties.score ?? 0,
      }));
      if (!this.hexDataB.length) this.hexDataB = this.hexDataA.map(d => ({ ...d }));
      if (this.visible) this._render();
      this._updateBrief();
    } catch (err) { console.warn('CityScale: loadHexData failed', err); }
    finally { this._loading = false; }
  }

  /** Called by ScenarioManager when what-if is applied. */
  setScenarioB(data) {
    this.hexDataB = data;
    if (this.visible) this._render();
    const el = document.getElementById('brief-scenario');
    if (el) el.textContent = 'What-If Active';
  }

  // ── Rendering ────────────────────────────────────────────
  _render() {
    this._renderHexLayers();
    this._renderContours();
  }

  _renderHexLayers() {
    if (!this.overlay) return;

    // If hex layer is disabled or band is hidden, clear Deck.gl
    if (!this.visible || !this._hexEnabled || !this.hexDataA.length) {
      this.overlay.setProps({ layers: [] });
      return;
    }

    const maxVal = Math.max(...this.hexDataA.map(d => d.value), 0.01);
    const layers = [new deck.H3HexagonLayer({
      id: 'hex-a',
      data: this.hexDataA,
      getHexagon: d => d.hex,
      getFillColor: d => {
        const t = Math.min(d.value / maxVal, 1);
        // Teal ramp: low scores dim, high scores bright
        return [0, Math.round(100 + t * 91), Math.round(100 + t * 65), Math.round(40 + t * 170)];
      },
      extruded: this._is3D,
      getElevation: d => this._is3D ? d.value * 5000 : 0,
      elevationScale: 1,
      opacity: 0.7,
      pickable: true,
      autoHighlight: true,
      highlightColor: [0, 191, 165, 100],
      onHover: info => this._onHover(info),
    })];

    // Scenario B overlay (orange) — only if different from A
    const hasDiff = this.hexDataB.some((b, i) =>
      this.hexDataA[i] && Math.abs(b.value - this.hexDataA[i].value) > 0.001);
    if (hasDiff) {
      const maxB = Math.max(...this.hexDataB.map(d => d.value), 0.01);
      layers.push(new deck.H3HexagonLayer({
        id: 'hex-b', data: this.hexDataB,
        getHexagon: d => d.hex,
        getFillColor: d => {
          const t = Math.min(d.value / maxB, 1);
          return [255, 152, 0, Math.round(t * 120)];
        },
        extruded: this._is3D,
        getElevation: d => this._is3D ? d.value * 5000 : 0,
        opacity: 0.35, pickable: false,
      }));
    }

    this.overlay.setProps({ layers });
  }

  _renderContours() {
    const contours = this._computeContours();
    const src = this.map.getSource(this._contourSourceId);
    if (src) src.setData(contours);
    this._applyContourVisibility();
  }

  _applyContourVisibility() {
    const show = this.visible && this._contourEnabled;
    try {
      this.map.setPaintProperty(this._contourLineId, 'line-opacity', show ? 0.9 : 0);
      this.map.setPaintProperty(this._contourGlowId, 'line-opacity', show ? 0.2 : 0);
    } catch { /* layers may not exist yet */ }
  }

  _onHover(info) {
    const el = document.getElementById('brief-top');
    if (el && info.object) {
      el.textContent = info.object.hex.slice(4, 12) + ' = ' + info.object.value.toFixed(3);
    }
  }

  // ── Contour computation ──────────────────────────────────
  _computeContours() {
    if (!this.hexDataA.length) return { type: 'FeatureCollection', features: [] };
    const mapA = new Map(this.hexDataA.map(d => [d.hex, d.value]));
    const mapB = new Map(this.hexDataB.map(d => [d.hex, d.value]));
    const pts = [];
    for (const [hex, vA] of mapA) {
      const vB = mapB.get(hex) ?? vA;
      try { const [lat, lng] = h3.cellToLatLng(hex); pts.push({ lng, lat, diff: vB - vA }); } catch {}
    }
    const maxDiff = pts.length >= 3 ? Math.max(...pts.map(p => Math.abs(p.diff))) : 0;
    if (maxDiff < 0.001) return { type: 'FeatureCollection', features: [] };

    const lngs = pts.map(p => p.lng), lats = pts.map(p => p.lat);
    const bb = [Math.min(...lngs) - .01, Math.min(...lats) - .01, Math.max(...lngs) + .01, Math.max(...lats) + .01];
    const W = 200, H = 200, grid = idwInterpolation(pts, W, H, bb, 2);
    const raw = d3.contours().size([W, H]).thresholds([-.3, -.15, .15, .3])(grid);
    const dLng = (bb[2] - bb[0]) / W, dLat = (bb[3] - bb[1]) / H;
    return {
      type: 'FeatureCollection',
      features: raw.map(c => ({
        type: 'Feature',
        properties: { threshold: c.value },
        geometry: { type: c.type, coordinates: c.coordinates.map(r => r.map(p => p.map(([gx, gy]) => [bb[0] + gx * dLng, bb[1] + gy * dLat]))) },
      })),
    };
  }

  _updateBrief() {
    if (!this.hexDataA.length) return;
    const best = this.hexDataA.reduce((a, b) => a.value > b.value ? a : b);
    const el = document.getElementById('brief-top');
    if (el) el.textContent = best.hex.slice(4, 12) + ' = ' + best.value.toFixed(3);
    const scEl = document.getElementById('brief-scenario');
    if (scEl && !this.hexDataB.some((b, i) => this.hexDataA[i] && Math.abs(b.value - this.hexDataA[i].value) > 0.001))
      scEl.textContent = 'Base (' + this.hexDataA.length + ' hexes)';
  }

  // ── Show / Hide (called by SemanticZoomController) ───────
  show() {
    this.visible = true;
    if (this.hexDataA.length) this._render();
    else this._applyContourVisibility(); // show contours even before hex data loads
  }

  hide() {
    this.visible = false;
    // Clear Deck.gl hex layers
    if (this.overlay) this.overlay.setProps({ layers: [] });
    // Hide contour Mapbox layers
    this._applyContourVisibility();
  }
}

// ── IDW Interpolation ──────────────────────────────────────
function idwInterpolation(pts, W, H, bb, pow) {
  const grid = new Float64Array(W * H);
  const dLng = (bb[2] - bb[0]) / W, dLat = (bb[3] - bb[1]) / H;
  for (let r = 0; r < H; r++) {
    const lat = bb[1] + (r + .5) * dLat;
    for (let c = 0; c < W; c++) {
      const lng = bb[0] + (c + .5) * dLng;
      let num = 0, den = 0, exact = null;
      for (const p of pts) {
        const d = Math.sqrt((lng - p.lng) ** 2 + (lat - p.lat) ** 2);
        if (d < 1e-10) { exact = p.diff; break; }
        const w = 1 / d ** pow; num += w * p.diff; den += w;
      }
      grid[r * W + c] = exact !== null ? exact : den > 0 ? num / den : 0;
    }
  }
  return grid;
}
