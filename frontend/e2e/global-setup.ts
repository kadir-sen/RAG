import { request } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '.env.e2e') });

export default async function globalSetup() {
  const baseURL =
    process.env.BASE_URL || 'https://rag-chatbot-357290910216.europe-west1.run.app';

  console.log(`\n[E2E Setup] Testing against: ${baseURL}`);

  // Verify the app is reachable
  const api = await request.newContext({ baseURL });
  try {
    const resp = await api.get('/api/conversations');
    if (resp.ok()) {
      console.log('[E2E Setup] API is reachable ✓');
    } else {
      console.warn(`[E2E Setup] API returned ${resp.status()} — tests may fail`);
    }
  } catch (err) {
    console.error('[E2E Setup] Cannot reach API:', err);
  } finally {
    await api.dispose();
  }
}
