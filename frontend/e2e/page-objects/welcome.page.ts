import { type Page, type Locator, expect } from '@playwright/test';
import { S } from '../helpers/selectors';

/**
 * WelcomePage — covers the no-conversation hero screen.
 *
 * Note: the in-hero search input and "Try asking" example queries were
 * removed in the design refresh. The composer is now bottom-anchored in
 * ChatPage and is exposed via ChatPage helpers, not here.
 */
export class WelcomePage {
  readonly page: Page;
  readonly heading: Locator;
  readonly correspondenceCard: Locator;
  readonly documentAnalysisCard: Locator;

  constructor(page: Page) {
    this.page = page;
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

  async selectCorrespondenceMode() {
    await this.correspondenceCard.click();
  }

  async selectDocumentAnalysisMode() {
    await this.documentAnalysisCard.click();
  }
}
