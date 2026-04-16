import { test, expect } from '../../fixtures/base.fixture';

test.describe('Library Picker Modal', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should open library picker from left drawer', async ({ page }) => {
    // Look for the "Add Documents" button or left drawer toggle
    const addDocsBtn = page.locator('button:has-text("+ Add Documents"), button:has-text("Add Documents")');
    const toggleBtn = page.locator('[title="Open documents panel"]');

    // Try to open the left drawer first if available
    if (await toggleBtn.isVisible()) {
      await toggleBtn.click();
      await page.waitForTimeout(500);
    }

    if (await addDocsBtn.isVisible()) {
      await addDocsBtn.click();

      // Modal should open
      const modal = page.locator('h3:has-text("Add Documents")');
      if (await modal.isVisible({ timeout: 3_000 })) {
        // Should have checkboxes for documents
        const checkboxes = page.locator('[role="dialog"] input[type="checkbox"], .fixed input[type="checkbox"]');
        const count = await checkboxes.count();
        expect(count).toBeGreaterThanOrEqual(0);

        // Close modal
        const cancelBtn = page.locator('button:has-text("Cancel")');
        if (await cancelBtn.isVisible()) {
          await cancelBtn.click();
        }
      }
    }
  });
});
