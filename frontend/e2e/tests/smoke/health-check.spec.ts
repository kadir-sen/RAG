import { test, expect } from '../../fixtures/base.fixture';

test.describe('API Health Checks', () => {
  test('GET /api/conversations should return 200', async ({ request }) => {
    const response = await request.get('/api/conversations');
    expect(response.status()).toBe(200);
  });

  test('GET /api/files should return 200', async ({ request }) => {
    const response = await request.get('/api/files');
    expect(response.status()).toBe(200);
  });

  test('GET /api/library should return 200', async ({ request }) => {
    const response = await request.get('/api/library');
    expect(response.status()).toBe(200);
  });

  test('GET /api/library/summary should return 200', async ({ request }) => {
    const response = await request.get('/api/library/summary');
    expect(response.status()).toBe(200);

    const data = await response.json();
    expect(data).toHaveProperty('total_files');
    expect(data).toHaveProperty('by_file_type');
  });
});
