import { test } from '@playwright/test';

test('capture welcome/intro/chat surfaces', async ({ page, context }) => {
  test.setTimeout(180_000);
  await context.clearCookies();
  await page.goto('/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '/tmp/screenshots/01-welcome-fresh.png' });

  // Document Analysis mode
  await page.locator('[data-testid="sidebar-mode-toggle"] [data-mode="document_analysis"]').click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/tmp/screenshots/02-doc-analysis-intro.png' });

  // Correspondence
  await page.locator('[data-testid="sidebar-mode-toggle"] [data-mode="correspondence"]').click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/tmp/screenshots/03-correspondence-center.png' });

  // Chat stream
  // Back to AI Assistant (single chat)
  await page.locator('button:has-text("AI Assistant")').click();
  await page.locator('#chat-input').waitFor({ timeout: 10_000 });
  await page.locator('#chat-input').fill('Hello');
  await page.locator('#chat-input').press('Enter');
  await page.waitForTimeout(20_000);
  await page.screenshot({ path: '/tmp/screenshots/04-chat-stream.png' });
});
