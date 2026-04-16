import { test as base } from '@playwright/test';
import { ChatPage } from '../page-objects/chat.page';
import { WelcomePage } from '../page-objects/welcome.page';
import { SidebarPage } from '../page-objects/sidebar.page';
import { ViewerPage } from '../page-objects/viewer.page';
import { SettingsPage } from '../page-objects/settings.page';

/**
 * Extended test fixture that injects page objects into every test.
 */
export const test = base.extend<{
  chatPage: ChatPage;
  welcomePage: WelcomePage;
  sidebarPage: SidebarPage;
  viewerPage: ViewerPage;
  settingsPage: SettingsPage;
}>({
  chatPage: async ({ page }, use) => {
    await use(new ChatPage(page));
  },
  welcomePage: async ({ page }, use) => {
    await use(new WelcomePage(page));
  },
  sidebarPage: async ({ page }, use) => {
    await use(new SidebarPage(page));
  },
  viewerPage: async ({ page }, use) => {
    await use(new ViewerPage(page));
  },
  settingsPage: async ({ page }, use) => {
    await use(new SettingsPage(page));
  },
});

export { expect } from '@playwright/test';
