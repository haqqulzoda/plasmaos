# Sprint 3.1 — Explicit Admin Account Lifecycle and Restore Semantics

## 1. Previous Account Model

The repository already stored an explicit four-value user account state in
`users.approval_status`. There were no `is_approved` or `is_disabled` columns.
The missing contract was restore provenance and strict transition enforcement:
admin endpoints overwrote any source state, approving a disabled user acted as
an implicit restore, disable discarded the prior state, and Google allowlist
reconciliation could approve a rejected account.

| Field | Type | Previous semantics | Authorization impact | Admin impact | Overlap or ambiguity |
|---|---|---|---|---|---|
| `approval_status` | `VARCHAR(20)` | `pending`, `approved`, `rejected`, `disabled` | Primary account access state; disabled was checked first | Directly overwritten by approve/reject/disable endpoints | Canonical values existed, but transitions were not constrained |
| `platform_role` | `VARCHAR(30)` | `admin`, `operator`, `pilot_user` | Admin/operator could bypass ordinary approval checks | Not changed by lifecycle actions | Role eligibility and lifecycle eligibility were not consistently composed |
| `is_admin` | `BOOLEAN` | Legacy/compatibility administrator flag | Granted admin identity unless disabled | Read by admin guards and API payloads | Duplicates part of `platform_role`; it is not lifecycle authority |
| `auth_version` | `INTEGER` | Monotonic JWT/session version | Rejects stale signed credentials | Bumped by existing account-management mutations | Correct revocation mechanism; no second framework was needed |
| `approved_at` | timestamp | Last recorded approval time | None directly | Approval metadata | Historical evidence only, not current-state authority |
| `approved_by_user_id` | UUID FK | Last approving administrator | None directly | Approval metadata | Historical evidence only |
| `rejected_at` | timestamp | Last rejection time | None directly | Rejection metadata | Disable previously reused `rejection_reason`, blurring meaning |
| `rejection_reason` | text | Rejection/previously disable reason | Display only | Admin explanation | Sprint 3.1 stops disable from overwriting this rejection-only metadata |
| `disabled_at` | timestamp | Disable time | Supporting metadata; status remained authoritative | Set by disable | Could not identify the pre-disable state |
| allowlists | environment configuration | Bootstrap admin/operator role and approval | Could grant privileged approved access | Applied during Google authentication | Rejected users were not protected from reconciliation |
| Google identity fields | strings | Authentication identity and profile data | Used to issue current JWT | Not intended as lifecycle state | OAuth login could trigger allowlist lifecycle mutation |

`CompanyProfile.approval_status` is a separate company/pilot eligibility state.
Sprint 3.1 does not change company lifecycle or Project, World Bank, ADB, or
Compliance behavior.

## 2. Canonical Lifecycle

`User.approval_status` remains the single canonical administrative lifecycle:

- `pending`: registered but not administratively approved.
- `approved`: eligible for normal access, still subject to role, company, tier,
  ownership, and route-specific rules.
- `rejected`: explicit negative administrative approval decision; no customer
  or privileged-role authorization.
- `disabled`: explicit suspension that denies authentication before any role or
  allowlist evaluation.

No additional public lifecycle states were introduced.

## 3. State Authority

`approval_status` is canonical. `pre_disabled_approval_status` is nullable
restore provenance and is meaningful only while the canonical state is
`disabled`. `platform_role`, `is_admin`, timestamps, reasons, OAuth identity,
allowlists, and `auth_version` cannot override lifecycle state.

The database constraint permits a non-null pre-disable value only when the
current state is `disabled`, and only for `pending`, `approved`, or `rejected`.

## 4. Transition Matrix

Admin commands are strict rather than idempotent. A repeated or invalid command
returns HTTP 409 without state mutation.

| Command | Allowed source | Result |
|---|---|---|
| Approve | `pending` | `approved` |
| Approve | `rejected` | `approved` |
| Reject | `pending` | `rejected` |
| Reject | `approved` | `rejected` |
| Disable | `pending` | `disabled`, preserve `pending` |
| Disable | `approved` | `disabled`, preserve `approved` |
| Disable | `rejected` | `disabled`, preserve `rejected` |
| Restore | `disabled` with known prior state | preserved state |
| Restore | `disabled` with unknown prior state | `pending` |

Approve, reject, or disable from their already-resulting state is invalid.
Approve/reject/disable from `disabled` is invalid; restore must be used.
Restore from any non-disabled state is invalid.

## 5. Disable vs Reject

Disable suspends access without changing the prior approval decision. It writes
`pre_disabled_approval_status` and `disabled_at`, leaves rejection metadata
intact, and does not set `rejection_reason`. Reject records a negative approval
decision in `rejected_at` and `rejection_reason`; it does not set disable
metadata. The states are never aliases.

## 6. Restore Semantics

Restore reads the explicit pre-disable value, writes it back to
`approval_status`, clears `disabled_at`, and clears the consumed provenance.
Known sequences therefore round-trip exactly:

- `approved -> disabled -> approved`
- `pending -> disabled -> pending`
- `rejected -> disabled -> rejected`

Restore never changes roles or resurrects credentials.

## 7. Unknown Prior-State Policy

Existing disabled rows have no trustworthy pre-disable field. The migration
leaves their provenance null; it does not infer approval from timestamps,
roles, allowlists, `is_admin`, or activity text. Restore of such a row returns
it to `pending`, which cannot elevate access. An administrator may then make a
separate, explicit approve or reject decision.

## 8. Google Auth

Google authentication is not a lifecycle command. Pending users remain
pending, rejected users remain rejected, and disabled users are rejected before
profile reconciliation or token issuance. A rejected allowlisted email is not
approved or assigned a privileged role by login.

## 9. Allowlist

The existing initial bootstrap rule remains for eligible pending/new users.
Allowlist membership cannot override rejected or disabled state. Privileged
role helpers now require canonical `approved` state, so pending, rejected, and
disabled role/flag/allowlist combinations are denied.

## 10. Session and Auth-Version Effects

The existing `auth_version` remains the only revocation mechanism. Every
successful admin lifecycle command increments it monotonically. This preserves
the existing refresh architecture and means:

- disable and reject immediately invalidate existing credentials;
- approve cannot revive credentials from before a rejection;
- restore never decrements or reuses the pre-disable version;
- credentials issued before disable remain invalid after restore.

No session inventory, forced-logout UI, or second revocation framework was
added; those remain Sprint 3.2 scope.

## 11. Admin API

The existing admin-only action endpoints are retained and normalized:

- `POST /admin/users/{user_id}/approve`
- `POST /admin/users/{user_id}/reject`
- `POST /admin/users/{user_id}/disable`
- `POST /admin/users/{user_id}/restore`

All use the existing `require_admin` dependency, return a safe admin user
projection, and never expose `auth_version`, OAuth internals, tokens, or
secrets. The response may include `pre_disabled_approval_status` so the admin
UI can label restore behavior. Operators retain read-only queue access.

The lifecycle service returns actor, target, action, previous state, new state,
and timestamp context. The existing minimal admin activity recorder receives
that context; no Sprint 3.4 append-only audit redesign was added.

## 12. Invalid Transitions

Invalid source/action pairs return HTTP 409 with a deterministic message such
as `Cannot approve account from 'disabled' state`. Validation happens before
mutation, audit recording, commit, or version increment. Actions are strict,
not idempotent, because a repeated security-sensitive command usually signals
stale administrative state.

## 13. Data Migration

Revision `20260828_0001_s3_1_admin_account_lifecycle` is the single additive
child of the Sprint 2 head. It adds one nullable `VARCHAR(20)` column and one
check constraint. It performs no UPDATE, INSERT, DELETE, status inference,
approval, rejection, disable, restore, or unrelated business-data mutation.

Fresh local PostgreSQL 16.12 validation reached the new head from the immutable
Sprint 0.4c baseline with zero fabricated users. A separately seeded Sprint 2
database preserved counts and ID fingerprints for 8 users, 8 CompanyProfiles,
1 Project, 1 Tender, 1 TenderAnalysis, 1 AnalysisVersion, and 1 Proposal.
Both seeded disabled rows remained disabled with unknown provenance.

## 14. Security Regression

Validation performed on 2026-08-28:

- Sprint 0/P0 security: 116 passed, 17 subtests passed.
- Sprint 3.1 lifecycle: 12 passed, 31 matrix subtests passed.
- Sprint 2 ownership/version/concurrency/version-aware reads: 29 passed.
- Sprint 1 Project/World Bank/Project Context/access: 64 passed.
- Connector regression gate: 195 passed, 1 approved fixture skip, 4 subtests.
- Frontend TypeScript: passed with zero errors.
- Frontend production build: passed.
- Frontend lint: zero errors; 15 pre-existing unrelated warnings.
- Fresh and seeded-existing database `alembic check`: no new upgrade operations.
- Read-only preflight: zero invalid lifecycle combinations on both databases.

An unfiltered recursive `pytest` invocation remains unsuitable as a release
gate because the repository already contains duplicate root/`scripts/` test
module names, a stale `MODEL_NAME` import in `scripts/test_extraction.py`, and a
Windows-only working-directory change in `test_ai.py`. The documented focused
security, sprint, and connector gates above collect and pass cleanly.

## 15. Self and Last-Admin Risks Deferred

Current APIs do not prohibit an administrator from targeting themselves.
Because commands are strict, an approved admin cannot approve or restore
themselves, but can reject or disable themselves. A disabled admin cannot use
restore because disabled-first authentication blocks the request; another
approved admin is required. The API also does not prevent disabling/rejecting
the last administrator or concurrent admin mutations. These known risks remain
explicitly deferred to Sprint 3.3, as required.

## 16. Audit Hook for Sprint 3.4

`AccountLifecycleTransition` exposes actor user ID, target user ID, action,
previous state, new state, and occurrence time. Admin endpoints pass this into
the existing `AdminActivityEvent` metadata. This is a reusable hook for Sprint
3.4; it is not represented as the future append-only audit guarantee.

## 17. Test Results

The restore matrix covers all three known states, unknown legacy restore,
strict invalid transitions, auth-version monotonicity, direct approve-disabled
conflict, rejected Google login, allowlist resistance, and role/flag override
denial. Fresh and existing database checks used isolated loopback databases and
did not alter the configured project database.

## 18. Production Considerations

No deployment or production access occurred. Before a future authorized
release, run the read-only preflight against the intended target, review counts
of disabled accounts with unknown provenance, take the normal backup, apply the
single additive migration, and communicate that first restore of an unknown
legacy disabled account yields pending rather than approved. Sprint 3.2 should
next address session visibility and forced reauthentication without changing
this lifecycle contract.
