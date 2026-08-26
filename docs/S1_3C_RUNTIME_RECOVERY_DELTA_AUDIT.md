# Sprint 1.3C — Runtime Recovery Delta Audit

## 1. Sprint 1.3B Delta Inventory

### Base and Git evidence

There is no Git commit immediately before Sprint 1.3B. `HEAD` is
`ec55da62dcb0c113020d9c86244844b55ed9208c`, from before the uncommitted Sprint
1.1–1.3 work. Consequently, a repository-wide comparison to `HEAD` is not a
Sprint 1.3B diff: it combines earlier Sprint 1 work, generated tracked bytecode,
and the recovery changes, while omitting all untracked files.

The requested commands were still recorded. At audit time, `git diff --stat`
reported 29 tracked paths, 521 insertions, and 227 deletions. `git diff
--name-status` reported tracked modifications in pre-existing Sprint work,
generated `__pycache__` files, the three auth-support paths, the Tender Details
page, and three security tests updated by this audit. Those outputs cannot be
used as the S1.3B release boundary. No timestamp inference was used.

The defensible base is therefore the logical post-S1.3/pre-S1.3B workspace,
established from Git content, the S1.1–S1.3 specifications and documents,
semantic diffs, and actual import/call dependencies. Against that logical base,
the S1.3B name-status inventory is:

```text
A  backend/scripts/enqueue_world_bank_project_enrichment.py
A  backend/test_s1_3b_project_context_runtime_recovery.py
M  backend/app/services/project_enrichment.py                 (fairness hunk)
M  frontend/types/project.ts
M  frontend/app/dashboard/tenders/[tenderId]/page.tsx
M  frontend/tests/project-context.test.mjs
A  frontend/auth.ts
M  frontend/app/api/auth/[...nextauth]/route.ts
M  frontend/lib/documentProxy.ts
A  docs/S1_3B_PROJECT_CONTEXT_RUNTIME_RECOVERY.md
```

This is ten audited files: the nine paths reported by S1.3B plus the required
fairness change in `project_enrichment.py` made during the recovery follow-up.
An exact logical line-stat cannot be truthfully reconstructed because the
pre-S1.3B versions of several uncommitted files were never recorded in Git.

| Path | Classification | Semantic reason |
|---|---|---|
| `backend/scripts/enqueue_world_bank_project_enrichment.py` | REQUIRED FOR PROJECT RUNTIME RECOVERY | Adds the missing bounded operator reconciliation entry point. |
| `backend/test_s1_3b_project_context_runtime_recovery.py` | REQUIRED ONLY FOR TEST / ACCEPTANCE | Proves migration reuse, command safety, API state separation, and fairness. |
| `backend/app/services/project_enrichment.py` fairness hunk | REQUIRED FOR PROJECT RUNTIME RECOVERY | Prioritizes untouched/stale rows before known source failures so failures cannot starve the backlog. |
| `frontend/types/project.ts` | REQUIRED FOR PROJECT RUNTIME RECOVERY | Separates no-project, authorization, endpoint failure, and authoritative source-unavailable states. |
| `frontend/app/dashboard/tenders/[tenderId]/page.tsx` | REQUIRED FOR PROJECT RUNTIME RECOVERY | Loads Project Context independently and preserves Tender Details on Project API failure. |
| `frontend/tests/project-context.test.mjs` | REQUIRED ONLY FOR TEST / ACCEPTANCE | Locks the corrected HTTP and user-message semantics. |
| `frontend/auth.ts` | REQUIRED FOR PROJECT RUNTIME RECOVERY RELEASE BUILD | Moves unchanged Auth.js configuration to a legal non-route module for Next.js 16. |
| `frontend/app/api/auth/[...nextauth]/route.ts` | REQUIRED FOR PROJECT RUNTIME RECOVERY RELEASE BUILD | Leaves only supported App Router handler exports. |
| `frontend/lib/documentProxy.ts` | REQUIRED FOR THE AUTH MODULE MOVE | Updates one import; the proxy security contract is unchanged. |
| `docs/S1_3B_PROJECT_CONTEXT_RUNTIME_RECOVERY.md` | REQUIRED DOCUMENTATION | Records recovery evidence, limitations, and operational behavior. |

No audited S1.3B path is unrelated pre-existing work or unnecessary. Other
dirty workspace paths belong to the uncommitted Sprint 1.1–1.3 base and must
not be mislabeled as S1.3B.

## 2. Auth.ts Decision

**Decision: include as an independently justified production-build dependency.**

`frontend/auth.ts` is the former route-module Auth.js configuration moved
without callback or policy changes. A normalized semantic comparison against
the configuration previously in the route has only a trailing blank-line
difference. The sole meaningful source change is exporting the existing
`handlers` and `auth` bindings from a normal module.

- Behavior changed: module ownership/export location only.
- Reason during recovery: the current Next.js 16 production build rejects an
  App Router route that exports the non-route `auth` symbol.
- Production requirement: yes, for a valid production build.
- Local-browser-only requirement: no.
- Authentication/authorization semantics: unchanged.
- Auth.js fail-closed behavior: unchanged; configuration errors do not produce
  an access token or bypass backend authorization.
- Access-token propagation: unchanged; the same session callback writes the
  same backend token.
- Disabled-account enforcement: unchanged and remains authoritative in the
  backend dependencies and refresh endpoint.
- Could runtime recovery work without it: development/API recovery could, but
  the Sprint 1 release build could not. It is therefore required for release,
  not for the Project domain model itself.

Actual call sites are the NextAuth route (`handlers`) and the document proxy
(`auth`). There is no bare Auth.js object truthiness authorization gate.

## 3. NextAuth Route Decision

**Decision: include as the second half of the production-required module
split.**

The route now contains only:

```ts
import { handlers } from '@/auth';

export const { GET, POST } = handlers;
```

It is an import/export movement, not an authentication behavior change. Google
provider settings, backend bridge handling, refresh behavior, JWT/session
callbacks, fail-closed errors, token propagation, and disabled-account policy
remain in `frontend/auth.ts` unchanged. It is neither formatting-only nor test
support: it is necessary for Next.js route-module validity in production.

## 4. DocumentProxy Decision

**Decision: include only because it is a dependency of the retained auth
module move.**

The exact delta is one import:

```text
- import { auth } from "@/app/api/auth/[...nextauth]/route";
+ import { auth } from "@/auth";
```

Project Context has no dependency on document download behavior. The release
requires this change only because the route no longer exports `auth`.

Security behavior is unchanged:

- `await auth()` must yield a string `accessToken`; otherwise the proxy returns
  401.
- The destination remains the fixed configured backend base plus
  `/tenders/documents/{id}/download`; callers cannot select a scheme or host.
- Only the backend destination receives the bearer token.
- No request URL is accepted, no `new URL` or redirect destination is built,
  and no SSRF-like host expansion was added.
- Tokens are not logged, echoed, or included in error responses.
- Both route call sites pass only the document path parameter.

## 5. Required Project Recovery Delta

The minimum dependency-complete S1.3B delta is exactly the ten paths in section
1. The Project-specific behavior consists of the operator command, its recovery
tests, the queue fairness ordering, failure classification/types, the isolated
Tender Details request/render path, the frontend tests, and the S1.3B document.
The auth trio is retained as a separately justified release-build dependency.

The following are explicitly not S1.3B delta:

- foundational Sprint 1.1–1.3 schema, API, worker, component, and migration
  files already present in the logical base;
- tracked/untracked bytecode and frontend build output;
- local database contents, containers, images, browser harnesses, or temporary
  files;
- unrelated later-Sprint files already present in the dirty workspace.

## 6. Operator Command Review

`enqueue_world_bank_project_enrichment.py` passes the operator-safety audit:

- dry-run is the default and explicitly rolls back the claim transaction;
- apply requires `--apply` plus the exact phrase
  `ENQUEUE_WORLD_BANK_PROJECT_ENRICHMENT`;
- `--limit` is validated from 1 through the service maximum of 50;
- the existing service selects only linked canonical `world_bank` Projects;
- eligibility and active-work exclusion reuse the S1.2 seven-day freshness and
  30-minute lease contracts;
- `FOR UPDATE SKIP LOCKED` prevents concurrent claim duplication;
- dispatch reuses the existing S1.2 Celery task and contains no HTTP client or
  duplicate enrichment implementation;
- output is aggregate JSON and contains no credentials;
- dispatch failures are recorded explicitly.

Reruns are safe and lease-aware, but “idempotent” must be interpreted
precisely: successful fresh and actively leased Projects are not duplicated;
terminal failed/source-unavailable/partial rows are intentionally eligible for
a later retry. An operator should not blindly rerun failed batches without
reviewing failure classes.

S1.3C itself ran no reconciliation command and dispatched zero Projects. The
specification's 3 successful / 1 partial / 412 pending figures were already
stale when this audit began: a prior S1.3B continuation, prompted by the report
that most tenders still showed “being prepared,” had already attempted all 416
local Projects. The recorded local terminal distribution is 369 successful, 2
partial, and 45 failed with empty authoritative responses. This audit did not
alter that state and production must not use those counts.

## 7. Security Results

The relevant authentication and authorization matrix passed: **64 tests plus
10 subtests**.

Coverage includes unauthenticated and malformed-token denial, valid ordinary,
admin, and operator access, disabled ordinary/admin/operator denial, disabled
allowlisted-user denial, stale `auth_version` denial, refresh restrictions,
protected Project/Tender route dependencies, fail-closed token checks, and the
absence of a bare Auth.js object truthiness gate.

The document-proxy security contract is covered by updated static release tests
and semantic diff review: unauthenticated requests require a token and return
401; the destination host remains fixed; arbitrary URLs are not accepted; the
authorization header is forwarded only to the configured backend; and no token
logging or response leakage exists.

Only test expectations were updated for the auth configuration's new module
location. No production auth or document-proxy behavior was changed in S1.3C.

## 8. Excluded Changes

No path from the ten-file logical S1.3B inventory is excluded. Excluded from an
S1.3B-specific commit are all other dirty workspace paths, including generated
`__pycache__` files and changes belonging to Sprint 1.1–1.3 or unrelated later
work. They must be committed/reviewed under their own provenance rather than
silently absorbed into S1.3B.

The three test files changed by this audit are an S1.3C verification delta, not
retroactively labeled S1.3B:

- `backend/test_p0_2a_release_admin_repair.py`
- `backend/test_p0_3a_onboarding_access.py`
- `backend/test_s0_2_disabled_authorization.py`

## 9. Enrichment Rollout Runbook

1. After deployment and migration verification, calculate the production
   eligible population from production state. Do not assume 412 or any local
   count.
2. Run the command without `--apply` using a small limit such as 5 and verify
   `mode=dry_run`, the bounded `eligible_in_batch`, and
   `database_mutated=false`.
3. Dispatch a first batch of 5 with the explicit confirmation phrase.
4. Verify aggregate `claimed`, `enqueued`, and `dispatch_failed` counts, then
   monitor Project `enrichment_status`, `enrichment_failure_class`, last-attempt
   time, queue depth, worker errors/retries, World Bank 429/5xx responses, and
   identity-mismatch events.
5. Validate a sample through the authenticated Project API and Tender Details
   UI. Confirm identity, truthful freshness, official metadata/provenance, and
   conservative role labels.
6. Continue in bounded batches, increasing gradually but never beyond 50.
7. Pause immediately on any identity mismatch or dispatch failure, stuck leases
   beyond 30 minutes, sustained 429/5xx behavior, or an unexpectedly elevated
   failed/source-unavailable rate. Review failure classes before retrying.
8. Rerun only after the cause is understood. Active leases and row locks prevent
   concurrent duplication; terminal failures may be deliberately retried.

## 10. Regression Results

| Check | Result |
|---|---|
| Sprint 1.1 | 9 passed |
| Sprint 1.2 | 15 passed |
| Sprint 1.3 | 11 passed |
| Sprint 1.3B | 10 passed; one Alembic deprecation warning |
| Auth/security matrix | 64 passed, 10 subtests passed |
| World Bank, UTC | 18 passed |
| World Bank, Asia/Tashkent | 18 passed |
| World Bank, America/New_York | 18 passed |
| Connector regression gate | 195 passed, 1 known storage-fixture skip, 4 subtests passed |
| Frontend Project Context | 18 passed |
| TypeScript | passed |
| ESLint | zero errors; 15 pre-existing warnings |
| Next.js 16.1.6 production build | passed; existing middleware deprecation warning |
| Alembic current/head | `20260826_0002_s1_2_wb_project_enrichment` |
| Alembic check | `No new upgrade operations detected.` |

There were zero regression failures and no new skip. No migration was created.
No deployment, production access, ADB work, Project architecture change, auth
redesign, or Sprint 2 work occurred.

## 11. Release Recommendation

**Recommend inclusion, with path-scoped provenance before release.** The
ten-file S1.3B logical delta is dependency-complete and all audited behavior is
justified. Retain the auth trio together; excluding only one member would break
the build or document-proxy import. Include the three S1.3C test corrections
and this audit document as a separate verification commit.

Because Sprint 1.1–1.3 and S1.3B were never separated by Git commits, do not
stage the entire dirty workspace. First preserve the logical earlier-Sprint
base in its own reviewed commit(s), then stage exactly the ten S1.3B paths, and
finally the four S1.3C audit paths. Generated bytecode, build output, local
runtime state, and unrelated later work must remain excluded.

Recommended next task: prepare and review those path-scoped Sprint 1 commits;
do not deploy and do not begin Sprint 2 as part of this audit.
