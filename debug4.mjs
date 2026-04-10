import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

const errLogs = [];
page.on('console', msg => { if (msg.type() === 'error') errLogs.push(msg.text()); });
page.on('pageerror', err => errLogs.push(err.message));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(8000);

const state = await page.evaluate(() => ({
  band: zoomController?.currentBand,
  hexA: cityLayer?.hexDataA?.length,
  visible: cityLayer?.visible,
  overlayLayers: cityLayer?.overlay?._props?.layers?.length ?? -1,
  districtHidden: districtLayer?.visible === false,
}));
console.log('State:', JSON.stringify(state));

if (errLogs.length) console.log('Errors:', errLogs.slice(0, 5).join('\n'));
else console.log('No errors!');

await page.screenshot({ path: 'data/screenshots/city-scale-z10.png' });
console.log('Screenshot saved');
await browser.close();
