import apiClient from './client';

/**
 * Downloading a file the API generates.
 *
 * These endpoints need the bearer token, so the file arrives as an XHR blob
 * rather than through a plain link, and the browser has to be handed it here.
 * Lifted out of chronologyApi.ts when the chat-answer export needed the same
 * thing — one copy, because the two fiddly parts (reading the server's filename
 * out of content-disposition, and not revoking the object URL too early for
 * Safari) are exactly what a second implementation gets wrong.
 */

/* An unfiltered export builds a document over the whole record, which takes the
   server a while. The client's default 120s would abandon a request the server
   was going to answer, and the user would see a failure over a file that then
   never arrives. */
export const DOWNLOAD_TIMEOUT = 10 * 60 * 1000;

/** Save a blob, preferring the name the server sent over `fallback`. */
export function saveBlob(
  blob: Blob,
  headers: Record<string, unknown>,
  fallback: string,
) {
  const disposition = String(headers['content-disposition'] ?? '');
  const named = /filename="?([^"]+)"?/.exec(disposition)?.[1];
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = named || fallback;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking immediately can cancel the download in Safari; one tick is enough.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** GET a generated file and hand it to the browser. */
export async function downloadGet(
  path: string,
  fallback: string,
  params?: Record<string, unknown>,
) {
  const res = await apiClient.get(path, {
    responseType: 'blob',
    timeout: DOWNLOAD_TIMEOUT,
    params,
  });
  saveBlob(res.data as Blob, res.headers as Record<string, unknown>, fallback);
}

/** POST a payload and hand the generated file to the browser. */
export async function downloadPost(
  path: string,
  body: unknown,
  fallback: string,
) {
  const res = await apiClient.post(path, body, {
    responseType: 'blob',
    timeout: DOWNLOAD_TIMEOUT,
  });
  saveBlob(res.data as Blob, res.headers as Record<string, unknown>, fallback);
}
