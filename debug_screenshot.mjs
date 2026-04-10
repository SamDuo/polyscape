import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

const errors = [];
page.on('console', msg => {
  if (msg.type() === 'error' || msg.type() === 'warning')
    errors.push(`[${msg.type()}] ${msg.text()}`);
});
page.on('pageerror', err => errors.push(`[pageerror] ${err.message}`));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(6000);

const deckCheck = await page.evaluate(() => {
  return {
    deckExists: typeof deck !== 'undefined',
    H3HexagonLayer: typeof deck?.H3HexagonLayer,
    MapboxOverlay: typeof deck?.MapboxOverlay,
    h3Exists: typeof h3 !== 'undefined',
    cityLayerExists: typeof cityLayer !== 'undefined',
    cityLayerVisible: cityLayer?.visible,
    hexDataLength: cityLayer?.hexDataA?.length ?? -1,
    overlayExists: !!cityLayer?.overlay,
  };
});
console.log('Deck check:', JSON.stringify(deckCheck, null, 2));
console.log('Errors:', errors.length);
errors.slice(0, 20).forEach(e => console.log(' ', e));

await browser.close();
