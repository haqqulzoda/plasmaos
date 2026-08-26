# Sprint 1.3B — Project Context Runtime Integration Recovery

## 1. Reproduced Symptom

Environment: controlled local non-production only. Production was not accessed
or deployed.

The configured application database was inspected before any migration. A real
World Bank tender (`cf6b92bb…`, source `world_bank`, raw project ID `P171305`)
followed the Tender Explorer → Tender Details → Project Context path. The
request path was:

`GET /api/v1/tenders/{tender_id}/project`

The current endpoint code raised SQLAlchemy `ProgrammingError` from PostgreSQL
because the `projects`/`tender_projects` relations did not exist. That was a
real 500 backend failure, not a no-project or pending result. The Tender Details
page caught the Project request independently, retained the tender, constructed
the World Bank fallback identity, and the `failed` branch in
`ProjectContextSection` rendered exactly:

`Project details are temporarily unavailable.`

The already-running local port-8000 API was also a stale pre-S1.3 image: its
OpenAPI document lacked the Project route and the same path returned 404. The
old frontend catch treated that response as the same generic failure.

## 2. Root Cause

The primary cause was layer A, database schema: the configured local database
was still at Sprint 0.4C and had neither Project table. That made the current
Project API fail at query execution.

Two additional integration blockers were proven:

- Layer F/runtime lifecycle: the running local API and Celery images were stale;
  the API lacked the endpoint and both inspected workers lacked
  `app.workers.project_enrichment_tasks.enrich_world_bank_project`.
- Existing Project rows had no explicit operator reconciliation path. They were
  only queued by a later World Bank tender refresh, which is an integration gap
  for already-migrated data.

The frontend also collapsed 404, 401/403, and 5xx into one generic failure
branch. Typed status classification now reserves temporary-unavailable for
actual endpoint failures.

## 3. Environment Revision

| Check | Before | After |
|---|---|---|
| Database environment | local controlled non-production | local controlled non-production |
| Alembic revision | `20260824_0002_s0_4c` | `20260826_0002_s1_2_wb_project_enrichment (head)` |
| `projects` table | absent | present |
| `tender_projects` table | absent | present |
| `alembic check` | not applicable while behind | `No new upgrade operations detected.` |

The existing migration chain was applied with `alembic upgrade head`; no
`create_all` and no new migration were used. An attempted pre-upgrade database
clone was rejected because seven active sessions prevented a PostgreSQL
template copy, so no pre-upgrade clone was created. The migration itself ran
transactionally and completed successfully.

## 4. WB Project-ID Coverage

Post-recovery controlled-dataset coverage:

| Measure | Count |
|---|---:|
| Total World Bank tenders | 943 |
| Valid `P######` project ID | 943 |
| Without project ID | 0 |
| Malformed/suspicious | 0 |
| With TenderProject | 943 |
| With Project | 943 |

There are 416 distinct canonical World Bank Projects. After the monitored
reconciliation run, zero Projects remain pending/queued/running: 369 Projects /
845 tenders are `successful`, 2 Projects / 5 tenders are `partial`, and 45
Projects / 93 tenders are `failed` because the official endpoint returned an
empty authoritative record. These are local counts, not production estimates.

Representative pre-enrichment sanitized rows, captured after linkage and before
the full queue drain:

| Tender | Raw ID | Normalized ID | TenderProject | Project | Status |
|---|---|---|---|---|---|
| `0032cfa1…` | P173446 | P173446 | yes | yes | never_attempted |
| `007f690b…` | P175915 | P175915 | yes | yes | never_attempted |
| `009b8187…` | P169071 | P169071 | yes | yes | never_attempted |
| `00d0f997…` | P171997 | P171997 | yes | yes | never_attempted |
| `012c9d89…` | P176459 | P176459 | yes | yes | never_attempted |
| `017e76c6…` | P171144 | P171144 | yes | yes | never_attempted |
| `01d0e4cd…` | P177146 | P177146 | yes | yes | never_attempted |
| `01d82fac…` | P179466 | P179466 | yes | yes | never_attempted |
| `025d8317…` | P177627 | P177627 | yes | yes | never_attempted |
| `02d39b07…` | P177816 | P177816 | yes | yes | never_attempted |

## 5. TenderProject Coverage

The S1.1 migration backfill processed real local data with these counters:

| Counter | Count |
|---|---:|
| WB tenders | 943 |
| With raw project ID | 943 |
| Valid project IDs | 943 |
| Invalid/skipped | 0 |
| Distinct project IDs | 416 |
| Projects created | 416 |
| Projects reused | 527 |
| Links created | 943 |
| Links already present | 0 |
| Normalization changes | 0 |
| Errors | 0 |

The post-migration invariant is complete for this dataset: every valid World
Bank project ID has a canonical source-scoped Project and a TenderProject link.

## 6. Project API Behavior

Authenticated controlled calls now preserve distinct semantics:

| Condition | API result |
|---|---|
| No Project link | `200` with `null` |
| Linked, never enriched | `200`; canonical source/ID and `pending` freshness |
| Partial/source unavailable/stale | `200`; identity plus truthful state |
| Query/backend failure | uncaught server failure → 5xx |
| Missing/insufficient authorization | 401/403 |

Before migration, the known linked source identity could not be queried because
the relation was absent. After migration, `P171305` returned HTTP 200 with
`world_bank`, `P171305`, `never_attempted`, and `pending`, without requiring
enrichment fields.

After the local Compose rebuild, an authenticated call for tender `5a3718e8…`
returned HTTP 200 with `P151224`, `successful`, `fresh`, title, country, official
source URL, two current roles, and no historical roles.

## 7. Enrichment Queue Behavior

Before S1.3B, pre-existing canonical Projects waited for incidental future
tender refresh. S1.3B adds an explicit operator command:

`python3 scripts/enqueue_world_bank_project_enrichment.py`

It is dry-run by default. Apply mode requires both `--apply` and the exact
confirmation phrase, enforces a 1–50 batch, reuses the S1.2 claim/lease and
Celery dispatch services, and performs no World Bank HTTP inside the command or
migration. A dry run with limit 5 reported five eligible and no mutation. The
first apply proof reported 3 claimed, 3 enqueued, 0 dispatch failures. The
post-rebuild proof reported 1 claimed, 1 enqueued, 0 dispatch failures.

Selection and leases make reruns idempotent with respect to active work; the
deterministic orchestration test covers the zero-claim rerun result.

The complete controlled run exposed and fixed a fairness issue in which older
failed rows could sort ahead of untouched rows. Claim ordering now prioritizes
`never_attempted` Projects, preventing known empty-source records from starving
pending Projects. The run finished with no `never_attempted`, queued, or running
World Bank Project.

## 8. World Bank Live/Controlled Source Check

The existing S1.2 official client was exercised with real canonical IDs from
the controlled database:

| Project | HTTP/identity | Parsed result | Roles |
|---|---|---|---|
| P146788 | 200, matching ID | title/country/status present; successful | 2 |
| P149279 | 200, matching ID | title/country/status present; successful | 2 |
| P150520 | 200, matching ID | sparse authoritative record; partial | 0 |
| P151224 | 200, matching ID | title/country/status present; successful | 2 |

`P151224` was received by the rebuilt local Celery worker, requested from
`https://search.worldbank.org/api/v2/projects?format=json&id=P151224&rows=1`,
and succeeded in 1.283 seconds. Metadata and two roles were persisted.

World Bank `teamleadname` remains the native role and maps conservatively to
`OTHER_PROJECT_ROLE` / “World Bank project team.” No TTL claim, email, phone,
or other person inference was introduced; persisted inferred-email count is
zero.

## 9. UI State Corrections

The request catch now classifies HTTP outcomes:

- 404 is no-project and omits the section.
- 401/403 is authorization and does not claim source unavailability.
- 5xx/network failure is an endpoint failure and may show the temporary
  unavailable message while the Tender remains usable.
- A linked pending Project receives a successful response and renders its
  canonical identity with “Project details are being prepared.”
- `stale`, `incomplete`, and `unavailable` freshness remain distinct.
- Source-unavailable renders “Official project data is currently unavailable,”
  while the endpoint-failure fallback alone renders “Project details are
  temporarily unavailable.”

The auth configuration was moved out of the route module so the current Next
16 production build can export only valid route handlers. This is a structural
build fix; callbacks and session behavior are unchanged.

## 10. Browser Acceptance Matrix

Actual headless Chrome was run against current-code local API/UI processes with
a legitimate approved local backend identity. Source-state variants used
controlled network responses based on the real enriched `P146788` response.

| Case | Expected | Observed |
|---|---|---|
| A linked + enriched | real identity, metadata, official source | pass |
| B linked + pending | P171305 + preparing; no unavailable | pass |
| C sparse metadata | P150520 + incomplete message | pass |
| D current leadership | leadership visible; conservative labels | pass |
| E historical leadership | separate previous-leadership disclosure | pass |
| F stale | outdated message | pass |
| G source unavailable | truthful source-unavailable message | pass |
| H no Project | Project Context omitted | pass |
| I Project API 5xx | tender survives; temporary-unavailable shown | pass |

Result: 9/9 passed.

## 11. Tests

- S1.1: 9 passed.
- S1.2: 15 passed.
- S1.3: 11 passed.
- S1.3B backend recovery: 10 passed, one Alembic deprecation warning.
- Frontend Project Context: 18 passed.
- World Bank: 18 passed in each of UTC, Asia/Tashkent, and America/New_York.
- Disabled authorization + UNKNOWN actionability: 49 passed, 8 subtests passed.
- Connector gate: 195 passed, 1 known storage-fixture skip, 4 subtests passed.
- Frontend typecheck: passed.
- ESLint: zero errors, 15 unchanged warnings.
- Clean frontend production build and Docker production build: passed; the
  existing middleware-convention warning remains.
- Alembic current/check: head and clean.

No new skip was added. The existing connector skip is
`test_storage_path_resolver.py:33` because the optional 481480 local fixture is
absent.

## 12. Remaining Risks

- All 416 linked Projects were attempted. The official API returned usable
  source data for 369, sparse data for 2, and HTTP 200 with no authoritative
  Project record for 45. The 45 retain canonical identity and truthful failure
  state; they should not be presented as fabricated Project metadata.
- The local Compose environment has no configured `AUTH_SECRET`, Google client
  ID, or Google client secret; its NextAuth session endpoint therefore returns
  a configuration 500. The browser matrix used an isolated non-production auth
  configuration and did not weaken application authorization. Local operators
  must supply those environment values before normal Google login acceptance.
- No pre-upgrade database clone exists because active connections blocked the
  attempted template copy. The controlled migration completed successfully and
  current integrity/coverage checks pass.
- The container build reports dependency-audit findings and the existing Next
  middleware deprecation warning; neither was introduced or expanded in S1.3B.
- No production database, broker, runtime, or deployment was touched. ADB,
  Tender actionability, people inference, Sprint 2, and new Project features
  remain out of scope.
