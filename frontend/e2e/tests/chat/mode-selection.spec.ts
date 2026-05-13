import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Mode Selection', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('should enter Correspondence Mode when card is clicked', async ({
    page,
    welcomePage,
  }) => {
    await welcomePage.selectCorrespondenceMode();

    // Mode header chip in ChatPage shows "CORRESPONDENCE MODE" (uppercase).
    await expect(page.getByText('CORRESPONDENCE MODE').first()).toBeVisible({ timeout: 5_000 });

    // Back button should be visible
    await expect(page.locator(S.backButton)).toBeVisible();
  });

  test('should enter Document Analysis mode when card is clicked', async ({
    page,
    welcomePage,
  }) => {
    await welcomePage.selectDocumentAnalysisMode();

    // Mode header chip in ChatPage shows "DOCUMENT ANALYSIS" (uppercase).
    await expect(page.getByText('DOCUMENT ANALYSIS').first()).toBeVisible({ timeout: 5_000 });

    // Back button should be visible
    await expect(page.locator(S.backButton)).toBeVisible();
  });

  test('should return to welcome screen via Back button', async ({
    page,
    welcomePage,
  }) => {
    // Enter a mode
    await welcomePage.selectCorrespondenceMode();
    await expect(page.locator(S.backButton)).toBeVisible();

    // Click back
    await page.locator(S.backButton).click();

    // Welcome screen should reappear
    await welcomePage.waitForVisible();
    await expect(welcomePage.correspondenceCard).toBeVisible();
  });
});
