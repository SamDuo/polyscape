import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForFunction(() => cityLayer?.hexDataA?.length > 0, { timeout: 25000 });
await page.waitForTimeout(3000);
await page.screenshot({ path: 'data/screenshots/city-scale-z10-paper.png' });
console.log('High-res city scale screenshot saved (2x retina)');

const info = await page.evaluate(() => ({
  hexes: cityLayer.hexDataA.length,
  best: cityLayer.hexDataA.reduce((a,b) => a.value > b.value ? a : b),
}));
console.log(`${info.hexes} hexes, best: ${info.best.hex} = ${info.best.value.toFixed(4)}`);

await browser.close();
