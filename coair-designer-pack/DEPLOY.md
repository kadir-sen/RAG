# Deploying the COAir designer pack

This pack is a **static single-page app**. It builds to `dist/` and can be
served by any static host. There is no server-side component and, in the
default configuration, no backend either.

> ### Read this first
> The pack ships in **designer mode**: `VITE_MOCK=1` in [.env](.env) is baked
> into the bundle at build time, so a deployed build answers every API call
> from the sample fixtures in `src/mocks/`. That is exactly what you want for a
> design review or a stakeholder link — and exactly what you do **not** want to
> mistake for the production app. Anyone who opens the link can sign in with
> any username and password.
>
> To point a build at the real COAir backend instead, set `VITE_MOCK=false` and
> `VITE_API_URL=https://…/api` in `.env` before building, and add that origin
> to `connect-src` in the CSP (see below).

---

## Option A — deploy the prebuilt `dist/`

`dist/` in this archive is already built (Node 24, Vite 7). Drop it on any
static host and you are done:

```bash
# any static file server, e.g.
npx serve dist
```

The host must do two things, both of which the included config files already
express:

1. **Rewrite unknown paths to `/index.html`** — the app uses client-side
   routing, so a direct hit on `/login` or a browser refresh 404s without this.
2. **Never cache `/index.html` or `/boot.js`**, and cache `/assets/*` forever —
   Vite content-hashes everything under `/assets`, nothing else is hashed.

## Option B — build from source

Requires Node 20+ (developed on Node 24).

```bash
npm install
npm run build      # tsc -b && vite build  →  dist/
```

## Host configuration

Both files are included and carry the same security headers as the platform
portal, plus the SPA rewrite and cache rules:

| Host | File | Notes |
|---|---|---|
| Vercel | [vercel.json](vercel.json) | `buildCommand` and `outputDirectory` are set; just import the repo |
| Netlify | [netlify.toml](netlify.toml) | `publish = "dist"`, `command = "npm run build"` |

For **nginx / S3 / CloudFront / Apache**, replicate those two behaviours. nginx:

```nginx
location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location / {
    try_files $uri /index.html;     # SPA rewrite
    add_header Cache-Control "public, max-age=0, must-revalidate";
}
```

### Content-Security-Policy

The included policy is the portal's, widened only for the two Google Fonts
origins the app loads Inter and JetBrains Mono from:

```
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com
font-src  'self' https://fonts.gstatic.com
```

Two things worth knowing:

- **The pre-paint theme script is a separate file** ([public/boot.js](public/boot.js)),
  not an inline `<script>`, precisely so `script-src 'self'` can stay strict.
  If you inline it again, the CSP will block it and the app will flash the
  wrong ground on load.
- **Self-hosting the two font families** collapses the policy back to `'self'`
  everywhere and removes the third-party request entirely. Worth doing before
  this goes anywhere client-facing.
- `connect-src 'self'` is correct only while `VITE_MOCK=1`. A build pointed at
  a real backend needs that API origin added.

---

## Verifying a build before you ship it

```bash
npm run build
npm run serve:dist          # serves dist/ with the real production headers
PACK_URL=http://localhost:4180 npm run smoke
```

`npm run smoke` drives a real browser through login → welcome → cited answer →
document viewer → SQL result → email trace → both workspace modes → settings →
CSV export → theme toggle, in **both** the drawing-sheet and blueprint grounds,
and fails on any console error, page error, or failed request. `serve:dist`
applies the same CSP and cache headers as the deployed site, so a CSP
regression fails locally rather than in production.

To refresh the reference images in `screenshots/`:

```bash
npm run dev                 # in one terminal
npm run screenshots         # in another
```

## What is not in this archive

- `node_modules/` — run `npm install`.
- `e2e/` — the Playwright suite that targets the **live** platform. It is
  omitted deliberately: it is not needed to build, deploy, or design, and
  `e2e/tests/chat/capability-suite.spec.ts` carries a hardcoded fallback of the
  production admin credentials, which should not travel in a shared archive.
  It remains in the working copy of the pack.
