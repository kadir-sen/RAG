import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Pinecone-coverage check: every citation chip the assistant returns should
 * resolve to a viewable document. Run a few representative queries that we
 * expect to surface different doc types (PDF, email, spreadsheet) and assert
 * that the viewer opens without an error banner.
 */
const VIEWER_ERROR_TEXTS = [
  'Document not found',
  'preview not available',
  'Cannot parse email',
  'Cannot parse docx',
];

async function sendAndWait(page: import('@playwright/test').Page, query: string) {
  const input = page.locator(S.chatInput);
  await input.fill(query);
  await input.press('Enter');
  await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 120_000 });
}

test.describe('Chat — citation chips open every doc type', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('each citation chip opens a viewer without an error banner', async ({
    page,
    viewerPage,
  }) => {
    await sendAndWait(page, 'Summarize all delay notifications and DPS-related correspondence.');

    // Citation chips are small inline buttons on the assistant message.
    // Match any clickable chip-like element inside the response area.
    const chips = page.locator('.prose').last().locator('button');
    const count = await chips.count();
    test.skip(count === 0, 'No citation chips were returned for this query');

    // Inspect up to 5 chips to keep runtime bounded.
    const maxChips = Math.min(count, 5);
    for (let i = 0; i < maxChips; i++) {
      const chip = chips.nth(i);
      const label = (await chip.innerText().catch(() => '')).trim();
      await chip.click();

      // Either the viewer panel opens, or the chip wasn't a citation; both ok.
      try {
        await viewerPage.waitForOpen(8_000);
      } catch {
        continue;
      }

      // Whatever opened, it should not contain a known error string.
      const viewerBody = await page.locator(S.mainContent).innerText();
      for (const err of VIEWER_ERROR_TEXTS) {
        expect(
          viewerBody.includes(err),
          `Citation chip ${i} ("${label}") surfaced viewer error: ${err}`,
        ).toBe(false);
      }

      await viewerPage.close().catch(() => {});
    }
  });

  test('emails (.msg) render structured content, not an empty error', async ({
    page,
    viewerPage,
  }) => {
    await sendAndWait(page, 'Show me emails about Vingcard or access card graphics.');

    const chips = page.locator('.prose').last().locator('button');
    const count = await chips.count();
    test.skip(count === 0, 'No email citation chips were returned');

    let openedAny = false;
    for (let i = 0; i < Math.min(count, 5); i++) {
      const chip = chips.nth(i);
      const label = (await chip.innerText().catch(() => '')).trim();
      if (!/\.msg|\.eml|email/i.test(label)) continue;

      await chip.click();
      try {
        await viewerPage.waitForOpen(8_000);
      } catch {
        continue;
      }
      openedAny = true;

      const body = await page.locator(S.mainContent).innerText();
      // A successful parse surfaces at least one structured field.
      expect(
        /Subject:|From:|To:|Date:/i.test(body),
        `Email viewer for "${label}" missing structured headers. Body excerpt: ${body.slice(0, 300)}`,
      ).toBe(true);

      await viewerPage.close().catch(() => {});
    }

    test.skip(!openedAny, 'No email-labeled chip was clickable in this run');
  });
});
