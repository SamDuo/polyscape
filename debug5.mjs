import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

const allLogs = [];
page.on('console', msg => allLogs.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => allLogs.push(`[ERR] ${err.message}`));

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(8000);

// Manually try the fetch to diagnose
const fetchResult = await page.evaluate(async () => {
  const bbox = getMapBbox();
  const url = `/predict?bbox=${bbox.join(',')}&res=8`;
  try {
    const resp = await fetch(url);
    const text = await resp.text();
    return { url, status: resp.status, bodyLen: text.length, firstChars: text.slice(0, 200), bbox };
  } catch (e) {
    return { url, error: e.message, bbox };
  }
});
console.log('Fetch result:', JSON.stringify(fetchResult, null, 2));

// Check if loadHexData was called
const state = await page.evaluate(() => ({
  loading: cityLayer?._loading,
  hexA: cityLayer?.hexDataA?.length,
}));
console.log('State:', JSON.stringify(state));

// Print relevant console logs
allLogs.filter(l => /City|predict|hex|load/i.test(l)).forEach(l => console.log(l));

await browser.close();
