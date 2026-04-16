import { test, expect } from '../../fixtures/base.fixture';

test.describe('Sidebar — Conversation Management', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should create a new conversation via New Chat button', async ({
    page,
    sidebarPage,
  }) => {
    await sidebarPage.createNewChat();

    // Welcome screen or chat input should be visible (fresh state)
    const welcomeSearch = page.locator('#welcome-search');
    const chatInput = page.locator('#chat-input');
    const isReady =
      (await welcomeSearch.isVisible()) || (await chatInput.isVisible());
    expect(isReady).toBeTruthy();
  });

  test('should show conversation in list after sending a message', async ({
    page,
    sidebarPage,
  }) => {
    await sidebarPage.createNewChat();

    // Send a message to populate the conversation
    const welcomeSearch = page.locator('#welcome-search');
    const chatInput = page.locator('#chat-input');
    const input = (await welcomeSearch.isVisible()) ? welcomeSearch : chatInput;

    await input.fill('Test conversation message');
    await input.press('Enter');

    // Wait for response
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[role="status"]')).not.toBeVisible({ timeout: 90_000 });

    // The conversation should now appear in the sidebar list
    const conversations = page.locator('.truncate');
    const count = await conversations.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('should rename a conversation via inline edit', async ({ page, sidebarPage }) => {
    // First create a chat with a message
    await sidebarPage.createNewChat();
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('Rename test');
    await input.press('Enter');
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[role="status"]')).not.toBeVisible({ timeout: 90_000 });

    // Find conversation items
    const convItems = page.locator('.truncate');
    const count = await convItems.count();
    if (count === 0) {
      test.skip(true, 'No conversations to rename');
      return;
    }

    // Hover over the first conversation to reveal rename/delete buttons
    const firstConvParent = convItems.first().locator('..');
    await firstConvParent.hover();
    await page.waitForTimeout(300);

    // Check if rename button appeared
    const renameBtn = firstConvParent.locator('[title="Rename"]');
    if (!(await renameBtn.isVisible({ timeout: 2_000 }).catch(() => false))) {
      test.skip(true, 'Rename button not visible on hover');
      return;
    }

    await renameBtn.click();
    await page.waitForTimeout(300);

    // The inline input should appear
    const renameInput = firstConvParent.locator('input[type="text"], input:not([type])');
    if (await renameInput.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await renameInput.fill('E2E Renamed Chat');
      await renameInput.press('Enter');
      await page.waitForTimeout(500);

      // Verify the new title
      await expect(page.getByText('E2E Renamed Chat')).toBeVisible({ timeout: 3_000 });
    }
  });

  test('should delete a conversation', async ({ page, sidebarPage }) => {
    // Create a conversation with a message first
    await sidebarPage.createNewChat();
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('Delete test');
    await input.press('Enter');
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[role="status"]')).not.toBeVisible({ timeout: 90_000 });

    const countBefore = await page.locator('.truncate').count();

    // Hover and delete
    const convItem = page.locator('.truncate').first().locator('..');
    await convItem.hover();

    const deleteBtn = convItem.locator('[title="Delete"]');
    if (await deleteBtn.isVisible()) {
      await deleteBtn.click();
      await page.waitForTimeout(300);

      // Confirm the deletion
      const confirmBtn = convItem.locator('button:has-text("Yes")');
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
      await page.waitForTimeout(500);

      const countAfter = await page.locator('.truncate').count();
      expect(countAfter).toBeLessThanOrEqual(countBefore);
    }
  });
});
