# Dependency exceptions

The release gate (`scripts/run_release_gate.sh config-dependencies`) prints the full
`npm audit` for the frontend as a report and blocks on `npm audit --omit=dev --audit-level=high`
**only while every exception below is unexpired**. `backend/scripts/dependency_exceptions.py check`
reads the `EXCEPTION … EXPIRES …` lines; after an expiry date the full `npm audit --audit-level=high`
blocks again until the exception is renewed here (new owner decision, new date) or the
advisory is fixed and the exception removed.

## npm-dev-braces-chain

```
EXCEPTION npm-dev-braces-chain EXPIRES 2026-11-08
```

| | |
| --- | --- |
| Advisory | GHSA-vfj7-8cjw-p6xm, high: `braces` stack-exhaustion denial of service through deeply nested patterns; every published `braces` version is listed as affected |
| Chain | `eslint-config-next` (16.3.8, devDependency) → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces` (5 high findings, one advisory) |
| Why it is accepted | Dev-only: the chain is ESLint tooling, used when linting source on developer machines and in the gate. It is not in the production dependency tree, not in the frontend image's runtime, and never processes user input. npm's only "fix" is `eslint-config-next@14.2.35`, a major downgrade that would drop the Next 16 lint rules. |
| Production result | `npm audit --omit=dev --audit-level=high` → **found 0 vulnerabilities** (2026-10-08, after `sharp` 0.35.5 and `source-map-js` 1.2.2) |
| Owner decision | 2026-10-08 (INT-5, option a) |
| Expires | **2026-11-08**: the gate fails again after this date unless renewed |
| Exit | Remove this section when a fixed `braces` (or a chain without it) is released, then re-run the gate |
