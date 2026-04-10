/**
 * PolyScape — District Scale Layer (12 <= zoom < 15)
 *
 * Renders SHAP radial-bar "lenses" at hex centroids using D3 arc
 * generators inside SVG markers on the Mapbox map.
 */

class DistrictScaleLayer {
  constructor() {
    this.map = null;
    this.markers = [];         // active mapboxgl.Marker instances
    this._explanations = [];   // cached SHAP data
    this.visible = false;
    this._tooltip = null;
  }

  /**
   * Store map reference and create shared tooltip element.
   */
  init(mapInstance) {
    this.map = mapInstance;

    this._tooltip = document.createElement('div');
    this._tooltip.className = 'shap-tooltip';
    this._tooltip.style.display = 'none';
    document.body.appendChild(this._tooltip);
  }

  /**
   * Batch-fetch SHAP explanations for visible hex centroids.
   */
  async loadExplanations(visibleHexes) {
    try {
      const resp = await fetch('/explain/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hexes: visibleHexes }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      this._explanations = data.explanations || [];

      if (this.visible) {
        this.renderLenses(this._explanations);
      }
    } catch (err) {
      console.warn('DistrictScaleLayer: loadExplanations failed', err);
    }
  }

  /**
   * Create or update SHAP lens markers for each explanation.
   */
  renderLenses(explanations) {
    // Clear existing markers
    this.markers.forEach((m) => m.remove());
    this.markers = [];

    for (const entry of explanations) {
      const { h3_index, shap_values, centroid } = entry;
      if (!shap_values || !centroid) continue;

      const lngLat = [centroid.lng, centroid.lat];

      // Build SVG element
      const el = this.createLensSVG(shap_values);
      el.classList.add('shap-lens');

      // Hover → tooltip
      el.addEventListener('mouseenter', (e) => this._showTooltip(e, shap_values));
      el.addEventListener('mousemove', (e) => this._moveTooltip(e));
      el.addEventListener('mouseleave', () => this._hideTooltip());

      // Click → fly to street scale
      el.addEventListener('click', () => {
        this.map.flyTo({ center: lngLat, zoom: 16, duration: 1200 });
      });

      const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
        .setLngLat(lngLat)
        .addTo(this.map);

      marker._h3Index = h3_index;
      this.markers.push(marker);
    }
  }

  /**
   * Generate a radial-bar SVG element from SHAP values.
   * Each of the top-5 features gets an arc segment.
   * Positive SHAP → green (#66bb6a), Negative → red (#ef5350).
   * All bars extend outward; color encodes direction.
   *
   * @param {Array<{feature: string, value: number}>} shapValues
   * @returns {HTMLElement} SVG element (60x60 px)
   */
  createLensSVG(shapValues) {
    const ns = 'http://www.w3.org/2000/svg';
    const size = 60;
    const innerR = 8;
    const maxOuterR = 28;
    const gap = 0.04; // radians between bars
    const top5 = shapValues.slice(0, 5);

    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);

    const g = document.createElementNS(ns, 'g');
    g.setAttribute('transform', `translate(${size / 2},${size / 2})`);
    svg.appendChild(g);

    // Background circle
    const bg = document.createElementNS(ns, 'circle');
    bg.setAttribute('r', innerR);
    bg.setAttribute('fill', 'rgba(17,23,34,0.7)');
    bg.setAttribute('stroke', 'rgba(0,191,165,0.3)');
    bg.setAttribute('stroke-width', '0.5');
    g.appendChild(bg);

    if (top5.length === 0) return svg;

    const maxAbsVal = Math.max(...top5.map((s) => Math.abs(s.value)), 0.01);
    const sliceAngle = (2 * Math.PI) / top5.length;

    const arcGen = d3.arc();

    top5.forEach((item, i) => {
      const startAngle = i * sliceAngle + gap / 2;
      const endAngle = (i + 1) * sliceAngle - gap / 2;
      const ratio = Math.abs(item.value) / maxAbsVal;
      const outerR = innerR + ratio * (maxOuterR - innerR);
      const color = item.value >= 0 ? '#66bb6a' : '#ef5350';

      const pathD = arcGen({
        innerRadius: innerR,
        outerRadius: outerR,
        startAngle,
        endAngle,
      });

      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', pathD);
      path.setAttribute('fill', color);
      path.setAttribute('opacity', '0.8');
      g.appendChild(path);
    });

    return svg;
  }

  /**
   * Show tooltip with feature names and SHAP values.
   */
  _showTooltip(event, shapValues) {
    const top5 = shapValues.slice(0, 5);
    const rows = top5.map((s) => {
      const cls = s.value >= 0 ? 'positive' : 'negative';
      const sign = s.value >= 0 ? '+' : '';
      return `<span class="feature-name">${s.feature}:</span> <span class="feature-value ${cls}">${sign}${s.value.toFixed(3)}</span>`;
    });
    this._tooltip.innerHTML = rows.join('<br>');
    this._tooltip.style.display = 'block';
    this._moveTooltip(event);
  }

  _moveTooltip(event) {
    this._tooltip.style.left = event.pageX + 12 + 'px';
    this._tooltip.style.top = event.pageY - 8 + 'px';
  }

  _hideTooltip() {
    this._tooltip.style.display = 'none';
  }

  /**
   * Show district-scale markers.
   */
  show() {
    this.visible = true;
    this.markers.forEach((m) => {
      m.getElement().style.opacity = '1';
      m.getElement().style.pointerEvents = 'auto';
    });
    this.updateVisibility();
  }

  /**
   * Hide district-scale markers.
   */
  hide() {
    this.visible = false;
    this.markers.forEach((m) => {
      m.getElement().style.opacity = '0';
      m.getElement().style.pointerEvents = 'none';
    });
  }

  /**
   * Only show markers within current viewport (performance cull).
   */
  updateVisibility() {
    if (!this.visible) return;

    const bounds = this.map.getBounds();
    const visibleHexes = [];

    for (const marker of this.markers) {
      const lngLat = marker.getLngLat();
      const inView = bounds.contains(lngLat);
      marker.getElement().style.display = inView ? '' : 'none';
      if (inView && marker._h3Index) {
        visibleHexes.push(marker._h3Index);
      }
    }

    // If we have no explanations yet but have hex data from city layer,
    // attempt to load them
    if (this._explanations.length === 0 && visibleHexes.length === 0) {
      const bbox = [
        bounds.getWest(), bounds.getSouth(),
        bounds.getEast(), bounds.getNorth(),
      ];
      this._fetchForBbox(bbox);
    }
  }

  /**
   * Attempt to fetch explanations for hexes in a bounding box.
   */
  async _fetchForBbox(bbox) {
    try {
      const resp = await fetch(`/explain?bbox=${bbox.join(',')}`);
      if (!resp.ok) return;
      const data = await resp.json();
      this._explanations = data.explanations || [];
      if (this.visible) {
        this.renderLenses(this._explanations);
      }
    } catch {
      // silent — backend may not be running
    }
  }
}
