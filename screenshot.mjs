import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

await page.goto('http://localhost:8080', { waitUntil: 'networkidle', timeout: 30000 });

// Wait for map and hex data to load
await page.waitForTimeout(6000);

// Take city scale screenshot (default z=10)
await page.screenshot({ path: 'data/screenshots/city-scale-z10.png', fullPage: false });
console.log('Saved: data/screenshots/city-scale-z10.png');

await browser.close();
