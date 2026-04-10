/**
 * PolyScape — Scenario Manager
 * Lives in the Filters dropdown (no side panel).
 * Slider values → FeatureOverride format → /predict/custom API.
 */

class ScenarioManager {
  constructor() {}

  init() {
    this._wireSlider('slider-competitor', 'val-competitor', v => String(v));
    this._wireSlider('slider-income', 'val-income', v => '$' + Number(v).toLocaleString());
    this._wireSlider('slider-walk', 'val-walk', v => String(v));
    this._wireSlider('slider-comp', 'val-comp', v => String(v));

    document.getElementById('apply-scenario')?.addEventListener('click', () => this.apply());
    document.getElementById('reset-scenario')?.addEventListener('click', () => this.reset());
  }

  _getOverrides() {
    const overrides = [];
    const add = (id, feat, def) => {
      const el = document.getElementById(id);
      if (el && Number(el.value) !== def) overrides.push({ feature: feat, value: Number(el.value) });
    };
    add('slider-competitor', 'competitor_count', 0);
    add('slider-income', 'median_income', 50000);
    add('slider-walk', 'walk_score', 0);
    add('slider-comp', 'complementary_poi_count', 0);
    return overrides;
  }

  async apply() {
    const overrides = this._getOverrides();
    if (!overrides.length) return;

    try {
      const resp = await fetch('/predict/custom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides }),
      });
      if (!resp.ok) return;
      const geojson = await resp.json();

      if (cityLayer) {
        cityLayer.setScenarioB((geojson.features || []).map(f => ({
          hex: f.properties.h3_index,
          value: f.properties.score ?? 0,
        })));
      }

      // Close dropdown
      document.getElementById('filters-dropdown').style.display = 'none';
      document.getElementById('btn-filters')?.classList.remove('active');
    } catch (err) { console.warn('ScenarioManager: apply failed', err); }
  }

  reset() {
    const defaults = { 'slider-competitor': '0', 'slider-income': '50000', 'slider-walk': '0', 'slider-comp': '0' };
    for (const [id, val] of Object.entries(defaults)) {
      const el = document.getElementById(id);
      if (el) { el.value = val; el.dispatchEvent(new Event('input')); }
    }
    if (cityLayer) {
      cityLayer.hexDataB = cityLayer.hexDataA.map(d => ({ ...d }));
      if (cityLayer.visible) cityLayer._render();
    }
    const el = document.getElementById('brief-scenario');
    if (el) el.textContent = 'Base';
  }

  _wireSlider(sliderId, displayId, fmt) {
    const slider = document.getElementById(sliderId);
    const disp = document.getElementById(displayId);
    if (slider && disp) slider.addEventListener('input', () => { disp.textContent = fmt(slider.value); });
  }
}
