# COAir — Designer Handoff

This pack runs the **entire COAir UI offline**, with realistic sample data and
**no backend required**. Everything you see is real React components you can
edit — change them and the design changes.

## Run it (2 commands)

```bash
npm install
npm run dev
```

Open **http://localhost:3000**. On the login screen, type **anything** in the
username/password fields and press Enter — in designer mode any credentials work.
You'll land in the full app with sample documents, chats, citations, SQL tables
and the document viewer all populated.

---

## The visual language: a drawing sheet

COAir is drawn in the same language as the rest of the platform — the module
portal and the Delay Analysis Toolkit: **an issued-for-construction drawing**.
Drafting paper, a faint blue-line grid, hairline rules, uppercase tracked mono
labels, tabular figures, square corners. The palette is carried over verbatim
from the toolkit so the three modules read as one document set.

There are two grounds, and they are the same drawing:

| Mode | Ground | When |
|---|---|---|
| **Drawing sheet** (light) | paper, ink lines | the primary identity |
| **Blueprint** (dark) | ink ground, white lines | its counterpart |

The mode follows the OS by default and can be flipped from the button in the top
bar. The choice is stored under the **same `platform.sheet` key the portal
uses**, so switching in one module switches the whole platform.

### The palette — nine colours

Every colour in the app resolves back to these. They live at the top of
[src/styles/globals.css](src/styles/globals.css) — change them and the whole UI
moves with them. **Do not drift from these values**; they are shared with the
toolkit.

| Token | Sheet (light) | Blueprint (dark) | Means |
|---|---|---|---|
| `--ink` | `#14324A` | `#E6EFF6` | drafting ink — body text, emphasis, fills |
| `--ink-soft` | `#5B7994` | `#8FAEC6` | annotation / secondary text |
| `--red` | `#9B3227` | `#E4796A` | revision red — a slip, an error |
| `--green` | `#3F6B4F` | `#74AE88` | gain / on-programme / live |
| `--amber` | `#B07A24` | `#D9A551` | caution / in review / correspondence |
| `--line` | `#C6D4E0` | `#2E5171` | hairline |
| `--grid` | `#EBF2F7` | `#14304A` | the blue-line grid |
| `--paper` | `#FCFCFA` | `#0C1E2E` | paper |
| `--panel` | `#F1F5F9` | `#12293C` | panel / sidebar / toolbar |

Three rules worth knowing before you change anything:

1. **Emphasis is ink, not a colour.** There is no separate UI accent hue. A
   thing becomes prominent the way it does on a drawing: the hairline thickens
   to ink, the soft annotation darkens to full ink, a fill goes ink with
   paper-coloured type (`--accent-ink`). `--accent` is therefore an alias of
   `--ink`.
2. **Red is reserved.** It means a slip or an error, nothing else. File-type
   pips deliberately avoid it — colouring every PDF red made the whole library
   read as a problem.
3. **The COAir amber is a brand mark, not a UI accent.** `--brand` carries the
   wordmark's "Air", the feather and caution states. Everything interactive is
   ink.

### Semantic tokens

Components never reference a raw hex — only these aliases, so both sheet modes
are covered by one definition:

| Token | Resolves to | Used for |
|---|---|---|
| `--bg-primary` | `--paper` | the sheet; carries the grid |
| `--bg-secondary` | `--panel` | sidebar, drawer, toolbars |
| `--bg-surface` | paper at 88% | cards drawn *on* the sheet (the grid shows faintly through) |
| `--bg-hover` / `--wash` | ink at 5% | hover, banded rows, faint fills |
| `--border` | `--line` | hairline |
| `--border-light` | `--ink-soft` | the hairline struck in |
| `--text-primary` / `-secondary` / `-muted` | ink / ink-soft / mixed | the three text weights |
| `--accent` / `--accent-hover` / `--accent-ink` | ink / ink at 82% / paper | interactive emphasis, and type on an ink fill |
| `--danger` / `--warning` / `--accent-green` | red / amber / green | status |
| `--type-pdf` / `-xls` / `-eml` | ink / green / amber | file-type pips |

---

## What you can edit

| To change… | Edit |
|---|---|
| **The palette, and therefore everything** | [src/styles/globals.css](src/styles/globals.css) §1 — the nine colours |
| Semantic tokens (what maps to what) | [src/styles/globals.css](src/styles/globals.css) §2 |
| Corner radii, globally | [src/styles/globals.css](src/styles/globals.css) §3 — the `@theme` block overrides Tailwind's radius scale, so every `rounded-*` already in the components lands on a drafting corner |
| File-type / provider colours | [src/styles/tokens.ts](src/styles/tokens.ts) |
| Any screen or component | [src/components/](src/components/), [src/layout/](src/layout/), [src/pages/](src/pages/) |
| The sample/demo content | [src/mocks/fixtures.ts](src/mocks/fixtures.ts) |
| The mock PDF page image | [src/mocks/pageImage.ts](src/mocks/pageImage.ts) |

Tailwind CSS v4 is used throughout, so utility classes work out of the box.

> **One thing to be careful of:** the reset and the focus styles in
> `globals.css` are wrapped in `@layer base` on purpose. Unlayered CSS outranks
> everything inside a cascade layer, so a bare `* { margin: 0; padding: 0 }`
> silently beats every Tailwind `p-*` and `m-*` utility in the app. If you add
> global rules, put them in `@layer base` too.

## Screens to design (all reachable offline)

1. **Login** — `/login`
2. **Welcome / mode picker** — landing after login (KPIs, mode cards)
3. **Chat answer** — open the pinned chat *“EOT entitlement — Zone 3”* (citations + related docs)
4. **SQL result** — open chat *“Q2 cost overrun by package”* (generated SQL + data table)
5. **Email trace** — open chat *“Rebar delivery correspondence”*
6. **Document viewer** — click any citation chip → right-hand viewer (PDF page / Excel table / email text)
7. **Library & Documents** — left sidebar sections
8. **Settings modal**, **Usage badge**, **sheet toggle** (top-right)

`KnowledgeModal`, `LibraryPickerModal` and `DataTablesPanel` are themed but not
currently reachable in the running pack — they are only rendered by
`LeftDrawer`, which no page mounts.

## Reference screenshots

`screenshots/` holds both grounds, five screens each. Regenerate them whenever
the design moves:

```bash
npm run screenshots
```

Run it with `npm run dev` live in another terminal; override the target with
`PACK_URL=http://localhost:5173 npm run screenshots`. The script is
[scripts/capture-sheets.mjs](scripts/capture-sheets.mjs) and talks to nothing but
the local pack.

There is also a release check — it walks every screen in both sheet modes and
fails on any console error, page error or failed request:

```bash
npm run build && npx vite preview --port 4180 &   # serve the production build
PACK_URL=http://localhost:4180 npm run smoke
```

## How the offline mode works

A small mock layer in [src/mocks/](src/mocks/) intercepts API calls and returns
the fixtures — see [src/mocks/adapter.ts](src/mocks/adapter.ts). It is **on by
default** via `VITE_MOCK=1` in [.env](.env). You normally never touch this.

To point the app at a **real backend** instead, set `VITE_MOCK=false` and
`VITE_API_URL=http://localhost:8080/api` in `.env`.

> None of the mock code affects production — it only changes where data comes
> from in this pack.
