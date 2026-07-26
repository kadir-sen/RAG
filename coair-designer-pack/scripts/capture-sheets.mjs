/**
 * Refreshes the reference images in `screenshots/` straight from the offline
 * pack — once as the drawing sheet (light), once as the blueprint (dark).
 *
 *   npm run dev            # in one terminal
 *   npm run screenshots    # in another
 *
 * Nothing here touches a backend or the network: every screen is filled from
 * src/mocks. Point it somewhere else with PACK_URL=http://localhost:5173.
 */
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const BASE = process.env.PACK_URL ?? 'http://localhost:3000';
const OUT = 'screenshots';

/** Stamps the sheet mode the way the app's own boot script does. */
async function setSheet(page, mode) {
  await page.evaluate((m) => {
    localStorage.setItem('platform.sheet', m);
    document.documentElement.setAttribute('data-sheet', m);
  }, mode);
  await page.waitForTimeout(500); // let the colour transitions settle
}

async function openConversation(page, title) {
  await page.locator('span.truncate', { hasText: title }).first().click();
  await page.waitForTimeout(700);
}

async function capture(browser, mode) {
  const tag = mode === 'light' ? 'sheet' : 'blueprint';
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const shot = (name) => page.screenshot({ path: `${OUT}/${tag}-${name}.png` });

  // 01 — access
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await setSheet(page, mode);
  await page.reload({ waitUntil: 'networkidle' });
  await shot('01-login');

  // 02 — welcome / mode picker
  await page.locator('#login-username').fill('designer');
  await page.locator('#login-password').fill('designer');
  await page.locator('button[type="submit"]').click();
  await page.locator('#chat-input').waitFor({ timeout: 20_000 });
  await page.waitForTimeout(900);
  await shot('02-welcome');

  // 03 — cited answer
  await openConversation(page, 'EOT entitlement');
  await page.getByText('Related Documents').first().waitFor({ timeout: 15_000 });
  await page.waitForTimeout(400);
  await shot('03-chat-eot');

  // 04 — document viewer, opened from a citation chip
  await page.locator('button', { hasText: 'EOT_Request_Zone3' }).first().click();
  await page.waitForTimeout(1200);
  await shot('04-viewer-pdf');

  // 05 — generated SQL + result table
  await openConversation(page, 'Q2 cost overrun');
  await page.locator('button', { hasText: 'Show details' }).first().click();
  await page.waitForTimeout(600);
  await shot('05-sql-table');

  await page.close();
  console.log(`  ${tag}: 5 screens`);
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
console.log(`Capturing ${BASE} →  ${OUT}/`);
try {
  for (const mode of ['light', 'dark']) await capture(browser, mode);
} finally {
  await browser.close();
}
console.log('Done.');
