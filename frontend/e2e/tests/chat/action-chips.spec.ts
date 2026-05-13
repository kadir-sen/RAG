import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Chat action chips (Programs strip)', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('renders both Correspondence and Document Analysis chips', async ({ page }) => {
    await expect(page.locator(S.actionChipsStrip)).toBeVisible();
    await expect(page.locator(S.chipCorrespondence)).toBeVisible();
    await expect(page.locator(S.chipDocumentAnalysis)).toBeVisible();
  });

  test('chips strip sits above the composer in vertical order', async ({ page }) => {
    const stripBox = await page.locator(S.actionChipsStrip).boundingBox();
    const composerBox = await page.locator(S.chatInput).boundingBox();
    expect(stripBox, 'action chips strip has no layout box').not.toBeNull();
    expect(composerBox, 'composer has no layout box').not.toBeNull();
    if (stripBox && composerBox) {
      expect(stripBox.y).toBeLessThan(composerBox.y);
    }
  });

  test('clicking the Correspondence chip activates correspondence mode', async ({ page }) => {
    await page.locator(S.chipCorrespondence).click();
    await expect(page.locator(S.chipCorrespondence)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('CORRESPONDENCE MODE').first()).toBeVisible({ timeout: 5_000 });

    await page.locator(S.backButton).click();
    await expect(page.locator(S.chipCorrespondence)).toHaveAttribute('aria-pressed', 'false');
  });

  test('clicking the Document Analysis chip activates document analysis mode', async ({ page }) => {
    await page.locator(S.chipDocumentAnalysis).click();
    await expect(page.locator(S.chipDocumentAnalysis)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('DOCUMENT ANALYSIS').first()).toBeVisible({ timeout: 5_000 });
  });
});
