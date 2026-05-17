import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Mode toggle lives in the sidebar — the chat thread itself must remain
 * clean (no "Programs" strip above the composer).
 */
test.describe('Sidebar mode toggle', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('renders both Correspondence and Document Analysis options in the sidebar', async ({ page }) => {
    await expect(page.locator(S.modeToggle)).toBeVisible();
    await expect(page.locator(S.chipCorrespondence)).toBeVisible();
    await expect(page.locator(S.chipDocumentAnalysis)).toBeVisible();
  });

  test('chat thread does not show a "Programs" header', async ({ page }) => {
    await expect(page.getByText('Programs', { exact: true })).toHaveCount(0);
  });

  test('clicking Correspondence activates correspondence mode', async ({ page }) => {
    await page.locator(S.chipCorrespondence).click();
    await expect(page.locator(S.chipCorrespondence)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('CORRESPONDENCE MODE').first()).toBeVisible({ timeout: 5_000 });

    await page.locator(S.backButton).click();
    await expect(page.locator(S.chipCorrespondence)).toHaveAttribute('aria-pressed', 'false');
  });

  test('clicking Document Analysis activates document analysis mode', async ({ page }) => {
    await page.locator(S.chipDocumentAnalysis).click();
    await expect(page.locator(S.chipDocumentAnalysis)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('DOCUMENT ANALYSIS').first()).toBeVisible({ timeout: 5_000 });
  });
});
