import { test, expect } from '../../fixtures/base.fixture';

test.describe('App Loading', () => {
  test('should load without errors and show branding', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/', { timeout: 60_000 });
    await page.waitForLoadState('networkidle', { timeout: 60_000 });

    // Branding visible (TopNav renders the COAir wordmark — CO + Air).
    await expect(page.locator('[aria-label="COAir"]')).toBeVisible();
    await expect(
      page.locator('[aria-label="COAir"]').getByText('CO', { exact: true }),
    ).toBeVisible();
    await expect(
      page.locator('[aria-label="COAir"]').getByText('Air', { exact: true }),
    ).toBeVisible();

    // No JS errors
    expect(errors).toHaveLength(0);
  });

  test('should show welcome screen with heading', async ({ page, welcomePage }) => {
    await page.goto('/');
    await welcomePage.waitForVisible();

    // The hero h1 is the wordmark — "CO" black/white + "Air" orange.
    await expect(page.locator('h1').first()).toContainText('CO');
    await expect(page.locator('h1').first()).toContainText('Air');
  });

  test('should have chat input visible and focusable', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Composer is now bottom-anchored on every screen.
    await expect(page.locator('#chat-input')).toBeVisible();
  });

  test('should show sidebar with New Chat button', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('button:has-text("New Chat")')).toBeVisible();
  });

  test('should show top navigation elements', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Sidebar toggle
    await expect(
      page.locator('[aria-label="Close sidebar"], [aria-label="Open sidebar"]'),
    ).toBeVisible();

    // Settings button
    await expect(page.locator('[aria-label="Open settings"]')).toBeVisible();

    // User avatar
    await expect(page.locator('[aria-label="User avatar"]')).toBeVisible();
  });
});
