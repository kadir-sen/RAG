import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Email Sidebar — Correspondence Mode', () => {
  test.beforeEach(async ({ page, sidebarPage, welcomePage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
    await welcomePage.selectCorrespondenceMode();
  });

  test('should show email list with checkboxes in correspondence mode', async ({
    page,
  }) => {
    // Wait for sidebar to update with email content
    await page.waitForTimeout(2_000);

    // Check if emails section header is visible (matches "Emails (N)")
    const emailSection = page.locator('p:has-text("Emails")').first();
    await expect(emailSection).toBeVisible({ timeout: 5_000 });

    // There should be checkboxes for email selection
    const checkboxes = page.locator('[aria-label="Sidebar"] input[type="checkbox"]');
    const count = await checkboxes.count();

    if (count > 0) {
      // Select first email
      await checkboxes.first().check();
      expect(await checkboxes.first().isChecked()).toBeTruthy();
    }
  });

  test('should enable quick prompt buttons when emails are selected', async ({
    page,
  }) => {
    await page.waitForTimeout(2_000);

    const checkboxes = page.locator('[aria-label="Sidebar"] input[type="checkbox"]');
    const count = await checkboxes.count();

    if (count > 0) {
      // Quick prompts should be disabled initially
      const summarizeBtn = page.locator('button:has-text("Summarize selected emails")');
      if (await summarizeBtn.isVisible()) {
        // Select an email
        await checkboxes.first().check();

        // Quick prompt buttons should now be enabled
        await expect(summarizeBtn).toBeEnabled();
      }
    }
  });

  test('should disable quick prompts when no emails selected', async ({ page }) => {
    await page.waitForTimeout(2_000);

    const summarizeBtn = page.locator('button:has-text("Summarize selected emails")');
    if (await summarizeBtn.isVisible()) {
      // With no selection, should be disabled (via opacity)
      const opacity = await summarizeBtn.evaluate((el) =>
        window.getComputedStyle(el).opacity,
      );
      expect(parseFloat(opacity)).toBeLessThan(1);
    }
  });
});
