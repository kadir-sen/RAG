# ARIA — Landing Page (v2)

A single-file, dependency-free landing page for **ARIA**, an AI-powered enterprise intelligence platform. Animation-heavy build with a dark Apple-inspired aesthetic, custom cursor, scroll progress, sticky scrollytelling, magnetic CTA, and an interactive product mockup.

> This is **Aria_v2** — the snapshot version. Everything is inlined into `index.html`: HTML markup, CSS (custom properties, conic gradients, `@property`, animations), and vanilla JavaScript (IntersectionObserver-driven reveals, particle canvas, custom cursor, scroll-driven scaling).

---

## File contents

| File | Purpose |
|---|---|
| `index.html` | The entire landing page — markup + styles + scripts. |
| `package.json` | Optional npm scripts to run a local static server or deploy. |
| `vercel.json` | One-click Vercel deployment config. |
| `netlify.toml` | One-click Netlify deployment config. |
| `.gitignore` | Standard ignore list for Node + editor artefacts. |
| `README.md` | This file. |

The page is **fully self-contained**. The only external resource it loads is **Google Fonts** (Inter + JetBrains Mono) via CDN. To run fully offline, see [Self-hosting fonts](#self-hosting-fonts).

---

## Clone and run

### 1. Get the code

If you received the **zip**:
```bash
unzip aria-v2-export.zip -d aria-landing
cd aria-landing
```

If it's in a **Git repo**:
```bash
git clone <your-repo-url> aria-landing
cd aria-landing
```

If it's a **plain folder**, just `cd` into it.

That's it — no `npm install` is needed. The page has zero JavaScript dependencies.

---

### 2. Run it — OFFLINE (no network, no server)

The simplest way:

- **macOS / Windows / Linux**: double-click `index.html` and it opens in your default browser.
- Or from the command line:
  ```bash
  # macOS
  open index.html
  # Windows
  start index.html
  # Linux
  xdg-open index.html
  ```

The page renders entirely from local files. Note: the only thing that *does* hit the network is the Google Fonts stylesheet (Inter + JetBrains Mono). Without internet you'll see system-font fallbacks but everything still works. To make it **truly 100% offline** (no font CDN), follow [Self-hosting fonts](#self-hosting-fonts) below.

A few scroll-driven animations behave better when served over HTTP rather than `file://`. If anything looks off, run a local server (next section).

---

### 3. Run it — ONLINE (local web server, recommended for development)

Requires **Node.js 16 or newer** (download from <https://nodejs.org>).

From inside the folder:

```bash
# Start a local server on http://localhost:3000
npm run dev

# Or alternative server on http://localhost:8080 (no caching, useful while editing)
npm start
```

Then open <http://localhost:3000> in your browser. Live changes? Just refresh.

`npm run dev` uses `npx -y serve`, and `npm start` uses `npx -y http-server`. Both fetch the server tool on demand — there's no `npm install` step.

If you don't have Node, any static server works:

```bash
python3 -m http.server 8000          # Python 3
php -S localhost:8000                # PHP 7+
caddy file-server --listen :8000     # Caddy
ruby -run -e httpd . -p 8000         # Ruby
```

---

### 4. Run it — ONLINE (publish to the internet)

The folder is a static site. Pick any host:

#### Vercel (one command)
```bash
npm run deploy:vercel
```
or push to GitHub and import at <https://vercel.com/new>. The included `vercel.json` configures clean URLs + security headers.

#### Netlify (one command)
```bash
npm run deploy:netlify
```
or drag-and-drop the folder onto <https://app.netlify.com/drop>. The included `netlify.toml` sets the publish directory and headers.

#### GitHub Pages
1. Create a new repo, commit and push this folder.
2. Repo → **Settings → Pages → Source**: *Deploy from a branch* → `main` / `(root)`.
3. Wait ~30 seconds. Your site is live at `https://<user>.github.io/<repo>/`.

#### Cloudflare Pages
1. Push to GitHub.
2. <https://dash.cloudflare.com> → **Pages → Connect to Git** → pick the repo.
3. Build command: *(leave blank)*. Output directory: `.` (or root). Deploy.

#### S3 + CloudFront
1. `aws s3 sync . s3://your-bucket --acl public-read --exclude "node_modules/*" --exclude ".git/*"`
2. Set **Index document** to `index.html` in the bucket's *Static website hosting* settings.
3. Front it with CloudFront for HTTPS + CDN.

#### Any FTP / SFTP host
Upload the folder. That's the entire deployment.

---

## Browser support

- **Chrome / Edge / Safari / Firefox** — current and previous major versions.
- Uses modern CSS: `@property`, `color-mix()`, `backdrop-filter`, conic gradients, `clip-path`. These have ~95%+ global support; for older browsers you'd want a static fallback for animated borders.
- The custom cursor disables itself below 980px wide (touch devices).
- Honours `prefers-reduced-motion: reduce` — all animations and transitions collapse to ~instant for users who request reduced motion.

---

## Customising

### Brand & copy
Search `index.html` for:
- `ARIA` — brand name
- `<h1 class="hero-h1">` — hero headline
- `Hello! I have access` — chat demo content
- `<section class="problem">`, `<section class="features">`, etc. — section copy

### Colour palette
All colours are CSS variables in `:root`. The relevant block is near the top of the `<style>` tag:

```css
--blue:  #4f8ef7;
--purp:  #8b5cf6;
--cyan:  #06b6d4;
--pink:  #ec4899;
--green: #4ade80;
--grad:  linear-gradient(135deg, #4f8ef7 0%, #8b5cf6 50%, #ec4899 100%);
```

Change those and the entire site re-themes — gradients, accents, glows, conic borders, and stat numbers all derive from them.

### Replace the chat demo content
The mock conversation lives inside `<div class="chat-zone">`. Each `.msg` is one bubble; toggle `right` for the user side. Update `bubble` markup and the citation `file-tag`.

### Use-case answers
The `ucData` object in the `<script>` block (search for `const ucData =`) holds the five demo Q&A pairs. Replace strings and they appear on the page when the user clicks each role.

---

## Self-hosting fonts

If you need to ship fully offline, replace this block in `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

with locally-served `@font-face` declarations. Tools like [google-webfonts-helper](https://gwfh.mranftl.com/fonts) bundle the font files plus a CSS snippet you can drop in. Put the woff2 files under `./fonts/` and you have a 100%-offline site.

---

## How it's built (so you can extend it)

- **No build step.** No bundler, no preprocessor, no framework.
- **CSS animations** drive most motion (orbs, marquee, conic-gradient borders via `@property --angle`, ribbon drift).
- **JavaScript handles**:
  - Custom cursor with `requestAnimationFrame` lerp interpolation
  - Scroll-progress bar and parallax/scaling on hero & showcase
  - `IntersectionObserver` for one-shot reveal animations
  - A canvas particle network in the hero
  - Magnetic-button transform tracking
  - Card spotlight + 3D tilt
  - Counter ramp-up on stats
  - Text scramble for the big-Q headline
  - Typewriter loop on the device input placeholder
  - Use-case panel swap with content re-render
- **Reveal pattern**: add `.fm-fade-up` / `.fm-scale` / `.fm-slide-l` / `.fm-slide-r` to any element; it animates in when scrolled into view.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Fonts look wrong / system | No internet, blocked CDN | [Self-host the fonts](#self-hosting-fonts). |
| Custom cursor missing | You're on a touchscreen / under 980px | Expected — disabled by design. |
| Conic gradient border static | Old browser (no `@property` support) | Upgrade to a current Chromium / Safari / Firefox. |
| `npm run dev` not found | Wrong directory | `cd` into the folder containing `package.json` first. |
| Port already in use | Something else is on 3000/8080 | Edit `package.json` scripts and pick a different `-l` / `-p` value. |

---

## Licence

Source code: UNLICENSED (private).
Fonts: Inter (OFL), JetBrains Mono (OFL).
The ARIA brand and copy are placeholders — replace before going to production.
