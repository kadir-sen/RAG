import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

export class WelcomePage {
  readonly page: Page;
  readonly searchInput: Locator;
  readonly sendButton: Locator;
  readonly heading: Locator;
  readonly correspondenceCard: Locator;
  readonly documentAnalysisCard: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.locator(S.welcomeSearch);
    this.sendButton = page.locator(S.sendButton).first();
    this.heading = page.locator('h1');
    this.correspondenceCard = page.locator(S.correspondenceCard);
    this.documentAnalysisCard = page.locator(S.documentAnalysisCard);
  }

  async isVisible() {
    return this.heading.isVisible();
  }

  async waitForVisible() {
    await expect(this.heading).toBeVisible({ timeout: 10_000 });
  }

  async searchAndSend(text: string) {
    await this.searchInput.fill(text);
    await this.searchInput.press('Enter');
  }

  async selectCorrespondenceMode() {
    await this.correspondenceCard.click();
  }

  async selectDocumentAnalysisMode() {
    await this.documentAnalysisCard.click();
  }

  async clickExampleQuery(queryText: string) {
    await this.page.locator(S.exampleQuery(queryText)).click();
  }

  async getExampleQueryCount(): Promise<number> {
    // Example queries are buttons under "Try asking" section
    return this.page.locator('button:below(:text("Try asking"))').count();
  }
}
