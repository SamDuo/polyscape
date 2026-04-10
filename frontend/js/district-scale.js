/**
 * PolyScape — District Scale Layer (12 <= zoom < 15)
 * SHAP radial-bar lenses at hex centroids.
 * Click lens → fly to street scale + open popup card.
 */

class DistrictScaleLayer {
  constructor() {
    this.map = null;
    this.markers = [];
    this._explanations = [];
    this.visible = false;
    this._tooltip = null;
    this._loading = false;
    this._lastBboxKey = '';
  }

  init(mapInstance) {
    this.map = mapInstance;
    this._tooltip = document.createElement('div');
    this._tooltip.className = 'shap-tooltip';
    this._tooltip.style.display = 'none';
    document.body.appendChild(this._tooltip);
  }

  async loadForBbox(bbox) {
    const key = bbox.map(v => v.toFixed(3)).join(',');
    if (key === this._lastBboxKey || this._loading) return;
    this._lastBboxKey = key;
    this._loading = true;

    try {
      const pResp = await fetch(`/predict?bbox=${bbox.join(',')}&res=8`);
      if (!pResp.ok) return;
      const geojson = await pResp.json();

      const allHexes = geojson.features.map(f => f.properties.h3_index);
      const step = Math.max(1, Math.floor(allHexes.length / 80));
      const sampled = allHexes.filter((_, i) => i % step === 0).slice(0, 80);
      if (!sampled.length) return;

      const eResp = await fetch('/explain/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ h3_indices: sampled }),
      });
      if (!eResp.ok) return;
      const data = await eResp.json();
      this._explanations = data.explanations || [];
      if (this.visible) this.renderLenses(this._explanations);
    } catch (err) { console.warn('DistrictScale: loadForBbox failed', err); }
    finally { this._loading = false; }
  }

  renderLenses(explanations) {
    this.markers.forEach(m => m.remove());
    this.markers = [];

    for (const entry of explanations) {
      const { h3_index, shap_values, centroid, score } = entry;
      if (!shap_values || !centroid) continue;

      const lngLat = [centroid.lng, centroid.lat];
      const el = this._createLensSVG(shap_values, score);
      el.classList.add('shap-lens');

      el.addEventListener('mouseenter', e => this._showTip(e, shap_values, score));
      el.addEventListener('mousemove', e => { this._tooltip.style.left = e.pageX + 12 + 'px'; this._tooltip.style.top = e.pageY - 8 + 'px'; });
      el.addEventListener('mouseleave', () => { this._tooltip.style.display = 'none'; });

      el.addEventListener('click', () => {
        this.map.flyTo({ center: lngLat, zoom: 16, duration: 1200 });
        this.map.once('moveend', () => { if (streetLayer) streetLayer.openCardForHex(h3_index, lngLat); });
      });

      const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
        .setLngLat(lngLat).addTo(this.map);
      marker._h3Index = h3_index;

      // If band is not active, hide immediately (safety net)
      if (!this.visible) el.style.display = 'none';

      this.markers.push(marker);
    }
  }

  _createLensSVG(shapValues, score) {
    const ns = 'http://www.w3.org/2000/svg';
    const size = 60, innerR = 8, maxR = 28, gap = 0.04;
    const top5 = shapValues.slice(0, 5);

    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    svg.setAttribute('width', size); svg.setAttribute('height', size);

    const g = document.createElementNS(ns, 'g');
    g.setAttribute('transform', `translate(${size / 2},${size / 2})`);
    svg.appendChild(g);

    const bg = document.createElementNS(ns, 'circle');
    bg.setAttribute('r', innerR);
    bg.setAttribute('fill', score > 0.5 ? 'rgba(102,187,106,0.25)' : 'rgba(0,191,165,0.18)');
    bg.setAttribute('stroke', 'rgba(0,191,165,0.35)'); bg.setAttribute('stroke-width', '0.5');
    g.appendChild(bg);

    if (score != null) {
      const t = document.createElementNS(ns, 'text');
      t.setAttribute('text-anchor', 'middle'); t.setAttribute('dy', '.35em');
      t.setAttribute('fill', '#e0e6ed'); t.setAttribute('font-size', '6'); t.setAttribute('font-weight', '600');
      t.textContent = score.toFixed(2);
      g.appendChild(t);
    }

    if (!top5.length) return svg;
    const maxAbs = Math.max(...top5.map(s => Math.abs(s.value)), 0.001);
    const slice = (2 * Math.PI) / top5.length;
    const arc = d3.arc();

    top5.forEach((item, i) => {
      const sA = i * slice + gap / 2, eA = (i + 1) * slice - gap / 2;
      const oR = innerR + (Math.abs(item.value) / maxAbs) * (maxR - innerR);
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', arc({ innerRadius: innerR, outerRadius: oR, startAngle: sA, endAngle: eA }));
      path.setAttribute('fill', item.value >= 0 ? '#66bb6a' : '#ef5350');
      path.setAttribute('opacity', '0.8');
      g.appendChild(path);
    });

    return svg;
  }

  _showTip(event, shapValues, score) {
    let html = score != null ? `<div style="margin-bottom:4px;font-weight:600;color:#00bfa5">Score: ${score.toFixed(3)}</div>` : '';
    html += shapValues.slice(0, 5).map(s => {
      const cls = s.value >= 0 ? 'positive' : 'negative';
      return `<span class="feature-name">${s.feature}:</span> <span class="feature-value ${cls}">${(s.value >= 0 ? '+' : '') + s.value.toFixed(4)}</span>`;
    }).join('<br>');
    this._tooltip.innerHTML = html;
    this._tooltip.style.display = 'block';
    this._tooltip.style.left = event.pageX + 12 + 'px';
    this._tooltip.style.top = event.pageY - 8 + 'px';
  }

  /**
   * Show ALL lens markers. Called when entering district band.
   */
  show() {
    this.visible = true;
    this.markers.forEach(m => {
      m.getElement().style.display = '';
      m.getElement().style.opacity = '1';
      m.getElement().style.pointerEvents = 'auto';
    });
  }

  /**
   * Hide ALL lens markers. Called when leaving district band.
   * Uses display:none so they don't intercept events or render at all.
   */
  hide() {
    this.visible = false;
    this.markers.forEach(m => {
      m.getElement().style.display = 'none';
    });
    this._tooltip.style.display = 'none';
  }
}
