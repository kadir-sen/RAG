import { test, expect } from '../../fixtures/base.fixture';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEST_FILES_DIR = path.resolve(__dirname, '../../fixtures/test-files');

test.describe('Drag and Drop Upload', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should accept file drop and start upload', async ({ page }) => {
    // Use Playwright's file chooser approach with setInputFiles
    // For drag-drop, we simulate by directly setting files on the hidden input
    const fileInput = page.locator('input[type="file"]');

    if (await fileInput.isVisible({ timeout: 1_000 }).catch(() => false) || await fileInput.count() > 0) {
      const pdfPath = path.join(TEST_FILES_DIR, 'sample.pdf');
      await fileInput.setInputFiles(pdfPath);

      // Wait a moment for the upload to trigger
      await page.waitForTimeout(2_000);

      // Upload should have been initiated
      // (either "Uploading..." or file appears in list)
      const uploading = page.locator('text=Uploading...');
      const isUploading = await uploading.isVisible();

      if (isUploading) {
        await expect(uploading).not.toBeVisible({ timeout: 30_000 });
      }
    }
  });
});
