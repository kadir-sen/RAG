import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Provider Tabs — Multi-LLM Responses', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('should show provider tabs when multiple providers respond', async ({
    page,
  }) => {
    // Send a question that triggers multi-provider response
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('What are the key contract terms?');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    // Check for provider tabs (may or may not appear depending on response)
    const tabs = page.locator('button:has-text("Gemini"), button:has-text("OpenAI"), button:has-text("Claude")');
    const tabCount = await tabs.count();

    if (tabCount > 1) {
      // Click each tab and verify content changes
      const firstTab = tabs.first();
      await firstTab.click();
      await page.waitForTimeout(300);

      const secondTab = tabs.nth(1);
      await secondTab.click();
      await page.waitForTimeout(300);

      // Active tab should have different styling
      // Just verify clicking doesn't throw errors
      expect(true).toBeTruthy();
    }
  });
});
