import { type Page, expect } from '@playwright/test';
import { S } from './selectors';

/**
 * Send a chat message and wait for the AI response to complete.
 * Watches for the typing indicator to appear then disappear.
 */
export async function sendMessageAndWait(
  page: Page,
  message: string,
  options: { timeout?: number; useWelcomeInput?: boolean } = {},
) {
  const { timeout = 90_000, useWelcomeInput = false } = options;
  const inputSelector = useWelcomeInput ? S.welcomeSearch : S.chatInput;

  await page.locator(inputSelector).fill(message);
  await page.locator(inputSelector).press('Enter');

  // Wait for typing indicator to appear (request sent)
  await expect(page.locator(S.typingIndicator)).toBeVisible({ timeout: 10_000 });

  // Wait for typing indicator to disappear (response received)
  await expect(page.locator(S.typingIndicator)).not.toBeVisible({ timeout });
}

/**
 * Wait for a specific API response.
 */
export async function waitForApiResponse(
  page: Page,
  urlPattern: string | RegExp,
  timeout = 60_000,
) {
  return page.waitForResponse(
    (resp) => {
      const matches =
        typeof urlPattern === 'string'
          ? resp.url().includes(urlPattern)
          : urlPattern.test(resp.url());
      return matches && resp.status() === 200;
    },
    { timeout },
  );
}

/**
 * Wait for file upload to complete (progress indicator disappears).
 */
export async function waitForUploadComplete(page: Page, timeout = 30_000) {
  // If "Uploading..." button is visible, wait for it to go back to "Add Files"
  const uploadingBtn = page.locator(S.uploadingButton);
  if (await uploadingBtn.isVisible()) {
    await expect(uploadingBtn).not.toBeVisible({ timeout });
  }
}

/**
 * Create a new conversation via the sidebar and return to a clean state.
 */
export async function createNewChat(page: Page) {
  await page.locator(S.newChatButton).click();
  // Wait for welcome screen or chat input to be ready
  await expect(
    page.locator(`${S.welcomeSearch}, ${S.chatInput}`).first(),
  ).toBeVisible({ timeout: 5_000 });
}
