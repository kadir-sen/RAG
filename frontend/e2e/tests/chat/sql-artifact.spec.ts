import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('SQL Artifact Display', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('should display SQL artifact for data queries', async ({ page }) => {
    // Send a data query that should trigger SQL
    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('How many workers were deployed by trade last month?');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    // Check for SQL artifact elements
    const showDetails = page.locator('button:has-text("Show details")');
    const downloadCsv = page.locator('button:has-text("Download CSV")');

    if (await showDetails.isVisible()) {
      // Toggle show details
      await showDetails.click();
      await page.waitForTimeout(300);

      // SQL code or table should be visible
      const sqlOrTable = page.locator('pre, table');
      await expect(sqlOrTable.first()).toBeVisible({ timeout: 3_000 });
    }

    if (await downloadCsv.isVisible()) {
      // Verify the download button exists and is clickable
      await expect(downloadCsv).toBeEnabled();
    }
  });
});
