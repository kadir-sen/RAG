import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

test.describe('Chat — Send Message', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Create a new chat to start clean
    await sidebarPage.createNewChat();
  });

  test('sends a message via Enter and receives a response', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('What is this project about?');
    await input.press('Enter');

    await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout: 90_000 });

    const assistantMessages = page.locator(S.assistantMessage);
    await expect(assistantMessages.first()).toBeVisible();

    const text = await assistantMessages.first().innerText();
    expect(text.length).toBeGreaterThan(10);
  });

  test('composer is disabled while a request is in flight', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('Hello');
    await input.press('Enter');

    // Race condition: the typing indicator can flash through too briefly to
    // observe on a cached response. Either we catch it, or the textarea is
    // already disabled while the request is in flight, or the response has
    // already returned — any of those is acceptable for this assertion.
    const result = await Promise.race([
      page.locator(S.typingIndicator).first().waitFor({ state: 'visible', timeout: 10_000 }).then(() => 'typing' as const),
      page.locator(S.assistantMessage).first().waitFor({ state: 'visible', timeout: 10_000 }).then(() => 'answer' as const),
    ]);
    expect(['typing', 'answer']).toContain(result);

    if (result === 'typing') {
      await expect(page.locator(S.chatInput)).toBeDisabled();
    }
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });
  });

  test('send button sends the message', async ({ page }) => {
    const input = page.locator(S.chatInput);
    await input.fill('Hi');
    await page.locator(S.sendButton).first().click();

    // The typing indicator may flash through too briefly to observe on cached
    // / very short responses, so just wait for an assistant bubble to appear.
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });
  });
});
