import { type APIRequestContext } from '@playwright/test';

/**
 * Direct API helpers for test setup/teardown.
 * These bypass the UI for faster, more reliable test preparation.
 */

export async function createConversation(
  api: APIRequestContext,
  title = 'E2E Test Conversation',
) {
  const resp = await api.post('/api/conversations', {
    data: { title },
  });
  return resp.json();
}

export async function deleteConversation(
  api: APIRequestContext,
  conversationId: string,
) {
  await api.delete(`/api/conversations/${conversationId}`);
}

export async function listConversations(api: APIRequestContext) {
  const resp = await api.get('/api/conversations');
  return resp.json();
}

export async function listFiles(api: APIRequestContext) {
  const resp = await api.get('/api/files');
  return resp.json();
}

export async function getLibrary(api: APIRequestContext) {
  const resp = await api.get('/api/library');
  return resp.json();
}

export async function getLibrarySummary(api: APIRequestContext) {
  const resp = await api.get('/api/library/summary');
  return resp.json();
}

/**
 * Clean up all E2E test conversations.
 */
export async function cleanupTestConversations(api: APIRequestContext) {
  const convs = await listConversations(api);
  const testConvs = (convs as { conversation_id: string; title: string }[]).filter(
    (c) => c.title.startsWith('E2E ') || c.title === 'New Chat',
  );
  for (const c of testConvs) {
    await deleteConversation(api, c.conversation_id);
  }
}
