import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Regression guard for the doc_list bug: "Briefly list the document types you
 * have" used to return a flat list of 107 entries (with duplicates). The
 * grouped summary should now report a small set of category counts.
 */
test.describe('Chat — doc_list grouped summary', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('briefly list returns category counts, not per-file rows', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('Briefly list the document types you have');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    const assistant = page.locator(S.assistantMessage).first();
    await expect(assistant).toBeVisible();

    const text = await assistant.innerText();

    // Must mention at least one of the category labels
    const mentionsCategory =
      /Correspondence/i.test(text) ||
      /Documents/i.test(text) ||
      /Spreadsheets/i.test(text);
    expect(mentionsCategory).toBe(true);

    // Must not produce a 107-line wall of files. We allow a generous ceiling
    // (≤30 lines) so this stays robust if the answer gains a small explanation.
    const lineCount = text.split('\n').filter((l) => l.trim().length > 0).length;
    expect(lineCount).toBeLessThan(30);

    // Must not contain a numbered "1. [...] ..." list pattern (the verbose mode).
    // Five separate top-of-list numerals would be the smoking gun.
    const numberedRows = (text.match(/^\s*\d+\.\s/gm) || []).length;
    expect(numberedRows).toBeLessThan(5);
  });

  test('verbose query returns the full per-file listing', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('list all files verbose');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 120_000 });

    const text = await page.locator(S.assistantMessage).first().innerText();
    // Verbose mode must produce several numbered rows.
    const numberedRows = (text.match(/^\s*\d+\.\s/gm) || []).length;
    expect(numberedRows).toBeGreaterThanOrEqual(3);
  });
});
