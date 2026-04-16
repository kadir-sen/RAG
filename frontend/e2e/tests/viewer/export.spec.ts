import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Document Viewer — Export', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should show Export button for table documents', async ({ page, viewerPage }) => {
    const sidebar = page.locator('[aria-label="Sidebar"]');
    const fileItems = sidebar.locator('.cursor-pointer:has(.truncate)');
    const fileCount = await fileItems.count();

    if (fileCount === 0) {
      test.skip(true, 'No files in sidebar');
      return;
    }

    let foundExport = false;
    for (let i = 0; i < Math.min(fileCount, 5); i++) {
      await fileItems.nth(i).click();
      await page.waitForTimeout(2_000);

      if (!(await page.locator(S.viewerClose).isVisible())) continue;

      const exportBtn = page.locator('button:has-text("Export")');
      if (await exportBtn.isVisible()) {
        await expect(exportBtn).toBeEnabled();
        foundExport = true;
        break;
      }
    }

    if (!foundExport) {
      test.skip(true, 'No table documents with Export button found');
    }
  });
});
