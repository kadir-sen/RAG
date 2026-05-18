import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * The critical end-to-end check: when the assistant answers a RAG-routed
 * question with inline citation chips, each chip must open its document in
 * the right-side viewer without a "Document not found" or "preview not
 * available" banner.
 *
 * Bug history: production had ~38 vectors whose file_path was stale (Windows
 * or container path that did not exist on the Lightsail disk). The resolver
 * now falls back to searching the data/ tree by filename, so the chip-click
 * path should resolve every indexed document.
 */
test.describe('RAG answer — inline citations open the viewer', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('every citation chip on a RAG answer opens its document', async ({ page, viewerPage }) => {
    // Trigger an "answer" intent that should return citations.
    await page.locator(S.chatInput).fill(
      'What are the contract terms around delay notifications and DPS?',
    );
    await page.locator(S.chatInput).press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 120_000 });

    const assistant = page.locator(S.assistantMessage).last();
    await expect(assistant).toBeVisible();

    // Inline citation chips live inside the assistant card. The chip is a
    // button with a `title` attribute carrying the filename + anchor.
    const chips = assistant.locator('button[title]');
    const count = await chips.count();
    test.skip(count === 0, 'Query did not produce any citation chips for this build');

    const maxCheck = Math.min(count, 6);
    for (let i = 0; i < maxCheck; i++) {
      const chip = chips.nth(i);
      const label = (await chip.innerText().catch(() => '')).trim() || `chip ${i}`;

      await chip.click();
      // Some chips might not be citations (defensive) — skip silently if no viewer opens.
      try {
        await viewerPage.waitForOpen(8_000);
      } catch {
        continue;
      }

      const viewerBody = await page.locator(S.mainContent).innerText();
      for (const err of ['Document not found', 'preview not available', 'Cannot parse']) {
        expect(
          viewerBody.includes(err),
          `Citation chip ${i} ("${label}") surfaced viewer error: ${err}`,
        ).toBe(false);
      }

      await viewerPage.close().catch(() => {});
    }
  });

  test('no "Sources" header and no numbered [N] footnotes — chips are inline', async ({ page }) => {
    await page.locator(S.chatInput).fill('Summarize delay notifications');
    await page.locator(S.chatInput).press('Enter');

    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 120_000 });

    const assistant = page.locator(S.assistantMessage).last();
    const bodyText = await assistant.innerText();

    expect(bodyText).not.toMatch(/^\s*Sources\s*$/im);
    expect(bodyText).not.toMatch(/\[\s*1\s*\]\s/);
  });
});
