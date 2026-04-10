import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

const errors = [];
page.on('pageerror', err => errors.push(err.message));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(3000);

const check = await page.evaluate(() => {
  return {
    deckKeys: Object.keys(typeof deck !== 'undefined' ? deck : {}).filter(k => /H3|Hexagon|Mapbox/i.test(k)),
    h3: typeof h3,
    h3v2: typeof window.h3,
    h3v3: typeof window.h3Core,
    globalKeys: Object.keys(window).filter(k => /^h3/i.test(k)),
  };
});
console.log('Check:', JSON.stringify(check, null, 2));
console.log('Errors:', errors.slice(0, 5));
await browser.close();
