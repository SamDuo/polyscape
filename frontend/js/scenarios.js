/**
 * PolyScape — Scenario Controls
 *
 * Manages the left sidebar with scenario A (base) / B (what-if)
 * sliders and triggers data re-fetch on change.
 */

class ScenarioManager {
  constructor() {
    this.scenarioA = { name: 'Base', overrides: {} };
    this.scenarioB = { name: 'What-If', overrides: {} };
    this._debounceTimer = null;
  }

  /**
   * Build the scenario panel UI inside the left sidebar.
   */
  init() {
    const panel = document.getElementById('scenario-panel');
    if (!panel) return;

    panel.innerHTML = `
      <h2>Scenarios</h2>

      <div class="scenario-section">
        <h3>A &mdash; Base</h3>
        <p class="scenario-desc">
          Current conditions with existing feature values.
          No overrides applied.
        </p>
      </div>

      <div class="scenario-section">
        <h3>B &mdash; What-If</h3>
        <p class="scenario-desc">
          Adjust parameters below to simulate alternative conditions
          and compare against the base scenario.
        </p>

        <label>
          Competitor Count Delta
          <span class="slider-value" id="val-competitor">0</span>
        </label>
        <input type="range" id="slider-competitor"
               min="-5" max="5" step="1" value="0">

        <label>
          Income Multiplier
          <span class="slider-value" id="val-income">1.00</span>
        </label>
        <input type="range" id="slider-income"
               min="0.5" max="1.5" step="0.05" value="1.0">

        <label>
          Transit Boost
          <span class="slider-value" id="val-transit">0.00</span>
        </label>
        <input type="range" id="slider-transit"
               min="0" max="1" step="0.05" value="0">
      </div>

      <button class="apply-btn" id="apply-scenario">Apply Scenario</button>
    `;

    // Wire slider live-update displays
    this._wireSlider('slider-competitor', 'val-competitor', (v) => String(v));
    this._wireSlider('slider-income', 'val-income', (v) => Number(v).toFixed(2));
    this._wireSlider('slider-transit', 'val-transit', (v) => Number(v).toFixed(2));

    // Apply button
    const applyBtn = document.getElementById('apply-scenario');
    if (applyBtn) {
      applyBtn.addEventListener('click', () => this.onScenarioChange());
    }
  }

  /**
   * Read current slider values and return as a dict of overrides.
   */
  getOverrides() {
    const competitor = document.getElementById('slider-competitor');
    const income = document.getElementById('slider-income');
    const transit = document.getElementById('slider-transit');

    return {
      competitor_count_delta: competitor ? Number(competitor.value) : 0,
      income_multiplier: income ? Number(income.value) : 1.0,
      transit_boost: transit ? Number(transit.value) : 0,
    };
  }

  /**
   * Debounced handler: POST overrides, refresh city + district layers.
   */
  onScenarioChange() {
    clearTimeout(this._debounceTimer);

    this._debounceTimer = setTimeout(async () => {
      const overrides = this.getOverrides();
      this.scenarioB.overrides = overrides;

      try {
        // POST custom prediction with overrides
        const resp = await fetch('/predict/custom', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ overrides }),
        });

        if (!resp.ok) {
          console.warn('ScenarioManager: /predict/custom returned', resp.status);
          return;
        }

        const geojson = await resp.json();

        // Update city-scale hex data
        if (typeof cityLayer !== 'undefined' && cityLayer) {
          cityLayer.hexDataB = (geojson.features || []).map((f) => ({
            hex: f.properties.h3_index || f.properties.hex,
            value: f.properties.score ?? f.properties.value ?? 0,
          }));

          if (cityLayer.visible) {
            cityLayer.renderScenarioLayers(cityLayer.hexDataA, cityLayer.hexDataB);
            const contours = cityLayer.computeContours(
              cityLayer.hexDataA,
              cityLayer.hexDataB
            );
            cityLayer.renderContours(contours);
          }
        }

        // Update district-scale SHAP lenses
        if (typeof districtLayer !== 'undefined' && districtLayer && districtLayer.visible) {
          const bounds = map.getBounds();
          const bbox = [
            bounds.getWest(), bounds.getSouth(),
            bounds.getEast(), bounds.getNorth(),
          ];
          districtLayer._fetchForBbox(bbox);
        }
      } catch (err) {
        console.warn('ScenarioManager: apply failed', err);
      }
    }, 300);
  }

  /**
   * Wire a range input to a live value display.
   */
  _wireSlider(sliderId, displayId, formatter) {
    const slider = document.getElementById(sliderId);
    const display = document.getElementById(displayId);
    if (!slider || !display) return;

    slider.addEventListener('input', () => {
      display.textContent = formatter(slider.value);
    });
  }
}
