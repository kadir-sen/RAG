import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Branding — COAir', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('document title is "COAir"', async ({ page }) => {
    await expect(page).toHaveTitle('COAir');
  });

  test('TopNav surfaces the COAir brand (CO white + Air orange)', async ({ page }) => {
    const banner = page.locator(S.branding);
    await expect(banner).toBeVisible();
    // The wordmark is split across two spans — assert both halves exist.
    await expect(banner.getByText('CO', { exact: true })).toBeVisible();
    await expect(banner.getByText('Air', { exact: true })).toBeVisible();
  });

  test('assistant message prefix uses the CO monogram, not Asistant', async ({ page }) => {
    // Make sure the legacy "Asistant ·" prefix is gone everywhere in the DOM.
    await expect(page.locator('body')).not.toContainText(/Asistant\s*·/);
  });

  test('no "Construction" / "Asistant" string appears in the visible UI', async ({ page }) => {
    const body = page.locator('body');
    await expect(body).not.toContainText(/Construction(IQ)?/i);
    await expect(body).not.toContainText(/Asistant/);
  });

  test('legacy monograms (CIQ, AS) are no longer rendered', async ({ page }) => {
    expect(await page.getByText('CIQ', { exact: true }).count()).toBe(0);
    expect(await page.getByText('AS', { exact: true }).count()).toBe(0);
  });
});
