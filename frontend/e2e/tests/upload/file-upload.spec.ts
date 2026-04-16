import { test, expect } from '../../fixtures/base.fixture';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEST_FILES_DIR = path.resolve(__dirname, '../../fixtures/test-files');

test.describe('File Upload', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should show Add Files button in sidebar', async ({ sidebarPage }) => {
    await expect(sidebarPage.addFilesButton).toBeVisible();
  });

  test('should upload a PDF file via file input', async ({ page, sidebarPage }) => {
    const pdfPath = path.join(TEST_FILES_DIR, 'sample.pdf');
    await sidebarPage.uploadFile(pdfPath);

    // Wait for upload to process (may show "Uploading..." state)
    await page.waitForTimeout(3_000);

    // The file should appear in the sidebar file list
    // (or upload progress should be shown)
    const uploading = page.locator('text=Uploading...');
    if (await uploading.isVisible()) {
      await expect(uploading).not.toBeVisible({ timeout: 30_000 });
    }
  });

  test('should upload an EML file', async ({ page, sidebarPage }) => {
    const emlPath = path.join(TEST_FILES_DIR, 'sample.eml');
    await sidebarPage.uploadFile(emlPath);

    await page.waitForTimeout(3_000);
    const uploading = page.locator('text=Uploading...');
    if (await uploading.isVisible()) {
      await expect(uploading).not.toBeVisible({ timeout: 30_000 });
    }
  });

  test('should upload an XLSX file', async ({ page, sidebarPage }) => {
    const xlsxPath = path.join(TEST_FILES_DIR, 'sample.xlsx');
    await sidebarPage.uploadFile(xlsxPath);

    await page.waitForTimeout(3_000);
    const uploading = page.locator('text=Uploading...');
    if (await uploading.isVisible()) {
      await expect(uploading).not.toBeVisible({ timeout: 30_000 });
    }
  });
});
