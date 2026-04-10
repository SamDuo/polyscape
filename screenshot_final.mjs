import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

page.on('pageerror', err => console.log('[ERR]', err.message));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });

// Wait for hex data to fully load and render (large GeoJSON response)
await page.waitForFunction(() => cityLayer?.hexDataA?.length > 0, { timeout: 20000 });
await page.waitForTimeout(2000); // let deck.gl render

const state = await page.evaluate(() => ({
  band: zoomController?.currentBand,
  zoom: map?.getZoom()?.toFixed(1),
  hexes: cityLayer?.hexDataA?.length,
  deckLayers: cityLayer?.overlay?._props?.layers?.length,
  districtHidden: districtLayer?.visible === false,
  districtMarkers: districtLayer?.markers?.length,
}));
console.log('State:', JSON.stringify(state));

await page.screenshot({ path: 'data/screenshots/city-scale-z10.png' });
console.log('City scale screenshot saved');
await browser.close();
