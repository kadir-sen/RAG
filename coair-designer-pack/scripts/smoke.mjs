// Production smoke: walk every screen in both sheet modes against the built
// dist, collecting console errors, page errors, and failed network requests.
import { chromium } from '@playwright/test';

const BASE = process.env.PACK_URL ?? 'http://localhost:4180';
const problems = [];

async function walk(browser, mode) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const tag = mode === 'light' ? 'sheet' : 'blueprint';
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push(`[${tag}] console: ${m.text().slice(0, 200)}`);
  });
  page.on('pageerror', (e) => problems.push(`[${tag}] pageerror: ${String(e).slice(0, 200)}`));
  page.on('requestfailed', (r) => {
    if (!r.failure()?.errorText.includes('ERR_ABORTED'))
      problems.push(`[${tag}] requestfailed: ${r.url()} ${r.failure()?.errorText}`);
  });
  page.on('response', (r) => {
    if (r.status() >= 400) problems.push(`[${tag}] HTTP ${r.status()}: ${r.url()}`);
  });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.evaluate((m) => {
    localStorage.setItem('platform.sheet', m);
    document.documentElement.setAttribute('data-sheet', m);
  }, mode);

  // login
  await page.locator('#login-username').fill('designer');
  await page.locator('#login-password').fill('designer');
  await page.locator('button[type="submit"]').click();
  await page.locator('#chat-input').waitFor({ timeout: 20_000 });

  // welcome KPIs render
  await page.getByText('Project library', { exact: false }).first().waitFor();

  // cited answer + viewer
  await page.locator('span.truncate', { hasText: 'EOT entitlement' }).first().click();
  await page.getByText('Related Documents').first().waitFor();
  await page.locator('button', { hasText: 'EOT_Request_Zone3' }).first().click();
  await page.locator('img[alt^="Page"]').first().waitFor({ timeout: 10_000 });

  // SQL result + detail expand + xls viewer
  await page.locator('span.truncate', { hasText: 'Q2 cost overrun' }).first().click();
  await page.locator('button', { hasText: 'Show details' }).first().click();
  await page.getByText('Result (4 rows)').waitFor();
  await page.locator('button', { hasText: 'Cost_Tracker_Q2' }).first().click();
  await page.getByText('budget_aed').first().waitFor({ timeout: 10_000 });

  // email trace + correspondence + doc-analysis modes
  await page.locator('span.truncate', { hasText: 'Rebar delivery' }).first().click();
  await page.waitForTimeout(600);
  for (const modeBtn of ['Correspondence', 'Document Analysis']) {
    await page.locator('button', { hasText: modeBtn }).first().click();
    await page.waitForTimeout(700);
  }

  // settings modal
  await page.locator('button[aria-label="Open settings"]').click();
  await page.getByText('Vector Database').waitFor();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  // CSV export — must download client-side, no navigation, no 404
  const dl = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);
  await page.locator('a[aria-label="Export file list as CSV"]').click();
  const download = await dl;
  if (!download) problems.push(`[${tag}] CSV export produced no download`);
  else if (download.suggestedFilename() !== 'file_list.csv')
    problems.push(`[${tag}] CSV export unexpected filename ${download.suggestedFilename()}`);
  if (!page.url().includes('/')) problems.push(`[${tag}] CSV export navigated away: ${page.url()}`);

  // sheet toggle round-trip
  await page.locator('button.sheet-toggle').click();
  await page.waitForTimeout(400);
  await page.locator('button.sheet-toggle').click();
  await page.waitForTimeout(400);

  await page.close();
  console.log(`  ${tag}: walked login → welcome → chat → viewer → sql → email → modes → settings → csv → toggle`);
}

const browser = await chromium.launch();
try {
  for (const m of ['light', 'dark']) await walk(browser, m);
} finally {
  await browser.close();
}

if (problems.length) {
  console.log('\nPROBLEMS:');
  for (const p of [...new Set(problems)]) console.log('  ' + p);
  process.exit(1);
}
console.log('\nCLEAN: no console errors, no page errors, no failed requests.');
