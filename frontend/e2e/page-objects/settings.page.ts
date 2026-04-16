import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

export class SettingsPage {
  readonly page: Page;
  readonly dialog: Locator;
  readonly title: Locator;
  readonly closeButton: Locator;
  readonly backdrop: Locator;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.locator(S.settingsDialog);
    this.title = page.locator(S.settingsTitle);
    this.closeButton = page.locator(S.settingsClose);
    this.backdrop = page.locator(S.settingsBackdrop);
  }

  async open() {
    await this.page.locator(S.settingsButton).click();
    await expect(this.dialog).toBeVisible({ timeout: 3_000 });
  }

  async closeViaButton() {
    await this.closeButton.click();
    await expect(this.dialog).not.toBeVisible({ timeout: 3_000 });
  }

  async closeViaEscape() {
    await this.page.keyboard.press('Escape');
    await expect(this.dialog).not.toBeVisible({ timeout: 3_000 });
  }

  async closeViaBackdrop() {
    // Click on the backdrop (outside the dialog)
    await this.backdrop.click({ position: { x: 10, y: 10 } });
    await expect(this.dialog).not.toBeVisible({ timeout: 3_000 });
  }

  async isOpen(): Promise<boolean> {
    return this.dialog.isVisible();
  }

  async hasProvider(name: string): Promise<boolean> {
    return this.dialog.locator(`text=${name}`).isVisible();
  }

  async getProviderNames(): Promise<string[]> {
    const items = this.dialog.locator('.text-sm.font-medium');
    const count = await items.count();
    const names: string[] = [];
    for (let i = 0; i < count; i++) {
      names.push(await items.nth(i).innerText());
    }
    return names;
  }
}
