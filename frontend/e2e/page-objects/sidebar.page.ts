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
    // After the UI refresh the primary action lives in the Knowledge Base
    // section labelled "AI Assistant" (S.sidebarNewChat). Fall back to the
    // legacy "New Chat" pill if a future revert brings it back.
    this.newChatButton = page.locator(`${S.sidebarNewChat}, ${S.newChatButton}`).first();
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

  // ── Library folders (Documents / Correspondence / Spreadsheet) ──

  folderHeader(name: 'Documents' | 'Correspondence' | 'Spreadsheet'): Locator {
    return this.page.locator(S.folderHeader(name));
  }

  async folderIsExpanded(
    name: 'Documents' | 'Correspondence' | 'Spreadsheet',
  ): Promise<boolean> {
    const v = await this.folderHeader(name).getAttribute('aria-expanded');
    return v === 'true';
  }

  async openFolder(name: 'Documents' | 'Correspondence' | 'Spreadsheet') {
    if (!(await this.folderIsExpanded(name))) {
      await this.folderHeader(name).click();
      await expect(this.folderHeader(name)).toHaveAttribute('aria-expanded', 'true');
    }
  }

  async closeFolder(name: 'Documents' | 'Correspondence' | 'Spreadsheet') {
    if (await this.folderIsExpanded(name)) {
      await this.folderHeader(name).click();
      await expect(this.folderHeader(name)).toHaveAttribute('aria-expanded', 'false');
    }
  }

  /** Reads the trailing count badge inside the folder header. */
  async folderCount(
    name: 'Documents' | 'Correspondence' | 'Spreadsheet',
  ): Promise<number> {
    // The header layout puts the count in the last <span> of the row.
    const text = (await this.folderHeader(name).locator('span').last().innerText()).trim();
    const n = parseInt(text, 10);
    return Number.isFinite(n) ? n : -1;
  }
}
