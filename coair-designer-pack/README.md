# COAir — designer pack

The full COAir UI, running offline with realistic sample data and **no backend
required**. Every screen is the real React component, so editing it changes the
design.

```bash
npm install
npm run dev          # → http://localhost:3000
```

Sign in with **any** username and password.

## Where to go next

| | |
|---|---|
| **[DESIGNER.md](DESIGNER.md)** | The visual language, the palette, which token controls what, and which screens to look at. Start here if you are changing the design. |
| **[DEPLOY.md](DEPLOY.md)** | Building and hosting it, host configuration, CSP, and how to verify a build before shipping. Start here if you are deploying it. |
| `screenshots/` | Reference images of every screen, in both the drawing sheet (light) and blueprint (dark) grounds. |

## Commands

| Command | Does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check and build to `dist/` |
| `npm run serve:dist` | Serve `dist/` with the real production headers |
| `npm run smoke` | Drive a browser through every screen in both grounds; fails on any error |
| `npm run screenshots` | Refresh `screenshots/` |
| `npm run lint` / `npm run format` | ESLint / Prettier |

Built with React 19, Vite 7 and Tailwind CSS v4.

> Ships in designer mode (`VITE_MOCK=1`): all data comes from `src/mocks/`, and
> any credentials are accepted. See [DEPLOY.md](DEPLOY.md) before putting a
> build anywhere client-facing.
