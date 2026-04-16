import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Chat — Send Message', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Create a new chat to start clean
    await sidebarPage.createNewChat();
  });

  test('should send a message via Enter key and receive a response', async ({
    page,
    chatPage,
  }) => {
    // The welcome search is visible on new chat
    const welcomeInput = page.locator(S.welcomeSearch);
    const chatInput = page.locator(S.chatInput);

    // Use whichever input is visible
    const input = (await welcomeInput.isVisible()) ? welcomeInput : chatInput;

    await input.fill('What is this project about?');
    await input.press('Enter');

    // Typing indicator should appear
    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });

    // Wait for response (up to 90 seconds for LLM)
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    // Assistant message should be visible
    const assistantMessages = page.locator(S.assistantMessage);
    await expect(assistantMessages.first()).toBeVisible();

    // Response should contain some text
    const text = await assistantMessages.first().innerText();
    expect(text.length).toBeGreaterThan(10);
  });

  test('should disable send button while loading', async ({ page }) => {
    const welcomeInput = page.locator(S.welcomeSearch);
    const chatInput = page.locator(S.chatInput);

    const input = (await welcomeInput.isVisible()) ? welcomeInput : chatInput;

    await input.fill('Hello');
    await input.press('Enter');

    // While loading, the chat input should be disabled
    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });

    const chatInputAfter = page.locator(S.chatInput);
    if (await chatInputAfter.isVisible()) {
      await expect(chatInputAfter).toBeDisabled();
    }

    // Wait for completion
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });
  });

  test('should send a message via send button click', async ({ page }) => {
    const welcomeInput = page.locator(S.welcomeSearch);
    const chatInput = page.locator(S.chatInput);

    const input = (await welcomeInput.isVisible()) ? welcomeInput : chatInput;

    await input.fill('Hi');
    await page.locator(S.sendButton).first().click();

    // Should receive a response
    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    await expect(page.locator(S.assistantMessage).first()).toBeVisible();
  });
});
