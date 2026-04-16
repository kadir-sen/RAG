import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

export class SidebarPage {
  readonly page: Page;
  readonly sidebar: Locator;
  readonly newChatButton: Locator;
  readonly addFilesButton: Locator;
  readonly exportLink: Locator;
  readonly fileInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.sidebar = page.locator(S.sidebar);
    this.newChatButton = page.locator(S.newChatButton);
    this.addFilesButton = page.locator(S.addFilesButton);
    this.exportLink = page.locator(S.exportLink);
    this.fileInput = page.locator(S.fileInput);
  }

  async createNewChat() {
    await this.newChatButton.click();
    // Wait for UI to reset
    await this.page.waitForTimeout(500);
  }

  async selectConversation(title: string) {
    await this.page.locator(`.truncate:has-text("${title}")`).click();
  }

  async hoverConversation(title: string) {
    const item = this.page.locator(`.truncate:has-text("${title}")`).locator('..');
    await item.hover();
  }

  async renameConversation(currentTitle: string, newTitle: string) {
    // Hover to reveal rename button
    const item = this.page.locator(`.truncate:has-text("${currentTitle}")`).locator('..');
    await item.hover();

    // Click rename button
    await item.locator(S.renameButton).click();

    // Type new name and confirm
    const input = item.locator('input');
    await input.clear();
    await input.fill(newTitle);
    await input.press('Enter');
  }

  async deleteConversation(title: string) {
    const item = this.page.locator(`.truncate:has-text("${title}")`).locator('..');
    await item.hover();
    await item.locator(S.deleteButton).click();
  }

  async uploadFile(filePath: string) {
    await this.fileInput.setInputFiles(filePath);
  }

  async uploadMultipleFiles(filePaths: string[]) {
    await this.fileInput.setInputFiles(filePaths);
  }

  async getConversationCount(): Promise<number> {
    return this.page.locator(S.recentChats).count();
  }

  async isVisible(): Promise<boolean> {
    const sidebar = this.page.locator(S.sidebar);
    const ariaHidden = await sidebar.getAttribute('aria-hidden');
    return ariaHidden === 'false';
  }
}
