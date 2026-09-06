# Production release preflight — Sprint 9.3

Status: local acceptance passed; production cutover is pending target details and deployment validation.

The user requested production release preparation after Sprint 9.3. Its earlier no-deployment scope does not prohibit this new request. No production service has been changed by this preflight.

## Verified

- Accepted Sprint 9.3 manifest hashes still match the worktree.
- Backend: 732 tests and 100 subtests passed, with one existing absent-fixture skip.
- Frontend: 159 tests, typecheck, lint, RTL and production build passed.
- Controlled Chromium: 145/145 cases, zero external requests.
- npm audit: zero reported advisories.
- No Sprint 9.3 migration; expected sole head is `20260904_0001_s8_2_analysis_language`.
- Changes remain uncommitted on main; the current HEAD does not identify the tested working tree.

## Concrete prerequisites

1. Identify the production host/checkout or deployment job. This workspace has no SSH host configuration or deployment workflow; the tracked GitHub workflow runs tests only.
2. Provision one server-only AUTH_BRIDGE_SECRET of at least 32 characters to both frontend and backend. Neither local environment file currently provides it. Never print it or commit it. Production configuration has not yet been inspected.
3. Commit the reviewed release candidate to give its images an accurate build SHA. Run the maintained CI gate and build both container images from that commit.
4. Validate configuration without printing expanded secrets: required credentials, explicit HTTPS origins, disabled dangerous flags, expected database target and schema head, shared durable Redis and document storage.
5. Exercise real Google login and HTTPS/cookie behavior in an isolated staging deployment of those images. The passing browser suite uses synthetic identity/service fixtures.
6. Record current image identifiers, configuration and verified backup/recovery points before production changes. No migration should be applied blindly: earlier undeployed sprints may have schema changes even though Sprint 9.3 adds none.

## Cutover and recovery

Coordinate frontend/backend replacement because the new bridge requires assertions the old frontend cannot supply. Deploy matching backend, frontend and worker images, then verify build identity, liveness/readiness, approved/admin login, authorization, stored-document reads and source queue diagnostics. Do not start source refresh or analysis simply to test a passive page.

A rollback must preserve the authentication and customer-read guards fixed in Sprint 9.3. If the previous image predates those fixes, do not reopen vulnerable routes as an automatic rollback; keep affected traffic unavailable while restoring a secured compatible build. Preserve database/Redis/document volumes; do not use Compose volume deletion.

No production command or credential mutation has been performed. Target details are the next required input.
