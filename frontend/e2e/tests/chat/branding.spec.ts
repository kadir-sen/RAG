import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Branding — Asistant', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('document title is "Asistant"', async ({ page }) => {
    await expect(page).toHaveTitle('Asistant');
  });

  test('TopNav surfaces the Asistant brand', async ({ page }) => {
    const banner = page.locator(S.branding);
    await expect(banner).toBeVisible();
    await expect(banner.getByText('Asistant', { exact: true })).toBeVisible();
  });

  test('no "Construction" / "ConstructionIQ" string appears anywhere in the visible UI', async ({ page }) => {
    // Body must not contain the legacy brand.
    await expect(page.locator('body')).not.toContainText(/Construction(IQ)?/i);
  });

  test('legacy "CIQ" monogram is no longer rendered', async ({ page }) => {
    // The welcome hero used to show "CIQ" — must be gone.
    const ciqHits = await page.getByText('CIQ', { exact: true }).count();
    expect(ciqHits).toBe(0);
  });
});
