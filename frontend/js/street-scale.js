/**
 * PolyScape — Street Scale Layer (zoom >= 15)
 *
 * Renders floating profile cards pinned to map locations with
 * D3 waterfall charts, sparklines, and metrics grids.
 */

class StreetScaleLayer {
  constructor() {
    this.map = null;
    this.pinnedCards = [];  // max 4
    this._activeCards = []; // non-pinned, removed on hide
  }

  /**
   * Store map reference.
   */
  init(mapInstance) {
    this.map = mapInstance;
  }

  /**
   * Fetch site details + SHAP from backend.
   */
  async loadSiteDetails(h3Index) {
    try {
      const resp = await fetch(`/explain/${h3Index}`);
      if (!resp.ok) return null;
      return await resp.json();
    } catch (err) {
      console.warn('StreetScaleLayer: loadSiteDetails failed', err);
      return null;
    }
  }

  /**
   * Create a floating profile card at a map location.
   *
   * @param {[number,number]} lngLat
   * @param {Object} siteData - {name, scoreA, scoreB, pop_density, competitors, income, walk_score, monthly}
   * @param {Array<{feature: string, value: number}>} shapValues
   * @returns {mapboxgl.Marker}
   */
  createCard(lngLat, siteData, shapValues) {
    const baseValue = siteData.scoreA ?? 0.5;
    const el = document.createElement('div');
    el.className = 'profile-card';

    el.innerHTML = `
      <div class="card-header">
        <span class="site-name">${this._esc(siteData.name || 'Site')}</span>
        <span class="score-badge scenario-a">${(siteData.scoreA ?? 0).toFixed(2)}</span>
        <span class="score-badge scenario-b">${(siteData.scoreB ?? 0).toFixed(2)}</span>
        <span class="card-actions">
          <button class="pin-btn" title="Pin card">&#x1F4CC;</button>
          <button class="close-btn" title="Close">&times;</button>
        </span>
      </div>
      <div class="waterfall-chart"></div>
      <div class="sparkline"></div>
      <div class="metrics-grid">
        <div class="metric-tile">
          <div class="metric-label">Pop Density</div>
          <div class="metric-value">${this._fmt(siteData.pop_density)}</div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">Competitors</div>
          <div class="metric-value">${siteData.competitors ?? '--'}</div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">Income</div>
          <div class="metric-value">${this._fmtCurrency(siteData.income)}</div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">Walk Score</div>
          <div class="metric-value">${siteData.walk_score ?? '--'}</div>
        </div>
      </div>
    `;

    const marker = new mapboxgl.Marker({
      element: el,
      anchor: 'bottom-left',
      offset: [12, -12],
    })
      .setLngLat(lngLat)
      .addTo(this.map);

    marker._isPinned = false;
    marker._cardEl = el;

    // Wire buttons
    const pinBtn = el.querySelector('.pin-btn');
    const closeBtn = el.querySelector('.close-btn');

    pinBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (marker._isPinned) {
        this.unpinCard(marker);
        pinBtn.classList.remove('pinned');
      } else {
        this.pinCard(marker);
        pinBtn.classList.add('pinned');
      }
    });

    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.unpinCard(marker);
      marker.remove();
      this._activeCards = this._activeCards.filter((m) => m !== marker);
    });

    this._activeCards.push(marker);

    // Render D3 charts after DOM insertion (requestAnimationFrame ensures element is in DOM)
    requestAnimationFrame(() => {
      const waterfallContainer = el.querySelector('.waterfall-chart');
      const sparklineContainer = el.querySelector('.sparkline');
      this.renderWaterfall(waterfallContainer, shapValues || [], baseValue);
      this.renderSparkline(sparklineContainer, siteData.monthly || null, baseValue);
    });

    return marker;
  }

  /**
   * Render horizontal waterfall chart with D3.
   *
   * Bars show cumulative SHAP contributions:
   *   green for positive, red for negative, dashed connectors between bars.
   */
  renderWaterfall(container, shapValues, baseValue) {
    if (!container) return;

    const top = shapValues.slice(0, 6);
    if (top.length === 0) {
      container.style.display = 'none';
      return;
    }

    const width = 240;
    const height = 120;
    const margin = { top: 4, right: 40, bottom: 4, left: 80 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const svg = d3
      .select(container)
      .append('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    // Build cumulative data
    let cumulative = baseValue;
    const bars = top.map((d) => {
      const start = cumulative;
      cumulative += d.value;
      return { feature: d.feature, value: d.value, start, end: cumulative };
    });

    const allVals = bars.flatMap((b) => [b.start, b.end]);
    const xMin = Math.min(...allVals) - 0.05;
    const xMax = Math.max(...allVals) + 0.05;

    const x = d3.scaleLinear().domain([xMin, xMax]).range([0, innerW]);
    const y = d3.scaleBand().domain(bars.map((b) => b.feature)).range([0, innerH]).padding(0.25);

    // Dashed connector lines
    bars.forEach((b, i) => {
      if (i < bars.length - 1) {
        g.append('line')
          .attr('class', 'connector')
          .attr('x1', x(b.end))
          .attr('y1', y(b.feature) + y.bandwidth())
          .attr('x2', x(b.end))
          .attr('y2', y(bars[i + 1].feature));
      }
    });

    // Bars
    bars.forEach((b) => {
      const isPositive = b.value >= 0;
      const barX = isPositive ? x(b.start) : x(b.end);
      const barW = Math.abs(x(b.end) - x(b.start));

      g.append('rect')
        .attr('x', barX)
        .attr('y', y(b.feature))
        .attr('width', Math.max(barW, 1))
        .attr('height', y.bandwidth())
        .attr('fill', isPositive ? '#66bb6a' : '#ef5350')
        .attr('rx', 2)
        .attr('opacity', 0.85);

      // Feature label
      g.append('text')
        .attr('class', 'bar-label')
        .attr('x', -4)
        .attr('y', y(b.feature) + y.bandwidth() / 2)
        .attr('dy', '0.35em')
        .attr('text-anchor', 'end')
        .text(this._truncate(b.feature, 10));

      // Value label
      const sign = b.value >= 0 ? '+' : '';
      g.append('text')
        .attr('class', `bar-value ${isPositive ? 'positive' : 'negative'}`)
        .attr('x', x(b.end) + (isPositive ? 3 : -3))
        .attr('y', y(b.feature) + y.bandwidth() / 2)
        .attr('dy', '0.35em')
        .attr('text-anchor', isPositive ? 'start' : 'end')
        .text(`${sign}${b.value.toFixed(2)}`);
    });
  }

  /**
   * Render sparkline (simple teal line chart).
   * If no monthly data, generate a synthetic 12-month trend.
   */
  renderSparkline(container, monthlyData, score) {
    if (!container) return;

    const data =
      monthlyData ||
      Array.from({ length: 12 }, (_, i) => {
        const trend = score + (i - 6) * 0.02 + (Math.random() - 0.5) * 0.05;
        return Math.max(0, Math.min(1, trend));
      });

    const width = 200;
    const height = 30;

    const svg = d3
      .select(container)
      .append('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    // Gradient definition
    const defs = svg.append('defs');
    const grad = defs
      .append('linearGradient')
      .attr('id', 'sparkGradient')
      .attr('x1', '0%')
      .attr('y1', '0%')
      .attr('x2', '0%')
      .attr('y2', '100%');
    grad.append('stop').attr('offset', '0%').attr('stop-color', '#00bfa5');
    grad.append('stop').attr('offset', '100%').attr('stop-color', '#00bfa5').attr('stop-opacity', 0);

    const x = d3.scaleLinear().domain([0, data.length - 1]).range([2, width - 2]);
    const y = d3
      .scaleLinear()
      .domain([d3.min(data) * 0.9, d3.max(data) * 1.1])
      .range([height - 2, 2]);

    const line = d3
      .line()
      .x((_, i) => x(i))
      .y((d) => y(d))
      .curve(d3.curveMonotoneX);

    const area = d3
      .area()
      .x((_, i) => x(i))
      .y0(height)
      .y1((d) => y(d))
      .curve(d3.curveMonotoneX);

    svg.append('path').datum(data).attr('class', 'spark-area').attr('d', area);
    svg.append('path').datum(data).attr('class', 'spark-line').attr('d', line);
  }

  /**
   * Pin a card (max 4 — evict oldest if over limit).
   */
  pinCard(marker) {
    if (marker._isPinned) return;
    marker._isPinned = true;

    this.pinnedCards.push(marker);

    if (this.pinnedCards.length > 4) {
      const evicted = this.pinnedCards.shift();
      evicted.remove();
      this._activeCards = this._activeCards.filter((m) => m !== evicted);
    }
  }

  /**
   * Unpin a card.
   */
  unpinCard(marker) {
    marker._isPinned = false;
    this.pinnedCards = this.pinnedCards.filter((m) => m !== marker);
  }

  /**
   * Show street-scale cards. Pinned cards are always visible.
   */
  show() {
    for (const m of this._activeCards) {
      m.getElement().style.opacity = '1';
      m.getElement().style.pointerEvents = 'auto';
    }
  }

  /**
   * Hide non-pinned cards; pinned ones stay visible.
   */
  hide() {
    for (const m of this._activeCards) {
      if (!m._isPinned) {
        m.getElement().style.opacity = '0';
        m.getElement().style.pointerEvents = 'none';
      }
    }
  }

  // ── Helpers ────────────────────────────────────────────

  _esc(str) {
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
  }

  _fmt(val) {
    if (val == null) return '--';
    return typeof val === 'number' ? val.toLocaleString() : String(val);
  }

  _fmtCurrency(val) {
    if (val == null) return '--';
    return '$' + Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  _truncate(str, max) {
    return str.length > max ? str.slice(0, max - 1) + '\u2026' : str;
  }
}
