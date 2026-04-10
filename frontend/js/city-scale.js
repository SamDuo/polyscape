/**
 * PolyScape — City Scale Layer (zoom < 12)
 *
 * Renders H3 hex density overlays via Deck.gl and difference contour
 * lines via D3 contours projected back to geographic coordinates.
 */

class CityScaleLayer {
  constructor() {
    this.map = null;
    this.overlay = null;
    this.visible = false;
    this.hexDataA = [];
    this.hexDataB = [];
    this._contourSourceId = 'contour-source';
    this._contourLineId = 'contour-line';
    this._contourGlowId = 'contour-glow';
  }

  /**
   * Initialize Deck.gl overlay on the Mapbox map.
   */
  init(mapInstance) {
    this.map = mapInstance;

    this.overlay = new deck.MapboxOverlay({
      interleaved: true,
      layers: [],
    });
    this.map.addControl(this.overlay);

    // Empty GeoJSON source for contour lines
    this.map.addSource(this._contourSourceId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });

    // Glow underlay
    this.map.addLayer({
      id: this._contourGlowId,
      type: 'line',
      source: this._contourSourceId,
      paint: {
        'line-color': [
          'interpolate', ['linear'], ['get', 'threshold'],
          -0.3, '#ef5350',
          -0.15, '#ef5350',
          0, '#888888',
          0.15, '#66bb6a',
          0.3, '#66bb6a',
        ],
        'line-width': 6,
        'line-opacity': 0,
      },
    });

    // Main contour line
    this.map.addLayer({
      id: this._contourLineId,
      type: 'line',
      source: this._contourSourceId,
      paint: {
        'line-color': [
          'interpolate', ['linear'], ['get', 'threshold'],
          -0.3, '#ef5350',
          -0.15, '#ef5350',
          0, '#888888',
          0.15, '#66bb6a',
          0.3, '#66bb6a',
        ],
        'line-width': 2,
        'line-opacity': 0,
      },
    });
  }

  /**
   * Fetch hex prediction data from backend.
   */
  async loadHexData(bbox) {
    try {
      const qs = `bbox=${bbox.join(',')}&res=8`;
      const resp = await fetch(`/predict?${qs}`);
      if (!resp.ok) return;
      const geojson = await resp.json();

      // Split features by scenario property
      this.hexDataA = geojson.features
        .filter((f) => f.properties.scenario === 'A' || !f.properties.scenario)
        .map((f) => ({
          hex: f.properties.h3_index || f.properties.hex,
          value: f.properties.score ?? f.properties.value ?? 0,
        }));

      this.hexDataB = geojson.features
        .filter((f) => f.properties.scenario === 'B')
        .map((f) => ({
          hex: f.properties.h3_index || f.properties.hex,
          value: f.properties.score ?? f.properties.value ?? 0,
        }));

      if (this.visible) {
        this.renderScenarioLayers(this.hexDataA, this.hexDataB);
        const contours = this.computeContours(this.hexDataA, this.hexDataB);
        this.renderContours(contours);
      }
    } catch (err) {
      console.warn('CityScaleLayer: loadHexData failed', err);
    }
  }

  /**
   * Render two H3HexagonLayer instances for scenario comparison.
   */
  renderScenarioLayers(dataA, dataB) {
    if (!this.overlay) return;

    const maxVal = Math.max(
      ...dataA.map((d) => Math.abs(d.value)),
      ...dataB.map((d) => Math.abs(d.value)),
      1
    );

    const layerA = new deck.H3HexagonLayer({
      id: 'hex-scenario-a',
      data: dataA,
      getHexagon: (d) => d.hex,
      getFillColor: (d) => {
        const t = Math.min(d.value / maxVal, 1);
        return [66, 133, 244, Math.round(t * 100)]; // blue ramp, 40% max
      },
      getElevation: 0,
      extruded: false,
      opacity: this.visible ? 0.4 : 0,
      pickable: true,
    });

    const layerB = new deck.H3HexagonLayer({
      id: 'hex-scenario-b',
      data: dataB,
      getHexagon: (d) => d.hex,
      getFillColor: (d) => {
        const t = Math.min(d.value / maxVal, 1);
        return [255, 152, 0, Math.round(t * 100)]; // orange ramp, 40% max
      },
      getElevation: 0,
      extruded: false,
      opacity: this.visible ? 0.4 : 0,
      pickable: true,
    });

    this.overlay.setProps({ layers: [layerA, layerB] });
  }

  /**
   * Compute per-hex score difference → rasterize → d3.contours().
   */
  computeContours(dataA, dataB) {
    if (!dataA.length && !dataB.length) {
      return { type: 'FeatureCollection', features: [] };
    }

    // Build lookup of hex → value for each scenario
    const mapA = new Map(dataA.map((d) => [d.hex, d.value]));
    const mapB = new Map(dataB.map((d) => [d.hex, d.value]));
    const allHexes = new Set([...mapA.keys(), ...mapB.keys()]);

    // Compute differences and collect centroids
    const hexPoints = [];
    for (const hex of allHexes) {
      const valA = mapA.get(hex) ?? 0;
      const valB = mapB.get(hex) ?? 0;
      try {
        const [lat, lng] = h3.cellToLatLng(hex);
        hexPoints.push({ lng, lat, diff: valB - valA });
      } catch {
        // skip invalid hex
      }
    }

    if (hexPoints.length < 3) {
      return { type: 'FeatureCollection', features: [] };
    }

    // Bounding box of hex centroids
    const lngs = hexPoints.map((p) => p.lng);
    const lats = hexPoints.map((p) => p.lat);
    const bbox = [
      Math.min(...lngs) - 0.01,
      Math.min(...lats) - 0.01,
      Math.max(...lngs) + 0.01,
      Math.max(...lats) + 0.01,
    ];

    // IDW interpolation to grid
    const gridW = 200;
    const gridH = 200;
    const grid = idwInterpolation(hexPoints, gridW, gridH, bbox, 2);

    // Generate contours
    const contourGen = d3.contours().size([gridW, gridH]).thresholds([-0.3, -0.15, 0.15, 0.3]);
    const rawContours = contourGen(grid);

    // Transform grid coords back to geographic
    const dLng = (bbox[2] - bbox[0]) / gridW;
    const dLat = (bbox[3] - bbox[1]) / gridH;

    const features = rawContours.map((contour) => {
      const geoCoords = contour.coordinates.map((ring) =>
        ring.map((polygon) =>
          polygon.map(([gx, gy]) => [bbox[0] + gx * dLng, bbox[1] + gy * dLat])
        )
      );
      return {
        type: 'Feature',
        properties: { threshold: contour.value },
        geometry: {
          type: contour.type,
          coordinates: geoCoords,
        },
      };
    });

    return { type: 'FeatureCollection', features };
  }

  /**
   * Add/update contour lines on the Mapbox source.
   */
  renderContours(contourGeoJSON) {
    const src = this.map.getSource(this._contourSourceId);
    if (src) {
      src.setData(contourGeoJSON);
    }
  }

  /**
   * Show city-scale layers with smooth fade.
   */
  show() {
    this.visible = true;

    // Fade in Deck.gl hex layers
    if (this.hexDataA.length || this.hexDataB.length) {
      this.renderScenarioLayers(this.hexDataA, this.hexDataB);
    }

    // Fade in contour lines
    this.map.setPaintProperty(this._contourLineId, 'line-opacity', 0.9);
    this.map.setPaintProperty(this._contourGlowId, 'line-opacity', 0.2);

    this._updateHexCount();
  }

  /**
   * Hide city-scale layers with smooth fade.
   */
  hide() {
    this.visible = false;

    if (this.overlay) {
      this.overlay.setProps({ layers: [] });
    }

    this.map.setPaintProperty(this._contourLineId, 'line-opacity', 0);
    this.map.setPaintProperty(this._contourGlowId, 'line-opacity', 0);
  }

  /** Update hex count in stats bar. */
  _updateHexCount() {
    const el = document.getElementById('stat-hexes');
    if (el) {
      const count = new Set([
        ...this.hexDataA.map((d) => d.hex),
        ...this.hexDataB.map((d) => d.hex),
      ]).size;
      el.textContent = count.toLocaleString();
    }
  }
}

// ── IDW Interpolation Helper ────────────────────────────────

/**
 * Inverse Distance Weighting interpolation.
 * @param {Array<{lng, lat, diff}>} hexPoints - known data points
 * @param {number} gridWidth  - output grid columns
 * @param {number} gridHeight - output grid rows
 * @param {number[]} bbox     - [west, south, east, north]
 * @param {number} power      - distance weighting power
 * @returns {Float64Array}     flat row-major grid of interpolated values
 */
function idwInterpolation(hexPoints, gridWidth, gridHeight, bbox, power = 2) {
  const grid = new Float64Array(gridWidth * gridHeight);
  const dLng = (bbox[2] - bbox[0]) / gridWidth;
  const dLat = (bbox[3] - bbox[1]) / gridHeight;

  for (let row = 0; row < gridHeight; row++) {
    const lat = bbox[1] + (row + 0.5) * dLat;
    for (let col = 0; col < gridWidth; col++) {
      const lng = bbox[0] + (col + 0.5) * dLng;

      let numerator = 0;
      let denominator = 0;
      let exact = null;

      for (const pt of hexPoints) {
        const dx = lng - pt.lng;
        const dy = lat - pt.lat;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 1e-10) {
          exact = pt.diff;
          break;
        }

        const w = 1 / Math.pow(dist, power);
        numerator += w * pt.diff;
        denominator += w;
      }

      grid[row * gridWidth + col] =
        exact !== null ? exact : denominator > 0 ? numerator / denominator : 0;
    }
  }

  return grid;
}
