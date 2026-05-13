import { test, expect } from '../../fixtures/base.fixture';

test.describe('Settings Modal', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should open settings modal when gear icon is clicked', async ({
    settingsPage,
  }) => {
    await settingsPage.open();
    await expect(settingsPage.dialog).toBeVisible();
    await expect(settingsPage.title).toHaveText('Settings');
  });

  test('LLM Providers section has been removed', async ({ settingsPage }) => {
    await settingsPage.open();
    await expect(settingsPage.dialog.getByText('LLM Providers')).toHaveCount(0);
    // And no provider names leak through.
    for (const name of ['Gemini', 'OpenAI', 'Claude', 'GPT']) {
      await expect(settingsPage.dialog.getByText(name, { exact: true })).toHaveCount(0);
    }
  });

  test('should display Pinecone vector database', async ({ settingsPage }) => {
    await settingsPage.open();
    await expect(settingsPage.dialog.locator('text=Pinecone')).toBeVisible();
  });

  test('should display storage section', async ({ settingsPage }) => {
    await settingsPage.open();
    await expect(settingsPage.dialog.locator('text=Local Storage')).toBeVisible();
  });

  test('should close via close button', async ({ settingsPage }) => {
    await settingsPage.open();
    await settingsPage.closeViaButton();
    expect(await settingsPage.isOpen()).toBeFalsy();
  });

  test('should close via Escape key', async ({ settingsPage }) => {
    await settingsPage.open();
    await settingsPage.closeViaEscape();
    expect(await settingsPage.isOpen()).toBeFalsy();
  });

  test('should close via backdrop click', async ({ settingsPage }) => {
    await settingsPage.open();
    await settingsPage.closeViaBackdrop();
    expect(await settingsPage.isOpen()).toBeFalsy();
  });

  test('should have focus trap (Tab does not escape dialog)', async ({
    page,
    settingsPage,
  }) => {
    await settingsPage.open();

    // Give the dialog time to set up focus trap
    await page.waitForTimeout(200);

    // Tab multiple times — focus should remain within the dialog
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(50);
    }

    // Focus should still be inside the dialog or its backdrop
    const isInsideModal = await page.evaluate(() => {
      const el = document.activeElement;
      const dialog = document.querySelector('[role="dialog"]');
      const backdrop = document.querySelector('[role="presentation"]');
      return (dialog?.contains(el) ?? false) || (backdrop?.contains(el) ?? false);
    });
    expect(isInsideModal).toBeTruthy();
  });
});
