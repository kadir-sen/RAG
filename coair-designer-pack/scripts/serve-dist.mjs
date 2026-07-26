/**
 * Serves `dist/` with the exact security headers and SPA rewrite the
 * deployed site uses (see vercel.json / netlify.toml), so `npm run smoke`
 * exercises the real production conditions — including whether the CSP
 * would block the pre-paint boot script or the web fonts.
 *
 *   npm run build && npm run serve:dist
 */
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const ROOT = 'dist';
const PORT = Number(process.env.PORT ?? 4180);

const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
  "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; " +
  "frame-ancestors 'none'; base-uri 'self'; form-action 'self'";

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json',
};

createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  let path = join(ROOT, normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, ''));

  try {
    if ((await stat(path)).isDirectory()) path = join(path, 'index.html');
  } catch {
    // Client-side routing: anything that is not a real file is the SPA shell.
    path = join(ROOT, 'index.html');
  }

  try {
    const body = await readFile(path);
    const ext = extname(path);
    const hashed = path.includes(`${ROOT}/assets/`);
    res.writeHead(200, {
      'Content-Type': TYPES[ext] ?? 'application/octet-stream',
      'Content-Security-Policy': CSP,
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'no-referrer',
      'Cache-Control': hashed
        ? 'public, max-age=31536000, immutable'
        : 'public, max-age=0, must-revalidate',
    });
    res.end(body);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found');
  }
}).listen(PORT, () => {
  console.log(`dist/ served with production headers → http://localhost:${PORT}`);
});
