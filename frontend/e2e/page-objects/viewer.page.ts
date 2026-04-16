import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

export class ViewerPage {
  readonly page: Page;
  readonly closeButton: Locator;
  readonly prevButton: Locator;
  readonly nextButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.closeButton = page.locator(S.viewerClose);
    this.prevButton = page.locator(S.prevPage);
    this.nextButton = page.locator(S.nextPage);
  }

  async waitForOpen(timeout = 10_000) {
    await expect(this.closeButton).toBeVisible({ timeout });
  }

  async close() {
    await this.closeButton.click();
    await expect(this.closeButton).not.toBeVisible({ timeout: 3_000 });
  }

  async nextPage() {
    await this.nextButton.click();
  }

  async prevPage() {
    await this.prevButton.click();
  }

  async isNextDisabled(): Promise<boolean> {
    return this.nextButton.isDisabled();
  }

  async isPrevDisabled(): Promise<boolean> {
    return this.prevButton.isDisabled();
  }

  async getFileName(): Promise<string> {
    // First span in the toolbar is the filename
    const toolbar = this.closeButton.locator('..');
    return toolbar.locator('span').first().innerText();
  }
}
