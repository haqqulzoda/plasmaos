# Sprint 3.2 — Session Revocation & Restore Security

## 1. Authentication Mechanisms

| Auth mechanism | Issuance point | Validation point | User state checked | `auth_version` checked | Role claims embedded | Immediately revocable | Lifetime | Risk/disposition |
|---|---|---|---|---|---|---|---|---|
| Backend access JWT | `POST /api/v1/auth/google` | `app.core.security.get_current_user` | Current DB row; disabled/rejected denied | Exact integer equality | Yes, for display/transport | Yes, on the next authorization check | 8 hours | Safe after central hardening |
| Backend refresh credential | There is no distinct refresh token; the current access JWT is presented to `POST /auth/refresh` | Same central dependency | Current DB row | Exact equality | Existing JWT contains claims | Yes | Input JWT's 8-hour lifetime | Fixed: the former stale-version rotation bypass was removed |
| `plasma_api_token` cookie | Google bridge and refresh | Central backend dependency when no Bearer token is supplied | Current DB row | Exact equality | JWT claims | Yes; cookie deletion is not required | 8 hours | Safe server-side; logout clearing is UX only |
| Auth.js JWT cookie/session | Auth.js Google callback | Every Auth.js JWT callback calls backend refresh; middleware calls backend `/users/me` | Backend evaluates current DB row | Backend exact equality | Yes | Yes, at the next callback/protected middleware evaluation | 8 hours maximum | Fixed: stale cookies fail closed and cached authority fields are cleared |
| Google OAuth identity | Google provider, then backend Google bridge | Backend bridge reloads user | Disabled/rejected denied; pending limited; approved normal | Newly issued backend JWT carries current version | Backend response contains claims | Yes, through backend credential validation | Provider-managed plus 8-hour local session | Google proves identity, never lifecycle authority |
| Document proxy | No issuance | `auth()` plus protected backend download | Backend current row | Exact equality | Not used for authorization | Yes | Request-scoped | Safe; forwards Bearer token with no-store behavior |
| Admin/operator dependencies | No issuance | `require_admin`, `require_operator`, and related dependencies rooted in `get_current_user` | Approved current DB user | Exact equality occurs first | Token/session claims are not route authority | Yes | Request-scoped | Safe |
| Celery/background jobs | No credentials issued | Authorization occurs at job-submission route | Submitter checked at submission | Exact equality at submission | No JWT/token blobs are queued | New submissions revoke immediately | Job lifetime | Already-accepted server work may continue; unrelated ingestion is not user authority |

There are no persisted refresh-token records, per-device session rows, WebSocket authentication paths, or backend session tables. Revoking all sessions therefore means advancing the user's shared database `auth_version`, causing every older stateless credential on every device and instance to fail.

## 2. Token/Session Authority

The `users` row is authoritative. JWT and Auth.js claims are transport/display snapshots only. Every backend authenticated request reloads the user by `sub`; a missing user, blocked lifecycle, invalid version state, missing version claim, malformed version claim, or mismatch fails closed. Frontend middleware independently proves that the embedded backend JWT still passes `/users/me`; it does not authorize from `session.role` or `session.is_admin` alone.

Pending users may hold a limited backend/Auth.js session for onboarding and status routes. Normal customer, Compliance, Project/Tender, vault, proposal, admin, and operator actions remain behind their existing approval/role dependencies.

## 3. `auth_version` Contract

For every request requiring current authenticated authority:

```text
credential.auth_version === current_database_user.auth_version
```

Both values must be valid non-negative integers. Missing, Boolean, string, floating-point, negative-current-state, and mismatched values are denied. The old `get_current_user_allow_stale_auth_version` dependency no longer exists. Login never resets the version; lifecycle and supported privilege changes only increment it.

## 4. Lifecycle Revocation Matrix

| Transition | Prior credentials invalidated | Fresh-auth result |
|---|---|---|
| Pending → approved | Yes | Fresh sign-in receives approved authority |
| Pending/approved → rejected | Yes | New Google/token issuance denied |
| Pending/approved/rejected → disabled | Yes | New issuance and all authorization denied |
| Disabled → prior approved | Yes again; pre-disable credentials stay invalid | Fresh sign-in allowed as approved |
| Disabled → prior pending | Yes again | Fresh sign-in remains limited/pending |
| Disabled → prior rejected | Yes again | Fresh sign-in/token issuance remains denied |
| User → admin/operator via existing bootstrap/repair path | Yes | Fresh sign-in is required before privilege appears |
| Admin/operator revoke | No runtime mutation endpoint exists | Implementation skipped; any future mutation must increment `auth_version` atomically |

## 5. Access Token Revocation

Access JWTs are stateless but centrally compared with the live user row. After a committed lifecycle or supported privilege transition increments `auth_version`, the old token is denied on ordinary protected, admin, Compliance, Project/Tender, proposal, vault, audit, and document endpoints because their dependency graph reaches the same exact validator.

## 6. Refresh Revocation

PlasmaOS has no separate refresh token. `/auth/refresh` consumes the existing backend JWT. It now uses the exact central validator, reloads the user, and refuses stale, missing-user, rejected, or disabled authority before minting anything. Possession of an old signed JWT is insufficient.

## 7. Auth.js Behavior

Every non-initial Auth.js JWT callback validates and rotates the backend credential using `cache: no-store`. Failure clears the backend access token and all cached lifecycle/role claims and marks `BackendSessionRevoked`. Next middleware also validates the backend token through `/users/me` for every protected page/API evaluation. A stale browser cookie may physically remain, but it cannot pass protected authorization.

Approval policy A is used: approval requires a fresh sign-in. A pending credential is not silently upgraded.

## 8. Google OAuth Behavior

The backend bridge queries the current user before issuing a backend JWT. Disabled and rejected users receive 403 and no cookie/token. A rejected allowlisted user remains rejected. Allowlist bootstrap for an eligible pending user increments `auth_version` in the same transaction as the privilege/lifecycle change, so prior credentials cannot acquire the new privilege.

## 9. Restore Reauthentication

Disable advances `N` to `N+1`; restore advances it to `N+2`. Neither credentials issued at `N` nor any hypothetical credential from the disabled period can match after restore. Restored-approved users must perform a fresh Google flow. Restored-pending users remain limited. Restored-rejected users remain ineligible for issuance.

## 10. Role Change Revocation

Current role grants are Google allowlist reconciliation and the allowlisted, Google-ID-verified admin repair command. Both bump `auth_version` before their single commit. The repair command refuses disabled accounts until an explicit restore. No admin/operator demotion or revoke endpoint currently exists, so Sprint 3.2 does not invent one. Future grant or revoke paths must couple the role mutation and version increment in one transaction.

## 11. Multi-Device Behavior

All devices for a user share the same database version. Tokens from phone, laptop, backend cookie, and Auth.js cookie issued at `N` all fail after the shared row advances. There is no per-device exception or process-local revocation list.

## 12. Multi-Instance Behavior

FastAPI instances query the shared database during every authentication evaluation. Auth.js/frontend instances validate against FastAPI. No in-memory user/role/approval cache participates in backend authorization. The frontend API client's short token cache may send one stale attempt, but the backend denies it and the 401 handler clears the client cache/signs out.

## 13. Transaction Boundary

Lifecycle state and `auth_version` are changed on the same ORM user inside one database transaction, with the audit event, and committed once. Company approval changes likewise bump the owning user's version before the single commit. Supported role grants do the same.

A request whose authorization check completed before the administrative commit may finish; Sprint 3.2 does not claim retroactive cancellation. Any authorization check beginning after commit observes the new row under PostgreSQL's normal READ COMMITTED request transaction behavior and denies the stale credential. A failed transaction rolls back both fields; invalid Sprint 3.1 transitions return 409 before mutation/version advancement.

## 14. Background Jobs

Authenticated job-submission routes validate current authority before accepting work. Queued Celery payloads use identifiers such as job, tender, source, or user IDs; they do not carry access/refresh JWTs or stale role claims as continuing authority. Already-authorized analysis, document processing, source refresh, or enrichment work may continue after a later disable because it is server-owned accepted work. New submissions after commit are denied. Unrelated ingestion and enrichment workers were not given artificial user auth checks.

## 15. Error Semantics

- 401: missing/invalid/expired credential, missing user, rejected/disabled authenticated account, malformed or stale `auth_version`, or invalid persisted version state.
- 403: lifecycle denial during Google/token issuance, or an authenticated current user failing an approval/role gate.
- 409: invalid lifecycle transition.

Responses do not reveal current/previous version values. The access-status response no longer exposes `auth_version`.

## 16. Database/Migration Decision

No Sprint 3.2 migration was added. The Sprint 3.1 head `20260828_0001_s3_1_admin_account_lifecycle` already provides the lifecycle provenance and existing `auth_version` mechanism needed for user-wide revocation. Adding session/refresh tables would duplicate the architecture without evidence.

## 17. Security Tests

`backend/test_s3_2_session_revocation_restore_security.py` covers exact-version parsing, version-zero legacy denial, negative state denial, disable/restore monotonicity, reject and approval policy, pending limitation, multi-device invalidation, missing-user denial, refresh/access-status bypass removal, Auth.js and middleware validation, issuance guards, atomic ordering, and aggregate-only preflight metrics. Existing Sprint 3.1, Sprint 0, Sprint 2, Sprint 1/World Bank, connector, frontend type/build/lint, fresh database, seeded database, Alembic, and read-only preflight gates are rerun as release evidence.

## 18. Deferred Sprint 3.3 Safeguards

Self-disable/reject prevention, last-admin/last-operator survival, concurrent privileged-account locking, and privileged mutation approval workflows remain deferred to Sprint 3.3. A full append-only audit redesign remains Sprint 3.4, and session-management/Admin UI redesign remains Sprint 3.5. No deployment or production access is part of Sprint 3.2.
