# Plasma AI frontend

Next.js 16 / React 19 application, with next-auth for sessions and next-intl for the
English, Uzbek, Russian and Arabic interface (`messages/`, `i18n/`).

For setup and the full test gate, see the repository root `README.md`.

## Commands

Run from this directory with Node 22.

```bash
npm ci
```

```bash
npm run dev
```

```bash
npm run typecheck && npm run lint
```

```bash
node --no-warnings --experimental-strip-types --test tests/*.test.mjs
```

`npm run dev` serves on http://localhost:3000 and expects the backend API (see
`BACKEND_INTERNAL_URL` and the auth variables in the root `.env`). Browser acceptance
scripts in `tests/*.py` need Playwright and a running stack. `scripts/run_release_gate.sh
browser` runs the maintained one.
