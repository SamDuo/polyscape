/**
 * PolyScape — Street Scale Layer (zoom >= 15)
 * Popup cards (glassmorphism) anchored above markers.
 * Pin up to 4 cards for compare mode.
 */

class StreetScaleLayer {
  constructor() {
    this.map = null;
    this.pinnedCards = [];
    this._activeCards = [];
  }

  init(mapInstance) {
    this.map = mapInstance;
    this.map.on('click', e => {
      if (!zoomController || zoomController.currentBand !== 'street') return;
      try {
        const h3Index = h3.latLngToCell(e.lngLat.lat, e.lngLat.lng, 8);
        this.openCardForHex(h3Index, [e.lngLat.lng, e.lngLat.lat]);
      } catch {}
    });
  }

  async openCardForHex(h3Index, lngLat) {
    if (this._activeCards.some(m => m._h3Index === h3Index)) return;

    try {
      const [exR, ftR] = await Promise.all([
        fetch(`/explain/${h3Index}`),
        fetch(`/features/${h3Index}`),
      ]);
      if (!exR.ok) return;
      const explain = await exR.json();
      const features = ftR.ok ? await ftR.json() : {};

      const siteData = {
        name: h3Index.slice(0, 12) + '...',
        scoreA: explain.score ?? 0,
        pop_density: features.population_density,
        competitors: features.competitor_count,
        income: features.median_income,
        walk_score: features.walk_score,
      };

      this._createPopup(lngLat, siteData, explain.shap_values, h3Index, explain.base_value);
    } catch (err) { console.warn('StreetScale: openCardForHex failed', err); }
  }

  _createPopup(lngLat, data, shapValues, h3Index, baseValue) {
    const score = data.scoreA ?? 0;
    const scoreCls = score > 0.6 ? 'score-high' : score > 0.3 ? 'score-med' : 'score-low';

    const el = document.createElement('div');
    el.className = 'popup-card';
    el.innerHTML = `
      <div class="popup-header">
        <span class="site-name">${esc(data.name)}</span>
        <span class="score-pill ${scoreCls}">${score.toFixed(2)}</span>
        <div class="popup-actions">
          <button class="pin-btn" title="Pin">&#x1F4CC;</button>
          <button class="close-btn" title="Close">&times;</button>
        </div>
      </div>
      <div class="popup-metrics">
        <div class="popup-metric"><div class="metric-label">Pop Density</div><div class="metric-value">${fmtNum(data.pop_density)}</div></div>
        <div class="popup-metric"><div class="metric-label">Competitors</div><div class="metric-value">${data.competitors ?? '--'}</div></div>
        <div class="popup-metric"><div class="metric-label">Income</div><div class="metric-value">${fmtCurrency(data.income)}</div></div>
        <div class="popup-metric"><div class="metric-label">Walk Score</div><div class="metric-value">${data.walk_score ?? '--'}</div></div>
      </div>
      <div class="popup-waterfall"></div>
      <div class="popup-sparkline"></div>
    `;

    const marker = new mapboxgl.Marker({ element: el, anchor: 'bottom', offset: [0, -8] })
      .setLngLat(lngLat)
      .addTo(this.map);

    marker._isPinned = false;
    marker._h3Index = h3Index;
    marker._siteData = data;

    // Wire buttons
    const pinBtn = el.querySelector('.pin-btn');
    const closeBtn = el.querySelector('.close-btn');

    pinBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (marker._isPinned) { this._unpin(marker); pinBtn.classList.remove('pinned'); }
      else { this._pin(marker); pinBtn.classList.add('pinned'); }
    });

    closeBtn.addEventListener('click', e => {
      e.stopPropagation();
      this._unpin(marker);
      marker.remove();
      this._activeCards = this._activeCards.filter(m => m !== marker);
      updateCompareButton();
    });

    this._activeCards.push(marker);

    // Render D3 charts after DOM attach
    requestAnimationFrame(() => {
      this._renderWaterfall(el.querySelector('.popup-waterfall'), shapValues || [], baseValue ?? 0.19);
      this._renderSparkline(el.querySelector('.popup-sparkline'), score);
    });
  }

  _renderWaterfall(container, shapValues, baseValue) {
    if (!container) return;
    const top = shapValues.slice(0, 6);
    if (!top.length) { container.style.display = 'none'; return; }

    const W = 260, H = 110, ml = 85, mr = 40, mt = 4, mb = 4;
    const iW = W - ml - mr, iH = H - mt - mb;

    const svg = d3.select(container).append('svg')
      .attr('viewBox', `0 0 ${W} ${H}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');
    const g = svg.append('g').attr('transform', `translate(${ml},${mt})`);

    let cum = baseValue;
    const bars = top.map(d => { const s = cum; cum += d.value; return { feature: d.feature, value: d.value, s, e: cum }; });

    const vals = bars.flatMap(b => [b.s, b.e]);
    const x = d3.scaleLinear().domain([Math.min(...vals) - .05, Math.max(...vals) + .05]).range([0, iW]);
    const y = d3.scaleBand().domain(bars.map(b => b.feature)).range([0, iH]).padding(.25);

    bars.forEach((b, i) => {
      if (i < bars.length - 1)
        g.append('line').attr('class', 'connector')
          .attr('x1', x(b.e)).attr('y1', y(b.feature) + y.bandwidth())
          .attr('x2', x(b.e)).attr('y2', y(bars[i + 1].feature));

      const pos = b.value >= 0;
      g.append('rect')
        .attr('x', pos ? x(b.s) : x(b.e))
        .attr('y', y(b.feature))
        .attr('width', Math.max(Math.abs(x(b.e) - x(b.s)), 1))
        .attr('height', y.bandwidth())
        .attr('fill', pos ? '#66bb6a' : '#ef5350')
        .attr('rx', 2).attr('opacity', .85);

      g.append('text').attr('class', 'bar-label')
        .attr('x', -4).attr('y', y(b.feature) + y.bandwidth() / 2).attr('dy', '.35em')
        .attr('text-anchor', 'end').text(trunc(b.feature, 10));

      g.append('text').attr('class', `bar-value ${pos ? 'positive' : 'negative'}`)
        .attr('x', x(b.e) + (pos ? 3 : -3))
        .attr('y', y(b.feature) + y.bandwidth() / 2).attr('dy', '.35em')
        .attr('text-anchor', pos ? 'start' : 'end')
        .text((pos ? '+' : '') + b.value.toFixed(3));
    });
  }

  _renderSparkline(container, score) {
    if (!container) return;
    const data = Array.from({ length: 12 }, (_, i) => Math.max(0, Math.min(1, score + (i - 6) * .02 + (Math.random() - .5) * .05)));
    const W = 200, H = 28;
    const svg = d3.select(container).append('svg')
      .attr('viewBox', `0 0 ${W} ${H}`).attr('preserveAspectRatio', 'xMidYMid meet');
    const gid = 'sg' + Math.random().toString(36).slice(2, 7);
    const grad = svg.append('defs').append('linearGradient').attr('id', gid)
      .attr('x1', '0%').attr('y1', '0%').attr('x2', '0%').attr('y2', '100%');
    grad.append('stop').attr('offset', '0%').attr('stop-color', '#00bfa5');
    grad.append('stop').attr('offset', '100%').attr('stop-color', '#00bfa5').attr('stop-opacity', 0);

    const x = d3.scaleLinear().domain([0, data.length - 1]).range([2, W - 2]);
    const y = d3.scaleLinear().domain([d3.min(data) * .9, d3.max(data) * 1.1]).range([H - 2, 2]);
    svg.append('path').datum(data).attr('class', 'spark-area').attr('d', d3.area().x((_, i) => x(i)).y0(H).y1(d => y(d)).curve(d3.curveMonotoneX)).style('fill', `url(#${gid})`);
    svg.append('path').datum(data).attr('class', 'spark-line').attr('d', d3.line().x((_, i) => x(i)).y(d => y(d)).curve(d3.curveMonotoneX));
  }

  _pin(marker) {
    if (marker._isPinned) return;
    marker._isPinned = true;
    this.pinnedCards.push(marker);
    if (this.pinnedCards.length > 4) {
      const evicted = this.pinnedCards.shift();
      evicted.remove();
      this._activeCards = this._activeCards.filter(m => m !== evicted);
    }
    updateCompareButton();
  }

  _unpin(marker) {
    marker._isPinned = false;
    this.pinnedCards = this.pinnedCards.filter(m => m !== marker);
    updateCompareButton();
  }

  show() { this._activeCards.forEach(m => { m.getElement().style.opacity = '1'; m.getElement().style.pointerEvents = 'auto'; }); }
  hide() { this._activeCards.forEach(m => { if (!m._isPinned) { m.getElement().style.opacity = '0'; m.getElement().style.pointerEvents = 'none'; } }); }
}

// ── Helpers ─────────────────
function esc(s) { const e = document.createElement('span'); e.textContent = s; return e.innerHTML; }
function fmtNum(v) { return v == null ? '--' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : String(v); }
function fmtCurrency(v) { return v == null ? '--' : '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; }
