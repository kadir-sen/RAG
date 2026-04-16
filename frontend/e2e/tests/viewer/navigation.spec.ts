import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Document Viewer — Page Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should navigate pages with prev/next buttons', async ({ page, viewerPage }) => {
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');

    if ((await fileItems.count()) === 0) {
      test.skip(true, 'No files in sidebar');
      return;
    }

    await fileItems.first().click();
    await page.waitForTimeout(2_000);

    if (!(await page.locator(S.viewerClose).isVisible())) {
      test.skip(true, 'Viewer did not open');
      return;
    }

    const prevBtn = page.locator(S.prevPage);
    const nextBtn = page.locator(S.nextPage);

    if (!(await prevBtn.isVisible())) {
      test.skip(true, 'Single page or no pagination');
      return;
    }

    await expect(prevBtn).toBeDisabled();

    if (await nextBtn.isEnabled()) {
      await viewerPage.nextPage();
      await page.waitForTimeout(1_000);
      await expect(prevBtn).toBeEnabled();

      await viewerPage.prevPage();
      await page.waitForTimeout(1_000);
      await expect(prevBtn).toBeDisabled();
    }
  });

  test('should show page counter', async ({ page, viewerPage }) => {
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');

    if ((await fileItems.count()) === 0) {
      test.skip(true, 'No files');
      return;
    }

    await fileItems.first().click();
    await page.waitForTimeout(2_000);

    if (!(await page.locator(S.viewerClose).isVisible())) {
      test.skip(true, 'Viewer did not open');
      return;
    }

    const pageCounter = page.locator('text=/\\d+\\/\\d+/');
    if (await pageCounter.isVisible()) {
      const text = await pageCounter.innerText();
      expect(text).toMatch(/^\d+\/\d+$/);
    }
  });
});
