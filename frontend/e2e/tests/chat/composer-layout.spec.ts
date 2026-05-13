import type { Page } from '@playwright/test';
import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * The composer (`#chat-input`) must be anchored at the bottom of the chat
 * area in every screen state: welcome / correspondence / document_analysis /
 * mid-conversation. We assert that its bottom edge sits within 32px of the
 * main content's bottom (allowing for vertical padding around the composer).
 */
async function composerSitsAtBottom(page: Page) {
  const composer = await page.locator(S.chatInput).boundingBox();
  const main = await page.locator(S.mainContent).boundingBox();
  expect(composer, 'composer has no box').not.toBeNull();
  expect(main, 'main content has no box').not.toBeNull();
  if (composer && main) {
    const composerBottom = composer.y + composer.height;
    const mainBottom = main.y + main.height;
    // Allow up to 32px of footer padding under the composer.
    expect(mainBottom - composerBottom).toBeLessThanOrEqual(32);
    expect(mainBottom - composerBottom).toBeGreaterThanOrEqual(-2);
  }
}

test.describe('Composer is anchored at the bottom', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('on the Welcome screen', async ({ page, welcomePage }) => {
    await welcomePage.waitForVisible();
    await expect(page.locator(S.chatInput)).toBeVisible();
    await composerSitsAtBottom(page);
  });

  test('inside Correspondence mode (empty)', async ({ page, welcomePage }) => {
    await welcomePage.selectCorrespondenceMode();
    await expect(page.getByText('CORRESPONDENCE MODE').first()).toBeVisible({ timeout: 5_000 });
    await composerSitsAtBottom(page);
  });

  test('inside Document Analysis mode (empty)', async ({ page, welcomePage }) => {
    await welcomePage.selectDocumentAnalysisMode();
    await expect(page.getByText('DOCUMENT ANALYSIS').first()).toBeVisible({ timeout: 5_000 });
    await composerSitsAtBottom(page);
  });

  test('mid-conversation, after sending a message', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('Hi');
    await page.locator(S.sendButton).click();
    // Wait for the user bubble to commit. We don't depend on the typing
    // indicator (which may flash through quickly on small responses) — the
    // chat log is enough proof that we transitioned out of Welcome.
    await expect(page.locator(S.chatLog)).toBeVisible({ timeout: 10_000 });
    await composerSitsAtBottom(page);
  });
});
