# Sprint 3.5 — Admin Operational UX & API Hardening

Status: complete locally. No deployment or production access was performed.

## 1. Previous Admin UX

The pre-Sprint 3.5 surface audit was completed before implementation.

| Surface | Current purpose | Data source | Lifecycle display | Available actions | Security problem | UX problem | Decision |
|---|---|---|---|---|---|---|---|
| `/admin` overview | Operational and corpus counts | `GET /admin/activity`, `GET /admin/corpus-health` | Pending/approved counts only | None | Legacy recent-event data was coupled to an operator-readable overview | No path to canonical audit history | Modify: preserve counts, withhold recent security events from operators, link to Accounts |
| `/admin/approvals` | User and company review | Legacy `GET /admin/approval-queue` | Raw stored strings | User/company approve, reject, disable; restore for users | Unbounded list; self inferred by email; UI invented action availability; prompts accepted free-form input | Approved accounts were usually absent; browser prompts had weak consequence/focus handling | Replace account read with bounded `GET /admin/accounts`; preserve canonical action endpoints and company controls |
| `/admin/companies/[id]` | Existing company detail/review | Existing company read and lifecycle endpoints | Company approval state | Existing approve/reject/disable | No Sprint 3.5 account authority issue | Separate detail navigation remains useful | Keep |
| Admin layout/navigation | Separate platform administration shell | Auth.js session claims plus backend API failures | Access gate only | Navigation/logout | A stale privileged shell could remain until the next API call | Accounts and audit history were not distinct | Modify: Accounts plus effective-admin-only Audit activity navigation |
| Dashboard Admin link/redirect | Entry and compatibility redirect | Auth.js session | Access gate only | Navigate | No lifecycle write | Existing compatibility route needed preservation | Keep |
| Recent activity data | Small legacy overview feed | `GET /admin/activity` | Not a complete lifecycle record | None | Not the canonical Sprint 3.4 audit contract | Missing outcomes, filters, pagination, legacy handling | Preserve route compatibility; use `/admin/audit-events` for the new audit UI |

No general user table, role-management endpoint, deletion endpoint, impersonation control, or device/session inventory existed. None was invented.

## 2. Information Architecture

The Admin shell remains narrow:

1. Overview — existing operational/corpus counts.
2. Accounts — canonical account status, safe role display, company context, filters, bounded pages, and explicit lifecycle actions.
3. Audit activity — immutable administrative security history for effective admins.

Existing company detail and customer-dashboard separation are preserved. `/admin/approvals` remains the compatible route for the Accounts surface.

## 3. Lifecycle Status Display

The Accounts surface renders `approval_status` directly as Pending, Approved, Rejected, or Disabled. Role, `is_admin`, identity provider data, allowlists, and timestamps do not derive or override lifecycle status. A disabled administrator is visibly `Role: Admin` and `Status: Disabled`.

## 4. Action Matrix

`GET /api/v1/admin/accounts` derives `allowed_actions` on the backend from the locked lifecycle service:

| Current state | Actions |
|---|---|
| Pending | Approve, Reject, Disable |
| Approved | Reject, Disable |
| Rejected | Approve, Disable |
| Disabled | Restore |

Operators receive an empty capability list. Stable user ID removes self-reject and self-disable. Last-admin truth is intentionally not computed in the browser. Every mutation still calls the existing canonical command endpoint, which revalidates the transition and survivability under lock.

## 5. Confirmation Semantics

All account transitions use a labeled modal with the target email, explicit action, and consequence. Approve says the account becomes Approved and requires fresh sign-in. Reject distinguishes rejection from disable, invalidates credentials, and notes later explicit approval. Disable states immediate access loss, credential/session invalidation, and fresh authentication after restore. Restore states the backend-computed result and that old sessions remain invalid. Reject and disable accept an optional bounded reason.

The UI waits for the backend response, disables duplicate submits, and never performs an optimistic lifecycle update.

## 6. Restore UX

The action is always named Restore. The API exposes `restore_target_status`, not `pre_disabled_approval_status`. Confirmations truthfully show Restore to Approved, Pending, or Rejected. A successful response uses the backend-returned state and then refetches the page.

Unknown/legacy provenance is conservatively previewed as Pending, matching the locked backend behavior.

## 7. Self-Action UX

The backend marks `is_current_actor` using UUID equality and removes Reject and Disable from that row's `allowed_actions`. The row explains that administrators cannot reject or disable themselves. No email comparison is used. Direct endpoint invocation remains authoritatively denied with HTTP 409 by Sprint 3.3.

## 8. Last-Admin UX

The browser does not calculate effective-admin counts. If the backend returns the last-admin 409, the UI shows: “This action would remove the last active administrator. No account state changed.” It refetches authoritative state and does not show success.

## 9. Concurrency / Stale-State UX

Security-state mutations are backend-confirmed. HTTP 409 is classified as a stale/invalid transition unless it safely matches self-action or last-admin denial. The account list is refetched before the safe explanation is displayed, so the message remains visible and the row shows the actual current state. Browser acceptance proved a second, stale browser changing from Approved to the backend's Disabled state with Restore as the only next action.

## 10. Audit Activity Surface

`/admin/audit` consumes `GET /api/v1/admin/audit-events`. Its bounded table shows Time, Actor, Action, Target, Outcome, and Reason/detail. Server repair actors are rendered as Server command; non-user reconciliation actors are rendered as System. Links from account rows prefill the target-user filter.

The overview `/admin/activity` route is retained. Operators can still obtain its operational counts, but `recent_events` is empty unless the caller is an effective admin. The canonical audit surface does not consume the legacy feed.

## 11. Audit Filters

The UI exposes the existing actor UUID, target UUID, controlled action, and SUCCESS/DENIED/FAILED outcome filters. Filters reset to the first page. The server validates UUIDs/outcomes, caps `limit` at 100, applies offset semantics, and orders by `created_at DESC, id DESC`. The UI uses 25 rows per page.

## 12. Legacy Events

Rows with null canonical fields render `Legacy event`, `Unavailable`, or `Legacy resource`. Missing actor, outcome, source, and state are never fabricated. Legacy free-form metadata is not returned by the canonical payload mapper and is not read by the UI.

## 13. Error Handling

The account action classifier maps:

- 401 to invalid authentication and the existing sign-out/login flow.
- 403 to lost current administrator authority and dashboard redirection.
- 404 to a missing target plus account refetch.
- 409 to safe self-action, last-admin, or stale-state language plus refetch.
- Other failures to a restrained no-success/no-state-change message.

Account and audit reads have loading, empty, unavailable, manual refresh, and authorization-loss states. Raw backend exception details and JSON are not displayed.

## 14. Authorization

Audit history remains effective-admin-only through `require_admin`. Operators, ordinary approved users, and pending/rejected/disabled admin-role rows are denied. Stale credentials remain denied by the Sprint 3.2 `auth_version` checks and Auth.js backend revalidation.

The account list remains readable by approved operators/admins for the existing operational workflow. Only effective admins receive non-empty account action capabilities, and all writes use the canonical admin lifecycle endpoints.

## 15. Sensitive Data

The new account response contains only ID, name, email, canonical status, display role, stable self marker, safe restore target, backend-derived actions, existing safe company summary, and creation time. It omits `auth_version`, Google/OAuth IDs, token state, authorization headers, allowlist configuration, and raw restore provenance.

Audit detail uses an allowlist of semantic state fields: account/company status and `credentials_invalidated`. It never renders raw state JSON or metadata. Automated payload/UI scans covered `auth_version`, access/refresh/Auth.js/OAuth tokens, Google ID, and secret metadata.

## 16. Accessibility

Actions are native keyboard-reachable buttons. The confirmation uses `role="dialog"`, `aria-modal`, a labeled heading, explicit Cancel and Confirm controls, initial confirmation focus, Escape handling, and disabled controls while in flight. Status/outcome text and icons supplement color. Tables use headers and horizontal overflow at narrower laptop/tablet widths.

## 17. API Compatibility

Existing lifecycle action endpoints, company endpoints, `/admin/activity`, `/admin/corpus-health`, `/admin/approval-queue`, `/admin/companies/{id}`, and `/admin/approvals` remain. The current Admin UI migrates account reads from the unbounded approval queue to additive `GET /admin/accounts`; the legacy queue is retained for compatibility. Audit UI uses the existing Sprint 3.4 canonical `/admin/audit-events` endpoint. No route was removed.

## 18. Test Results

- Sprint 3.5 backend contract tests: 8 passed.
- Sprint 3.5 frontend focused tests: 5 passed.
- Real Chromium Admin acceptance: 12/12 passed.
- Sprint 3.5 disposable PostgreSQL: fresh and representative-existing scenarios passed; 106 audit rows returned as stable pages of 100 and 6 with no duplicate/missing IDs; unrelated business fixtures unchanged; Alembic check clean.
- Sprint 3.1–3.5 focused unittest group: 49 passed.
- Sprint 2 plus Sprint 1/WB focused pytest group: 59 passed.
- Sprint 3.3 survivability and Sprint 3.4 audit database proofs: passed.
- Sprint 2 ownership/version/concurrency/version-aware read database proofs: passed.
- Sprint 1 Project/WB enrichment/auto-drain database proofs: passed.
- Connector gate: 195 passed, 1 approved skip, 4 subtests passed.
- TypeScript: passed. Production build: passed. ESLint: zero errors; 15 pre-existing unrelated warnings remain.
- Current migration head: `20260828_0002_s3_4_admin_audit_hardening`; no Sprint 3.5 migration; `alembic check` clean on disposable fresh and existing databases.

## 19. Deferred Features

General role management, user deletion, impersonation, per-device/session management, complex RBAC, admin analytics, cursor pagination, organization-management expansion, and Sprint 4 remain deferred. No direct generic user status PATCH was added.

## 20. Release Considerations

This is an additive API/UI release with no schema migration. Before release, use the normal non-production deployment pipeline, preserve the backend-before/frontend compatibility window, and rerun the same gates in the release environment. No production database or deployment was accessed in this sprint. The existing Next.js middleware deprecation warning and unrelated lint warnings are non-blocking follow-up maintenance, not Sprint 3.5 security-state defects.
