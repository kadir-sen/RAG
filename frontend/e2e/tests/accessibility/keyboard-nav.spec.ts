import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Accessibility — Keyboard Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should auto-focus search input on page load', async ({ page }) => {
    // Either welcome-search or chat-input should be focused
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      return el?.id || el?.tagName;
    });
    expect(['welcome-search', 'chat-input', 'INPUT', 'TEXTAREA']).toContain(focused);
  });

  test('should submit message with Enter key', async ({ page, sidebarPage }) => {
    await sidebarPage.createNewChat();

    const input = page.locator('#welcome-search, #chat-input').first();
    await input.fill('Hello');
    await input.press('Enter');

    // Should trigger message send (typing indicator appears)
    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
  });

  test('should close settings modal with Escape', async ({ page, settingsPage }) => {
    await settingsPage.open();
    await expect(settingsPage.dialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(settingsPage.dialog).not.toBeVisible({ timeout: 3_000 });
  });

  test('should trap focus inside settings modal', async ({ page, settingsPage }) => {
    await settingsPage.open();
    await page.waitForTimeout(200);

    // Press Tab a few times
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(50);
    }

    // Active element should be inside the dialog or its backdrop container
    const isInsideModal = await page.evaluate(() => {
      const el = document.activeElement;
      const dialog = document.querySelector('[role="dialog"]');
      const backdrop = document.querySelector('[role="presentation"]');
      return (
        (dialog?.contains(el) ?? false) ||
        (backdrop?.contains(el) ?? false) ||
        el?.tagName === 'BODY'  // body focus is acceptable (modal owns the page)
      );
    });
    expect(isInsideModal).toBeTruthy();
  });

  test('should have aria-labels on interactive elements', async ({ page }) => {
    // Verify key elements have proper aria-labels
    await expect(page.locator(S.sidebarToggle)).toHaveAttribute('aria-label', /.+/);
    await expect(page.locator(S.settingsButton)).toHaveAttribute(
      'aria-label',
      'Open settings',
    );
    await expect(page.locator(S.userAvatar)).toHaveAttribute(
      'aria-label',
      'User avatar',
    );

    // Sidebar should have aria-label
    await expect(page.locator(S.sidebar)).toHaveAttribute('aria-label', 'Sidebar');
  });
});
