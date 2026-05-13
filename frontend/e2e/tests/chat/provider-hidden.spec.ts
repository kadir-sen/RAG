import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Hard guard: no LLM provider name or model id may leak into the rendered
 * DOM. The user is never supposed to know which model is answering.
 */
test.describe('Provider names are hidden', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('home / welcome surface contains no provider strings', async ({ page }) => {
    const body = page.locator('body');
    for (const needle of ['Gemini', 'OpenAI', 'Claude', 'GPT', 'claude-sonnet', 'gemini-2.5', 'gpt-4']) {
      await expect(body).not.toContainText(needle);
    }
  });

  test('after sending a message the assistant bubble shows no provider name', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('Briefly list the document types you have.');
    await page.locator(S.sendButton).click();

    // Wait until an assistant bubble exists. We do not assert on its content text
    // beyond ensuring it is non-empty, since we only care that provider names are absent.
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });

    const body = page.locator('body');
    for (const needle of ['Gemini', 'OpenAI', 'Claude', 'GPT', 'claude-sonnet', 'gemini-2.5', 'gpt-4']) {
      await expect(body).not.toContainText(needle);
    }
  });

  test('settings dialog contains no provider strings', async ({ settingsPage }) => {
    await settingsPage.open();
    for (const needle of ['Gemini', 'OpenAI', 'Claude', 'GPT', 'LLM Providers']) {
      await expect(settingsPage.dialog).not.toContainText(needle);
    }
  });
});
