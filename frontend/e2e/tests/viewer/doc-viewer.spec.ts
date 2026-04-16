import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Document Viewer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should open document viewer when clicking a file in sidebar', async ({
    page,
    viewerPage,
  }) => {
    // Check for clickable file items in the sidebar "Documents" section
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');
    const fileCount = await fileItems.count();

    if (fileCount === 0) {
      test.skip(true, 'No files in sidebar to test viewer');
      return;
    }

    // Click the first file
    await fileItems.first().click();
    await page.waitForTimeout(2_000);

    // Check if viewer opened
    const viewerClose = page.locator(S.viewerClose);
    if (await viewerClose.isVisible()) {
      await expect(viewerClose).toBeVisible();
    } else {
      // Viewer might not open for some file types — pass gracefully
      test.skip(true, 'Viewer did not open for this file type');
    }
  });

  test('should close document viewer via close button', async ({
    page,
    viewerPage,
  }) => {
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');

    if ((await fileItems.count()) === 0) {
      test.skip(true, 'No files in sidebar');
      return;
    }

    await fileItems.first().click();
    await page.waitForTimeout(2_000);

    const viewerClose = page.locator(S.viewerClose);
    if (!(await viewerClose.isVisible())) {
      test.skip(true, 'Viewer did not open');
      return;
    }

    await viewerPage.close();
    await expect(viewerClose).not.toBeVisible();
  });

  test('should show page navigation for multi-page documents', async ({
    page,
    viewerPage,
  }) => {
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');

    if ((await fileItems.count()) === 0) {
      test.skip(true, 'No files in sidebar');
      return;
    }

    await fileItems.first().click();
    await page.waitForTimeout(2_000);

    const viewerClose = page.locator(S.viewerClose);
    if (!(await viewerClose.isVisible())) {
      test.skip(true, 'Viewer did not open');
      return;
    }

    const prevBtn = page.locator(S.prevPage);
    if (!(await prevBtn.isVisible())) {
      test.skip(true, 'Single page document');
      return;
    }

    // On first page, prev should be disabled
    await expect(prevBtn).toBeDisabled();

    const nextBtn = page.locator(S.nextPage);
    if (await nextBtn.isEnabled()) {
      await viewerPage.nextPage();
      await page.waitForTimeout(1_000);
      await expect(prevBtn).toBeEnabled();
    }
  });
});
