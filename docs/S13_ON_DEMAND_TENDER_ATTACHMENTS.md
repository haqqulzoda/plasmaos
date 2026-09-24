# Sprint 13 — On-Demand Tender Attachments

## Status and boundary

Sprint 13 makes UzEx and GIZ attachment acquisition explicit, asynchronous,
source-aware, and passive on customer reads. It reuses the existing
`TenderDocument` and `TenderSyncJob` authorities and the existing persistent
Notifications outbox. No production system was accessed, no deployment was
performed, and the Compliance engine and ADB/EBRD connectors were not audited
or repaired.

The sole Alembic head remains
`20260912_0001_s10_5_communications`. Existing durable document and job fields
were sufficient, so no migration was added.

## Root causes before implementation

The lifecycle audit found two separate causes:

- UzEx Hunter discovery dispatched `process_tender_docs` immediately after
  persisting every new Tender. Source refresh therefore caused binary
  acquisition without a user command.
- GIZ metadata refresh could hydrate inline, while the worker later attempted
  to reuse a stored e-procurement archive URL in a new HTTP session. GIZ's
  official flow is project page -> participation-documents page -> archive;
  the archive URL may rotate or depend on cookies established by those pages.

The canonical descriptor/persistence authority remains `CanonicalDocument`,
`NormalizedAttachment`, and `persist_document_descriptors` in
`app/services/tender_sources/base.py`. `TenderDocument.download_status`, local
storage metadata, parsed text, and `TenderSyncJob` remain the status
authorities. The existing `heavy_dl_queue`, parser, storage-path resolver, and
upload/archive controls remain in use.

## UzEx change

Hunter/source refresh now persists Tender metadata only. It no longer imports
or dispatches `process_tender_docs`. Explorer, Tender Details, Compliance page
loads, and source refresh do not download or parse UzEx attachments.

An authorized user explicitly starts acquisition with
`POST /tenders/{tender_id}/sync-docs`. The command creates one durable job and
queues one bounded multi-document task on `heavy_dl_queue`. The existing UzEx
official portal flow then discovers, streams, validates, stores, and parses the
documents. Successfully parsed retries clear earlier failure state and become
`processed`.

## GIZ restoration

GIZ source refresh is metadata-only and rejects the former
`download_documents=true` behavior. Explicit acquisition opens one
cookie-preserving `httpx.AsyncClient`, revisits the legitimate official GIZ
project page, follows the participation-documents link, discovers the current
archive, and downloads it in the same session.

Redirects are manual, capped at five, and every hop must remain on an approved
`giz.de` host. Expired archive URLs are rotated on the existing stable
document identity. If the current official page exposes no public archive, the
worker does not retry an old stored link; it records access-required truth.
There is no anti-bot bypass, stealth automation, proxy rotation, or unofficial
endpoint.

## Shared acquisition lifecycle

The customer lifecycle is:

`AVAILABLE_REMOTE -> QUEUED -> DOWNLOADING -> PROCESSING -> READY`

Terminal mixed and unsuccessful outcomes are `PARTIAL` and `FAILED`.
`TenderSyncJob.progress` is durable; progress below the worker's processing
boundary maps to downloading and progress at or above it maps to processing.
No percentage or ETA is presented as user-facing fact.

The command locks the Tender row, checks for any active job for that Tender,
and then creates the job. This makes duplicate clicks, including clicks by
different authorized users, converge on the same active task. Celery uses late
acknowledgement, rejection on worker loss, prefetch 1, bounded publish retry,
and a single-concurrency heavy worker. Redelivery reuses stable document
identity, existing stored files, and SHA-based GIZ inner-file deduplication.
Partial success is committed and is not invalidated by another attachment's
failure.

## Progress UI

Tender Details keeps its two initial passive reads. The document panel shows
remote availability, queued, downloading, processing, ready, partial, and
failed states with localized EN/UZ/RU/AR copy and per-document state. Only an
explicit button click sends the acquisition POST.

While a job is active there is exactly one two-second status poller, capped at
150 attempts (five minutes), with cleanup on state/route changes. Each poll
updates the displayed durable backend state and counts. Terminal state reloads
the bounded details projection. `Run compliance analysis` appears only when
the attachment state is ready and remains a separate user action.

## Notifications

Terminal job state and one notification-outbox intent are committed together.
The job emits exactly one of `DOCUMENTS_READY`, `DOCUMENTS_PARTIAL`, or
`DOCUMENTS_FAILED`, keyed by `document-acquisition:{job_id}`. Payloads contain
only the Tender/job identifiers and ready/total/failed counts. Notification
navigation validates the Tender UUID and returns to the Tender Details
requirements/documents anchor.

## Compliance readiness boundary

Compliance analysis rebuilds its input only from documents that have all of:

- an existing local stored file;
- non-empty parsed text;
- no failed, unavailable, missing, or access-required state.

Remote metadata and stale `compiled_master_text` alone are insufficient. GIZ
compiled text and coverage use the same local-file boundary. Download workers
never start analysis automatically.

## Storage and security

The existing safe storage root and normalized path resolver remain
authoritative. Filenames are sanitized and writes use a `.part` file followed
by an atomic rename. Failed partial files are removed. GIZ validates signatures
rather than trusting MIME headers, rejects HTML/error payloads, caps downloads,
and preserves archive path, symlink, executable, file-count, individual-size,
total-expanded-size, nesting, and compression-ratio defenses.

Default GIZ limits are 100 MiB compressed/downloaded, 250 MiB expanded, 50 MiB
per member, 200 members, one archive nesting level, and 100:1 compression.
The two committed large document fixtures are 1,239,754 and 19,946,735 bytes:
average 10,593,244.5 bytes (10.10 MiB), maximum 19,946,735 bytes (19.02 MiB).
Repeated normal acquisition reuses the durable file; duplicate extracted GIZ
content reuses the existing SHA-matched file. No retention/deletion policy was
introduced.

## Performance and passivity

- Initial Tender Details browser graph: exactly two passive GETs.
- Initial source HTTP, attachment download, parse dispatch, and mutation: zero.
- Details SQL ceiling: 15 constant statements, including one latest-job read.
- Document summary/count reads are set-based; rendered items are capped at 25.
- One acquisition command covers all documents; there is no per-file browser
  command or notification.
- Active polling is one bounded timer; no `/users/me` call was added.
- Heavy attachment work remains on the concurrency-1 heavy queue.

## Validation

- Focused Sprint 13/GIZ/document tests: 29 passed.
- Full pinned backend gate: 769 passed, 1 skipped, with 100 subtests passed.
- Security gate: 118 passed.
- Analysis gate: 50 passed, with 12 subtests passed.
- Connector regression gate: 198 passed, 1 skipped, with 6 subtests passed.
- Alembic heads/current/check and disposable schema preflight: passed.
- Scale gate passed at 1,000, 10,000, and 100,000 Tenders while retaining
  constant query counts (at most five for details/document availability and
  three for missing-Tender reads).
- Frontend typecheck, ESLint, production build, and 220/220 static tests:
  passed. The production build generated 26 static pages.
- Four-locale RTL/physical-property audit: passed.
- Maintained Chromium acceptance: 145/145 passed with zero external requests.
- Python dependency consistency and the high-severity frontend dependency
  audit: passed; the frontend audit reported zero vulnerabilities.

## Exact Sprint 13 files changed

- `.gitignore` (keeps this Sprint 13 report visible to version control)
- `backend/app/api/endpoints/tenders.py`
- `backend/app/schemas/tender_details.py`
- `backend/app/services/giz_document_hydration.py`
- `backend/app/services/notifications.py`
- `backend/app/services/tender_details.py`
- `backend/app/services/tender_sources/giz.py`
- `backend/app/workers/hunter_tasks.py`
- `backend/app/workers/tender_tasks.py`
- `backend/test_giz_hydration_worker.py`
- `backend/test_release_reads.py`
- `backend/test_s0_5b1_unknown_actionability.py`
- `backend/test_s5_cross_source_regression.py`
- `backend/test_s6_1_hunter_explorer_convergence_foundation.py`
- `backend/test_s6_4_hunter_retirement_final_qa.py`
- `backend/test_s13_on_demand_tender_attachments.py`
- `backend/test_tender_document_status.py`
- `frontend/app/dashboard/notifications/page.tsx`
- `frontend/app/dashboard/tenders/[tenderId]/page.tsx`
- `frontend/lib/communications.ts`
- `frontend/messages/{en,uz,ru,ar}/notifications.json`
- `frontend/messages/{en,uz,ru,ar}/tenderDetails.json`
- `frontend/tests/hunter-retirement.test.mjs`
- `frontend/tests/s10-6-communications.test.mjs`
- `frontend/tests/s8-3-arabic-rtl.test.mjs`
- `frontend/tests/tender-details.test.mjs`
- `frontend/types/tender-details.ts`
- `docs/S13_ON_DEMAND_TENDER_ATTACHMENTS.md`

The accepted Sprint 11/12/12R dirty working tree was preserved; unrelated
changes were not reset.

## Remaining risks and Sprint 14 entry contract

- Official UzEx/GIZ availability, session behavior, and source payload quality
  remain external dependencies; failures now surface as durable partial/failed
  state rather than hidden page-load work.
- The durable job and late-ack worker recover worker loss, but an infrastructure
  outage between the database commit and broker acceptance can leave a pending
  job requiring operational reconciliation. A future sprint may add a generic
  task outbox/watchdog if operational evidence justifies it.
- Status polling deliberately stops after five minutes; the persistent
  notification remains the completion authority for longer jobs.

Sprint 14 may begin only from the unchanged Alembic head after Sprint 13 gates
are green. It must preserve explicit acquisition, passive reads, local-file
Compliance readiness, job-level notifications, bounded source security, and
the accepted dirty tree. Sprint 13 does not authorize a Compliance-engine
audit, ADB/EBRD repair, production access, deployment, or a retention policy.
