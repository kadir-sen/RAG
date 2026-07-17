import { test, expect } from '../../fixtures/base.fixture';

/**
 * html_report_section blocks are sanitized client-side before injection
 * (utils/sanitizeReportHtml.ts), independently of the backend's own templater
 * and allowlist sanitizer.
 *
 * These tests stub /api/chat with markup the backend would never emit — that
 * is the whole point. The client layer exists for the case where the HTML did
 * NOT come from the trusted templater (a backend regression, a block built
 * somewhere new, a tampered response). Stubbing is the only way to exercise
 * that case.
 */

function chatResponse(html: string) {
  return {
    answer: 'Section attached.',
    sources: [],
    blocks: [
      {
        type: 'html_report_section',
        block_id: 'b1',
        title: 'Delayed Blockwork',
        html,
        fallback_markdown: '## 6.1 Delayed Blockwork\n\nFallback narrative.',
        sanitized: true,
      },
    ],
  };
}

/** A section shaped exactly like compose_section's real output. */
const BENIGN_SECTION =
  '<div class="coair-report-body">' +
  '<h2>6.1. Delayed Blockwork</h2>' +
  '<p><span class="coair-para-no">6.1.1</span>On 19 July 2023, <strong>JAMED</strong> raised concerns.</p>' +
  '<h4>Chronology</h4>' +
  '<table><thead><tr><th>Date</th><th>Actor</th></tr></thead>' +
  '<tbody><tr><td>19 Jul 2023</td><td>JAMED</td></tr></tbody></table>' +
  '<div class="coair-sources"><strong>Sources</strong><ul><li>L1.pdf, p.3</li></ul></div>' +
  '<div class="coair-caveats"><strong>Caveats</strong><ul><li>Preliminary.</li></ul></div>' +
  '</div>';

const XSS_SECTION =
  '<div class="coair-report-body">' +
  '<h2>6.1. Delayed Blockwork</h2>' +
  '<script>window.__pwned = true;<\/script>' +
  '<img src="x" onerror="window.__pwned = true">' +
  '<svg onload="window.__pwned = true"></svg>' +
  '<iframe src="https://evil.example/steal"></iframe>' +
  '<a href="javascript:void(window.__pwned = true)">click</a>' +
  '<p>Legitimate narrative survives.</p>' +
  '</div>';

async function sendAndWait(page: import('@playwright/test').Page, html: string) {
  await page.route('**/api/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(chatResponse(html)),
    }),
  );
  const input = page.locator('#welcome-search, #chat-input').first();
  await input.fill('Prepare 6.1 chronology for Delayed Blockwork.');
  await input.press('Enter');
  await expect(page.locator('.coair-report-section')).toBeVisible({ timeout: 30_000 });
}

test.describe('html_report_section — client-side sanitization', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('renders a benign section without stripping its structure', async ({ page }) => {
    await sendAndWait(page, BENIGN_SECTION);
    const section = page.locator('.coair-report-section');

    // Sanitization must not cost us the report: headings, tables and the
    // scoped classes globals.css styles all have to survive.
    await expect(section.locator('h2')).toHaveText('6.1. Delayed Blockwork');
    await expect(section.locator('table td').first()).toHaveText('19 Jul 2023');
    await expect(section.locator('.coair-para-no')).toHaveText('6.1.1');
    await expect(section.locator('.coair-sources')).toBeVisible();
    await expect(section.locator('.coair-caveats')).toBeVisible();
    await expect(section.locator('strong').first()).toBeVisible();
  });

  test('neutralises injected script, handlers and frames', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await sendAndWait(page, XSS_SECTION);
    const section = page.locator('.coair-report-section');

    // Nothing executed.
    expect(await page.evaluate(() => (window as never as { __pwned?: boolean }).__pwned)).toBeFalsy();
    expect(errors).toHaveLength(0);

    // Nothing hostile survived into the DOM.
    await expect(section.locator('script')).toHaveCount(0);
    await expect(section.locator('iframe')).toHaveCount(0);
    await expect(section.locator('svg')).toHaveCount(0);
    await expect(section.locator('[onerror]')).toHaveCount(0);
    await expect(section.locator('[onload]')).toHaveCount(0);
    await expect(section.locator('a[href^="javascript:"]')).toHaveCount(0);

    // ...and the legitimate part of the same section still rendered.
    await expect(section).toContainText('Legitimate narrative survives.');
  });

  test('strips external resource references', async ({ page }) => {
    await sendAndWait(
      page,
      '<div class="coair-report-body"><p>x</p>' +
        '<img src="https://evil.example/track.gif">' +
        '<a href="https://evil.example">link</a>' +
        '<a href="/api/artifacts/r1/report.pdf">download</a></div>',
    );
    const section = page.locator('.coair-report-section');

    await expect(section.locator('img[src*="evil.example"]')).toHaveCount(0);
    await expect(section.locator('a[href*="evil.example"]')).toHaveCount(0);
    // Artifact links are the one href shape we do allow.
    await expect(section.locator('a[href="/api/artifacts/r1/report.pdf"]')).toHaveCount(1);
  });

  test('falls back to markdown when the html is entirely unsafe', async ({ page }) => {
    await page.route('**/api/chat', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(chatResponse('<script>window.__pwned = true;<\/script>')),
      }),
    );
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('Prepare 6.1 chronology for Delayed Blockwork.');
    await input.press('Enter');

    // Sanitizing to nothing must not render an empty card — the backend always
    // ships fallback_markdown for exactly this case.
    await expect(page.getByText('Fallback narrative.')).toBeVisible({ timeout: 30_000 });
    expect(await page.evaluate(() => (window as never as { __pwned?: boolean }).__pwned)).toBeFalsy();
  });
});
