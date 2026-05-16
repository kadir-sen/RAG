import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Top Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should toggle sidebar open/close', async ({ page }) => {
    // Sidebar should be open by default
    const sidebar = page.locator(S.sidebar);
    const initialHidden = await sidebar.getAttribute('aria-hidden');

    // Click toggle
    await page.locator(S.sidebarToggle).click();
    await page.waitForTimeout(400); // transition duration

    const afterToggle = await sidebar.getAttribute('aria-hidden');
    expect(afterToggle).not.toBe(initialHidden);

    // Toggle back
    await page.locator(S.sidebarToggle).click();
    await page.waitForTimeout(400);

    const afterRestore = await sidebar.getAttribute('aria-hidden');
    expect(afterRestore).toBe(initialHidden);
  });

  test('should change aria-expanded on sidebar toggle', async ({ page }) => {
    const toggle = page.locator(S.sidebarToggle);
    const initialExpanded = await toggle.getAttribute('aria-expanded');

    await toggle.click();
    await page.waitForTimeout(400);

    const afterExpanded = await toggle.getAttribute('aria-expanded');
    expect(afterExpanded).not.toBe(initialExpanded);
  });

  test('should open settings modal from top nav', async ({ page }) => {
    await page.locator(S.settingsButton).click();
    await expect(page.locator(S.settingsDialog)).toBeVisible({ timeout: 3_000 });
  });

  test('should display the COAir brand', async ({ page }) => {
    await expect(page.locator(S.branding)).toBeVisible();
    await expect(page.locator(S.branding).getByText('CO', { exact: true })).toBeVisible();
    await expect(page.locator(S.branding).getByText('Air', { exact: true })).toBeVisible();
  });

  test('should display user avatar', async ({ page }) => {
    await expect(page.locator(S.userAvatar)).toBeVisible();
  });
});
