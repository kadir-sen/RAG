import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Citations are rendered inline at the end of the assistant text. There is
 * no longer a "Sources" header or a row of numbered [N] chips.
 */
test.describe('Inline citation chips', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('assistant response renders inline file chips without a Sources header', async ({ page, viewerPage }) => {
    const input = page.locator(S.chatInput);
    await input.fill('What are the key contract terms about delay penalties?');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    const assistant = page.locator(S.assistantMessage).last();
    await expect(assistant).toBeVisible();

    // No "Sources" header / no "[1]" numbered footnote pattern.
    await expect(assistant.getByText('Sources', { exact: true })).toHaveCount(0);
    const bodyText = await assistant.innerText();
    expect(bodyText).not.toMatch(/\[\s*1\s*\]\s/);

    // The chips live inside the same assistant card as the text. If the model
    // returned at least one citation we should see a clickable button with a
    // file glyph that opens the viewer.
    const chips = assistant.locator('button[title]');
    const count = await chips.count();
    if (count > 0) {
      await chips.first().click();
      await viewerPage.waitForOpen(10_000);
      const viewerText = await page.locator(S.mainContent).innerText();
      expect(viewerText).not.toMatch(/Document not found/i);
      expect(viewerText).not.toMatch(/preview not available/i);
      await viewerPage.close().catch(() => {});
    }
  });
});
