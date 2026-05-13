import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Welcome Screen', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('shows the welcome heading', async ({ welcomePage }) => {
    await welcomePage.waitForVisible();
    await expect(welcomePage.heading).toBeVisible();
  });

  test('shows the Correspondence and Document Analysis tiles', async ({ welcomePage }) => {
    await expect(welcomePage.correspondenceCard).toBeVisible();
    await expect(welcomePage.documentAnalysisCard).toBeVisible();
  });

  test('no inline search input is rendered (composer is now bottom-anchored)', async ({ page }) => {
    await expect(page.locator('#welcome-search')).toHaveCount(0);
  });

  test('no "Try asking" example query buttons are rendered', async ({ page }) => {
    const categories = ['MANPOWER', 'EQUIPMENT', 'PROGRESS', 'CONTRACT', 'NOTICES', 'TREND'];
    for (const cat of categories) {
      const count = await page.locator(`button >> text="${cat}"`).count();
      expect(count, `Stale example chip "${cat}" still rendered`).toBe(0);
    }
  });

  test('mode tiles navigate into their mode screens', async ({ page, welcomePage }) => {
    await welcomePage.selectCorrespondenceMode();
    await expect(page.getByText('CORRESPONDENCE MODE').first()).toBeVisible({ timeout: 5_000 });

    await page.locator(S.backButton).click();
    await welcomePage.waitForVisible();

    await welcomePage.selectDocumentAnalysisMode();
    await expect(page.getByText('DOCUMENT ANALYSIS').first()).toBeVisible({ timeout: 5_000 });
  });
});
