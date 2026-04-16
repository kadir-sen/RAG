import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

export class ChatPage {
  readonly page: Page;
  readonly chatInput: Locator;
  readonly sendButton: Locator;
  readonly chatLog: Locator;
  readonly typingIndicator: Locator;

  constructor(page: Page) {
    this.page = page;
    this.chatInput = page.locator(S.chatInput);
    this.sendButton = page.locator(S.sendButton).first();
    this.chatLog = page.locator(S.chatLog);
    this.typingIndicator = page.locator(S.typingIndicator);
  }

  async sendMessage(text: string) {
    await this.chatInput.fill(text);
    await this.sendButton.click();
  }

  async sendMessageViaEnter(text: string) {
    await this.chatInput.fill(text);
    await this.chatInput.press('Enter');
  }

  async sendMessageAndWait(text: string, timeout = 90_000) {
    await this.sendMessage(text);
    // Wait for typing indicator to appear then disappear
    await expect(this.typingIndicator).toBeVisible({ timeout: 10_000 });
    await expect(this.typingIndicator).not.toBeVisible({ timeout });
  }

  async getLastAssistantMessage(): Promise<string> {
    const messages = this.page.locator(S.assistantMessage);
    const count = await messages.count();
    if (count === 0) return '';
    return messages.nth(count - 1).innerText();
  }

  async getAssistantMessageCount(): Promise<number> {
    return this.page.locator(S.assistantMessage).count();
  }

  async isSendDisabled(): Promise<boolean> {
    return this.sendButton.isDisabled();
  }
}
