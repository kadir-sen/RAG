import { test, expect } from '../../fixtures/base.fixture';

test.describe('Welcome Screen', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('should display welcome heading and search bar', async ({ welcomePage }) => {
    await welcomePage.waitForVisible();
    await expect(welcomePage.searchInput).toBeVisible();
  });

  test('should show Correspondence Mode and Document Analysis cards', async ({
    welcomePage,
  }) => {
    await expect(welcomePage.correspondenceCard).toBeVisible();
    await expect(welcomePage.documentAnalysisCard).toBeVisible();
  });

  test('should display example query buttons', async ({ page }) => {
    // There should be 6 example queries
    const exampleButtons = page.locator('button:has-text("workers"), button:has-text("crane"), button:has-text("progress"), button:has-text("contract"), button:has-text("notices"), button:has-text("manpower trend")');
    const count = await exampleButtons.count();
    expect(count).toBeGreaterThanOrEqual(4);
  });

  test('should send message from welcome search bar', async ({ page, welcomePage }) => {
    await welcomePage.searchAndSend('Hello test');

    // Should transition to chat and show typing indicator
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
  });

  test('should send message when clicking an example query', async ({ page }) => {
    // Click the first example query about workers
    await page.locator('button:has-text("workers were deployed")').click();

    // Should start loading
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
  });
});
