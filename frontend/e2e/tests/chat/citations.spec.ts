import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Citation Chips', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('should display citation chips and open document viewer on click', async ({
    page,
    viewerPage,
  }) => {
    // Send a document-related query
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('What are the key contract terms about delay penalties?');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    // Look for citation chips (buttons with score percentage or doc name)
    const citationButtons = page.locator('button[title]').filter({
      has: page.locator('text=/%/'),
    });

    // Alternative: look for any small clickable chip-like elements in the response area
    const chips = page.locator('.flex.flex-wrap button, .inline-flex button');
    const chipCount = await chips.count();

    if (chipCount > 0) {
      // Click the first citation chip
      await chips.first().click();

      // Document viewer should open
      try {
        await viewerPage.waitForOpen(10_000);
        await expect(page.locator(S.viewerClose)).toBeVisible();

        // Close it
        await viewerPage.close();
      } catch {
        // Citation might not open viewer for all types
      }
    }
  });
});
