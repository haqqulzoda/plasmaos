# Sprint 9.2 — Legacy Contract and Test Topology Cleanup

Audit/implementation date: 2026-09-05. Branch: `main`. Baseline and unchanged HEAD:
`b121cda5b76911c59fdab5733d70aa6883908e9c`.

## 1. Executive Summary

**Sprint 9.2 cleanup passes its scoped gates. The application is NOT release-ready.**
H01–H12 remain deferred, with H01/H02 mandatory Sprint 9.3 release blockers.

Moved four explicit developer probes, renamed 15 colliding PostgreSQL proof scripts,
repaired the exact ten stale test nodes, removed three obsolete refresh helpers,
deleted the closed 22-function GIZ duplicate set and redundant security shadow,
removed two unused frontend dependencies, and untracked 53 Python caches. No
compatibility HTTP route, connector, model, migration, translation key or live
DocumentViewer was removed. Runtime behavior of surviving definitions is unchanged.

Final validation: **615 collected; 614 passed, 1 skipped, 100 subtests passed**.
The ten repaired nodes pass individually. Connector gate: **196 passed, 1 skipped,
6 subtests passed**. Clean npm install, all 19 frontend checks and production build
pass. Disposable PostgreSQL bootstrap/current/check pass at the sole expected head.

Evidence: [execution and exact files](audits/s9_2/execution.json),
[100-target safety ledger](audits/s9_2/safety-ledger.md),
[90 acceptance criteria](audits/s9_2/acceptance.md).

## 2. Baseline / Rebased SHA

Current HEAD matched the accepted 9.1 SHA; the inventory was regenerated before
deletion rather than assumed current. It reconfirmed 29 frontend entries, 91 backend
method/path entries, 15 duplicate test basenames, 53 tracked caches and the identified
helper closure. See [preflight](audits/s9_2/preflight.json) and
[rebased inventory](audits/s9_2/rebased_inventory.json).

The initial worktree already contained accepted untracked 9.1 documentation/tooling
and three modified Python 3.14 cache files. Those are recorded separately. The 9.1
query-probe import was updated for the renamed proof dependency; historical 9.1
JSON/screenshots/results are preserved. Cache removal affects the Git index and
retains local bytes, including the three pre-existing modified caches.

Tooling used isolated Python 3.12.3, Node 22.14.0/npm 10.9.2 and PostgreSQL 16.15.
Backend requirements were not changed or locked; their resolved test environment is
recorded separately and is not asserted to be production's environment.

## 3. Probe Cleanup

| Previous path | New explicit tool | Result |
| --- | --- | --- |
| `backend/test_ai.py` | `backend/scripts/probes/ai_probe.py` | Configurable PDF and optional env-file; no chdir; model call inside main only. |
| `backend/test_tender_api.py` | `backend/scripts/probes/tender_api_probe.py` | Configurable base URL; timeout bounded to 0 < seconds <= 120; handles empty list. |
| `backend/test_uzbek_nlp.py` | `backend/scripts/probes/uzbek_nlp_probe.py` | Configurable OpenAPI target and bounded timeout; no import-time HTTP. |
| `backend/scripts/test_extraction.py` | `backend/scripts/probes/extraction_probe.py` | Additional broad-collection blocker: removed MODEL_NAME import and obsolete prompt signature. Explicit diagnostic now uses the existing model chain and taxonomy argument. |

The fourth move is topology repair discovered by actual broad collection, not a
product extraction redesign. It preserves the synthetic procurement diagnostic payload
and raw/validated response inspection. No live model probe was invoked.
[Usage](../backend/scripts/probes/README.md) documents all commands.

## 4. Pytest Collection Repair

No deselection configuration was introduced. Probes no longer have pytest filenames.
`verify_s9_2_collection.py` runs recursive backend collection with network connection,
process launch and chdir guards, and imports renamed proof modules under those guards.
Final result: **615 tests collected; operational side effects detected: 0**.

Probe import tests execute each module in an isolated process that rejects all
dependency imports, file-open operations and chdir during module execution; they
also check stdout/stderr, environment and sys.path remain unchanged. Four probes pass.
Reading/compiling the probe's own source happens before the guard is installed.

## 5. Duplicate Basename Repair

The original selected root/script pair reproduced the pytest import-mismatch error
before cleanup (9 tests collected, 1 collection error). All 15 colliding script-side
files were renamed to `verify_*.py`; root product test names remain unchanged.

Every exact old/new path is in the [rename ledger](audits/s9_2/renames.json).
Imports, two historical command references, the Sprint 8 migration proof and the
root PostgreSQL bridge were updated. Historical reports retain their original
outcomes. All 15 proof ASTs match their originals except renamed imports. Current
existing test files have zero duplicate basenames; guarded broad collection passes.

## 6. Ten Stale Assertion Repairs

The exact original test IDs are retained in [stale-nodes.json](audits/s9_2/stale-nodes.json).
Their independently invoked gate is **10/10 PASS**.

| Original contract | Current assertion |
| --- | --- |
| Onboarding submission/recovery copy | Namespace/key plus all four catalogs; submitted state, actual POST, session update and pending redirect remain checked. |
| Admin shell/redirect | Localized dashboard Admin link plus existing standalone Admin guards and both legacy redirects. |
| Settings/Readiness pages | Translated titles, optional-file field and canonical navigation key/route pairs. |
| Geography selection | Shared metadata, canonical selected-country state and translated select-all control. |
| Service taxonomy | Canonical service values consumed by localized taxonomy presentation; readiness service fallback retained. |
| Approval/pilot status | Catalog `{status}` interpolation fed by the respective account-status values. |
| Readiness labels/filters/files | Current type/status/expiry message-key helpers; filters, create/update/delete and nullable optional file retained. |
| Explorer geography | Canonical countries/services and query filters plus localized country/service display. |
| Explorer client/Hunter redirect | Whitespace-tolerant actual client call, canonical endpoint and passive compatibility redirect. |
| Recommended view | Stable `recommended` key, translated label and canonical navigation. |

`backend/frontend_contracts.py` provides small quote/whitespace-tolerant source and
catalog assertions. These remain static architecture checks, not browser execution
claims. Existing frontend semantic/localization suites also passed. No stale node
was deleted, skipped or deselected.

## 7. Refresh Helper Cleanup

Removed only `source_refresh_jobs.py::_bounded_int` and `::_strict_bool` after
reconfirming definition-only usage, no decorators/task registration, and no dynamic
or external repository caller. `validate_source_refresh_options` still delegates
to the unchanged source registry. Invalid-option and source refresh regressions pass.

## 8. Source Result Adapter Cleanup

Removed `tenders.py::_normalized_source_result` and its now-unused adapter import.
The two test-only callers now use `source_registry.adapt_execution_result` directly.
Tests preserve unavailable/parser-failure outcomes, metadata and message, and add
created/updated/unchanged/skipped/failed counts, alias precedence, zero counts,
rejected-count fallback and unknown-state failure behavior. Source DTOs and runners
are unchanged. The extra count test explains the connector gate's one additional test.

## 9. Frontend Dependency Cleanup

Removed only direct `jwt-decode` and `tailwind-merge`. No tracked static/dynamic
imports, plugin/configuration usage or package-script use remained. The lock graph
removed exactly their two package entries, added none, and left every other package
record identical. [Dependency proof](audits/s9_2/dependency-proof.json).

Clean `npm ci` and all checks ran in a fresh Linux frontend copy with unchanged
sibling backend files used by a cross-repository static test. The first Hunter
retirement invocation failed only because those sibling files were absent from the
temporary copy; correcting the copy made the unchanged test pass. No security
dependency upgrade occurred; H08 remains open.

## 10. GIZ Duplicate Closure

Deleted the exact 22 named functions listed individually in the
[safety ledger](audits/s9_2/safety-ledger.md), identified by AST names rather than
line range. [Call-graph evidence](audits/s9_2/deletion_proof.json) records all tracked
references, hashes and absent decorators. There were no incoming same-module edges
from outside the set; matching service/test references address the active service,
not endpoint copies. No dynamic loader or task registration targets the closure.

`giz_document_hydration.py`, heavy worker/task, archive limits, source definitions,
ADB/EBRD helpers and shared surviving helpers remain unchanged. Removed `zipfile`
import became unused only because of this closure. All **199 surviving Tender
module function/class definitions are AST-identical** to baseline. GIZ, archive,
hydration, status/coverage, heavy-worker and connector regressions pass.

## 11. Security Module Topology

Before removal, `core/security.py` and `core/security/__init__.py` had identical
ASTs; normal imports resolved the package. Three static tests read the mirror file;
they now check the canonical package and preserved guards/version behavior. No
tracked importlib direct-file loader, deployment/script entrypoint, alternate
configuration or registered task required the sibling file.

Removed the redundant sibling file; updated only the package's obsolete topology
comment. The package AST remains identical to baseline. Canonical import names,
eight-hour expiry and auth/account behavior are unchanged. Out-of-tree direct-file
usage was not established as a supported compatibility contract; no public route
was removed. The high-risk restoration unit is explicitly listed in the ledger.

## 12. DocumentViewer Decision

**KEEP** `frontend/components/workspace/DocumentViewer.tsx`. Moving its live
Compliance dependency would add path churn without changing the cleanup's outcome.
The component, import, preview/download behavior and catalogs remain unchanged.
Frontend Compliance/Tender Details, localization and RTL contract suites pass.

## 13. Config Cleanup

`ACCESS_TOKEN_EXPIRE_MINUTES` is not a consumed environment setting. No tracked
example/config value needed removal; the identical runtime constant of that name
still supplies the existing eight-hour expiry. Private `.env` files were not edited.

**KEEP + document legacy status** for `NEXT_PUBLIC_API_URL` and
`FRONTEND_NEXT_PUBLIC_API_URL`: Axios uses relative `/api/v1`, but Compose, Dockerfile,
release wrapper and configuration tests still consume/forward these build inputs.
No deployment variable or Docker exposure was changed.

## 14. Historical Tool Classification

[Scripts guide](../backend/scripts/README.md) and
[58-path tool inventory](audits/s9_2/tool-classification.json) classify historical
proofs, explicit-use diagnostics, operational wrappers and schema/data-changing
add/reset/init/seed/purge utilities. They are not a recommended automatic setup path.
Baseline/bootstrap resources remain authoritative for their documented guarded use.
Historical reports retain their results, with narrow renamed-command updates or
explicit 9.2 notes. No historical migration evidence was destroyed.

## 15. Compatibility Decision Ledger

| Surface | Decision | Reason / compatibility contract |
| --- | --- | --- |
| `/dashboard/hunter` | KEEP | Existing bookmarks redirect to `/dashboard/tenders?view=recommended`. |
| Hunter HTTP API, including slash alias | KEEP | No current frontend caller does not establish external-client absence. |
| `/audit/authorize` | KEEP | Existing alternate mount; hardening/deprecation requires separate work. |
| `/api/v1/audit/authorize` | KEEP | Same handler, retained explicit API mount. |
| `/sources/world-bank/sync`, `/sources/giz/sync`, `/sources/ebrd/sync`, `/sources/adb/sync` under Tender API prefix | KEEP | Operator adapters delegate; underlying runners remain worker dependencies. |
| `POST /api/v1/tenders/refresh` | KEEP | UzEx compatibility request into canonical refresh orchestration. |
| `/dashboard/bids`, `/dashboard/proposals` | KEEP | Bid Preparation redirects preserve bookmarks. |
| `/dashboard/bids/[id]` | KEEP | Proposal ownership resolution precedes canonical artifact redirect. |
| `/dashboard/workspace` | KEEP | Explorer redirect; live DocumentViewer is a separate dependency. |
| `/dashboard/admin`, `/dashboard/admin/approvals` | KEEP | Standalone guarded Admin redirects. |
| `/api/documents/[id]`, `/document-preview/[id]` | KEEP | Existing authenticated download/preview proxy contracts. |
| Active Hunter worker, agent, Celery names and Beat entry | KEEP | Scheduled recommendation/document work, not retired frontend code. |
| Legacy Tender list/detail GETs | KEEP behavior in 9.2 | H02/H03 remain mandatory hardening work; no assertion added to approve bypasses. |

There are **no approved HTTP route removals**. All 29 frontend entries and all
backend route declarations remain unchanged. Source-specific runners and scheduled
task identities are preserved. No external usage telemetry was assumed.

## 16. Python Cache Cleanup

Fresh `git ls-files` inventory contained exactly **53** cache files. Removed only
their index entries; local files, including three pre-existing modified caches,
were retained. Existing ignore rules remain unchanged. After imports, collection,
regressions and migration checks, `git ls-files` contains zero cache artifacts.
Generated caches do not appear as new worktree changes. Index deletions are intended.

## 17. Translation Key Decision

**KEEP all keys.** No namespace-aware deletion proof was required because no key was
removed. EN/UZ/RU/AR catalogs, locale architecture and analysis-language architecture
remain unchanged. Localization, message and RTL gates pass. Arabic analysis and PDF
gates remain intact.

## 18. Final Route/Legacy Inventory

[316 surviving reference locations](audits/s9_2/legacy-references.json) classify
Hunter/workspace/My Bids/alias references as compatibility, active worker/domain,
live Compliance naming, internal presentation, brand copy or historical tests/docs.
The final route inventory is the unchanged 29-entry preflight list. Endpoint and
worker semantics were preserved by source/AST comparison rather than assumed from
navigation. No new legacy-navigation bug was introduced or silently fixed.

## 19. ORM/Migration Preservation

No ORM model/table, migration, source definition or recovery foundation was removed.
All five registry definitions remain. A preservation comparison covers 182
protected files, including models, migrations, connectors, workers, frontend pages,
components, catalogs, locale helpers, source registry and active GIZ service.
[Preservation evidence](audits/s9_2/semantic-preservation.json).

## 20. Test Collection Result

`cd backend && python scripts/verify_s9_2_collection.py`: **615 collected**, no
import mismatch and zero detected operational side effects. The initial extra
extraction-probe import failure was resolved by explicit probe relocation; no
collector ignore pattern concealed it. [Collection log](audits/s9_2/collection.log).

## 21. Backend Regression Result

`cd backend && python -m pytest -q test_*.py`: **614 passed, 0 failed, 1 skipped,
100 subtests passed, 6 warnings**, 52.38 seconds. No filename exclusions.
The skip is the pre-existing unavailable local storage fixture for Tender 481480.
No live PDF/model fixture was invented to force it to pass.
[Backend log](audits/s9_2/backend.log).

The suite includes real disposable PostgreSQL workflow coverage through the updated
root bridge, plus SR-2.x/SR-3, Explorer, Tender Details, My Tenders, Bid Preparation,
Compliance/version/ownership/concurrency/export and existing security contracts.
Historical standalone verification scripts were import-checked; this is not a claim
that every historical dataset/scenario script was executed as a current release gate.

## 22. Frontend Regression Result

Clean install, TypeScript, ESLint, customer literal/message validation, RTL audit,
and all 15 focused test commands pass (19 checks excluding install/build).
Production build passes. [Exact commands and logs](audits/s9_2/frontend-results.json).
No browser UI changed; historical browser launchers and new screenshot acceptance
were not rerun or claimed passed. Existing middleware deprecation remains deferred.

## 23. Connector Result

`bash backend/scripts/run_connector_regression_gate.sh`: **196 passed, 1 skipped,
6 subtests passed**, zero failures. [Connector log](audits/s9_2/connector.log).
The gate covers all five source fixtures, GIZ hydration/archive/status, heavy-worker
failures and source-refresh adaptation. No real ADB/EBRD recovery was attempted.

## 24. Sprint 8 Regression

Backend analysis-language/Arabic-UI contracts and frontend Sprint 7/8 localization,
analysis-language and RTL suites pass. Four-locale catalog files are unchanged.
UI language remains independent of analysis language; Arabic analysis and Arabic PDF
gates remain. No runtime language policy was redesigned.

## 25. Auth Regression

Existing Sprint 0/1/3, disabled/rejected, auth_version, Admin, lifecycle,
survivability and session revocation/restore coverage passes within the root suite.
An additional topology-focused run passed 38 tests/20 subtests before the fourth
probe was discovered; the final root/probe results supersede its import count.
H01/H02 were neither fixed nor legitimized by new positive assertions.

## 26. Alembic Result

Fresh guarded bootstrap on **127.0.0.1:56592 / plasma_s05b4b_s92_audit** completed;
`alembic heads`, `current` and `check` passed. Sole head:
`20260904_0001_s8_2_analysis_language`. Check reports no new upgrade operations.
Logs: [bootstrap](audits/s9_2/bootstrap.log), [heads](audits/s9_2/alembic-heads.log),
[current](audits/s9_2/alembic-current.log), [check](audits/s9_2/alembic-check.log).

Configured existing/production databases were not accessed. Online Alembic's
version-column-width mutation was confined to disposable targets. No migration was
added, deleted or squashed; no new data/schema behavior was introduced.

## 27. Clean Tree Result

The worktree intentionally contains reviewed cleanup changes and the pre-existing
accepted 9.1 additions. “Clean” here means no unexpected changes or generated fixture
files, not an empty `git status`. Cache deletions are staged; other cleanup edits
remain reviewable. No commit, deployment or branch change was made.

Temporary tooling, installed dependencies and PostgreSQL data are outside the
repository. Only explicit audit logs/JSON are retained. The final manifest separates
9.2 changes from 9.1 files; the one updated 9.1 query-probe import is intentional.

## 28. Exact Files Changed

The [execution manifest](audits/s9_2/execution.json) lists every changed path and
classification, including both sides of renames, 53 index cache deletions, exact
probe paths, test repairs, helper removals, dependency files, narrow historical-doc
updates and new 9.2 documentation/evidence. Artifact hashes are recorded for review.
The [safety ledger](audits/s9_2/safety-ledger.md) has 100 individual removal/rename
targets, each with caller/framework/task proof, compatibility, regression and rollback.

## 29. Deferred H01–H12 Hardening

| Finding | Carry-forward status |
| --- | --- |
| H01 Google bridge identity verification | **MANDATORY SPRINT 9.3 RELEASE BLOCKER**; caller-supplied identity acceptance unchanged. |
| H02 Guards on legacy Tender reads | **MANDATORY SPRINT 9.3 RELEASE BLOCKER**; public read bypass unchanged. |
| H03 Passive GET source/document I/O | Open; retrieval fallbacks unchanged. |
| H04 Explorer bounded filtering | Open; global filesystem/corpus prepass unchanged. |
| H05 Upload limits/signature/cleanup | Open; production upload behavior unchanged. |
| H06 Stable errors/redacted logging | Open; no broad application sink/error rewrite. |
| H07 Credential/configuration exposure | Open; no rotation or Docker exposure change. |
| H08 Advisory triage/reproducibility | Open; only two unused direct dependencies removed, no security upgrades. |
| H09 Pagination/history performance | Open; production collection contracts unchanged. |
| H10 Production request amplification | Open; middleware/provider request behavior unchanged. |
| H11 Canonical sign-in/session recovery | Open; redirect/recovery behavior unchanged. |
| H12 Mobile clipping/overlap | Open; no product layout changes. |

Permanent CI/release gate and readiness/queue/failure diagnostics also remain 9.3 work.

## 30. Sprint 9.3 Entry Contract

Start from the reviewed 9.2 diff and rerun baseline checks. Prioritize H01 identity
proof and H02 direct-backend guards with synthetic negative auth tests; then remove
passive retrieval, bound filtering/history/list inputs, harden uploads and errors,
resolve configuration/dependency exposure, measure production request duplication,
repair session recovery and mobile issues, and implement the permanent release gate
and operational diagnostics. Preserve canonical domains, source contracts and Arabic
gates. Credential/deployment actions require their own concrete scope; production
access or deployment is not implied. **No 9.3 implementation was started.**

## 31. Remaining Risks

Passing cleanup regressions is not production security certification. H01–H12 and
operational/CI gaps remain; production configuration, external-client use and live
model/browser behavior were not revalidated. The backend dependency manifest remains
unlocked, and existing deprecation warnings persist. Historical proof scripts retain
sprint-specific assumptions even though imports are now collision-free.

This sprint ends with scope-preserving cleanup, retained evidence and a concrete
hardening handoff. No ADB/EBRD repair, production access/mutation or deployment occurred.
