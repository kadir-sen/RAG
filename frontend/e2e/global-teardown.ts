import { request } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';
import { cleanupTestConversations } from './helpers/api-helpers';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '.env.e2e') });

export default async function globalTeardown() {
  const baseURL =
    process.env.BASE_URL || 'https://rag-chatbot-357290910216.europe-west1.run.app';

  const api = await request.newContext({ baseURL });
  try {
    await cleanupTestConversations(api);
    console.log('[E2E Teardown] Test conversations cleaned up ✓');
  } catch (err) {
    console.warn('[E2E Teardown] Cleanup failed:', err);
  } finally {
    await api.dispose();
  }
}
