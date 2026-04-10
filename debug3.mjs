import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

const logs = [];
page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => logs.push(`[ERR] ${err.message}`));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(8000);

const state = await page.evaluate(() => ({
  band: zoomController?.currentBand,
  zoom: map?.getZoom()?.toFixed(1),
  hexA: cityLayer?.hexDataA?.length,
  visible: cityLayer?.visible,
  overlayLayers: cityLayer?.overlay?._props?.layers?.length ?? -1,
  districtVisible: districtLayer?.visible,
  districtMarkers: districtLayer?.markers?.length,
}));
console.log('State:', JSON.stringify(state, null, 2));

// Take screenshot
await page.screenshot({ path: 'data/screenshots/city-scale-z10.png' });
console.log('Screenshot saved');

// Print any warn/error logs
logs.filter(l => l.includes('warn') || l.includes('ERR') || l.includes('error')).forEach(l => console.log(l));
await browser.close();
