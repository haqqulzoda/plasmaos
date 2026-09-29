# D1-03 official notice as a shared source document

Problem: no open World Bank tender had a `TenderDocument` with `parsed_text`, so a SOURCE pursuit could not be analysed without a private upload, although the notice text itself (median ~5,500 characters; for a Request for Expression of Interest it contains the shortlisting criteria) is already stored on the tender. This change gives every tender with a substantive notice one system-generated, shared-source document holding that text, so `build_analysis_pack_candidate` marks it `parse_ready` and it is sealed like any other source document. Pack, run, review and staleness semantics (W2–W8, D1-01) are unchanged.

## The row

One `tender_documents` row per tender, identified by `source_document_type = 'OFFICIAL_NOTICE'` (constant `OFFICIAL_NOTICE_DOCUMENT_TYPE`).

| Column | Value |
| --- | --- |
| `file_url` | `official-notice://{source_system}/{external_id}` (percent-encoded; a `sha256-…` form if longer than 500 characters). Not fetchable. |
| `file_type`, `mime_type` | `text/plain` |
| `source_document_type` | `OFFICIAL_NOTICE` |
| `source_document_url` | the tender's `source_url` |
| `download_status` | `processed` |
| `storage_path`, `external_file_id` | `NULL` |
| `parsed_text` | the normalized notice text (below) |
| `sha256` | SHA-256 of `parsed_text` (UTF-8); `file_size` is its byte length |

`created_at` is the first capture time and is never rewritten. A notice text change updates `parsed_text`/`sha256`/`file_size` in place; the pack candidate's content hash then changes, so a run sealed from the previous text shows the existing "documents changed" banner (`inputs_changed`).

## Text

Deterministic, no AI, no paraphrase, no timestamps of our own:

```
=== OFFICIAL NOTICE: SOURCE FIELDS ===
Title: …
Reference: {external_id}
Notice type: …
Borrower/client: {buyer}
Country: …
Publication date: YYYY-MM-DD
Deadline: YYYY-MM-DD HH:MM UTC
Source URL: …

=== OFFICIAL NOTICE: NOTICE TEXT ===
{body}
```

* Fields come only from the persisted `Tender` row. A missing or blank field is omitted, never guessed.
* Times are stored in UTC, so the deadline is printed in UTC. A stored instant of exactly `00:00:00` or `23:59:59.999999` is what connectors write when the source gave a date but no time; it prints as `YYYY-MM-DD (UTC date; no time stated)` instead of inventing a clock time.
* Body normalization (`notice_text_from_html`): stdlib `HTMLParser`; `script`/`style` dropped; entities decoded (terminated entities only in tag-free text, so `AT&T` survives); NBSP and zero-width spaces mapped to a space or removed; block tags become paragraph breaks, `<br>` a line break, `<ul>/<ol>` list items `- ` / `1. `, table cells ` | `; whitespace runs collapsed inside a line, at most one blank line between paragraphs.
* Eligibility: the **normalized stored description** must be at least `OFFICIAL_NOTICE_MIN_CHARS = 300` characters. Markup and entities do not count. Applies to every source system.

### Structure of World Bank notices

The World Bank connector stores `description` as the notice HTML collapsed to one line, which loses every paragraph and list. Its raw payload (`source_metadata_json.notice_text`) still holds the HTML. `notice_body_text` uses that HTML for the body only when the words are provably the same as the stored description (equal after removing whitespace and the bullets/separators this normalizer adds); otherwise the stored description is used. So the text is always the stored notice's content, with its paragraphs and lists restored. Only `world_bank` is registered (`RAW_NOTICE_HTML_METADATA_KEYS`). Structure matters because the locator falls back to paragraphs for these items.

## Who writes it

* `persist_tender_batch` (`tender_sources/base.py`), the shared source-refresh persistence path used by every connector and sync endpoint. After each chunk's tender writes and in the same transaction it calls `sync_official_notices(db, tenders_of_the_chunk)`. All outcomes (created, updated, unchanged) are covered, so refresh also repairs a missing document.
* `scripts/backfill_official_notices.py` (operator).
* Nothing else. Customer GETs, pursuit commands and private uploads never call it (`test_only_source_refresh_and_backfill_write_official_notices`).

`sync_official_notices` is set-wise: one `SELECT tender_id, sha256` for the batch, then at most one `INSERT … ON CONFLICT (tender_id) WHERE source_document_type = 'OFFICIAL_NOTICE' DO UPDATE … WHERE tender_documents.sha256 IS DISTINCT FROM excluded.sha256`. Unchanged text issues no write (verified by `xmin` and by the statement log). Concurrent writers converge on one row. A build failure for one tender is logged (class only) and skipped so a pathological notice cannot fail a source refresh. Rows are never deleted: `pursuit_analysis_pack_items.tender_document_id` is `ON DELETE RESTRICT`. If a notice later drops below the threshold, the existing row keeps its last substantive text.

`persist_document_descriptors` (attachments) ignores OFFICIAL_NOTICE rows, so a connector that lists a document at the tender's own URL cannot overwrite the notice row.

## Migration

`20261003_0001_d1_03_official_notice_unique` (down: `20261002_0001_p0_extraction_trust_gate`): one partial unique index `uq_tender_documents_official_notice ON tender_documents (tender_id) WHERE source_document_type = 'OFFICIAL_NOTICE'`. Additive, reversible (drops the index), no data change; no earlier release wrote that type. The same index is declared on the model, so `alembic check` reports no drift. The `HEAD` constants in the migration tests and verify scripts are bumped to the new head.

## Exclusions

Every code path that acquires, hydrates, downloads, counts or compiles documents skips the row (`not_official_notice()`); `test_every_tender_document_query_excludes_the_notice_or_fetches_by_primary_key` walks the AST of each module and fails on any `select(TenderDocument …)` that neither excludes the row nor fetches by primary key.

| Path | Behaviour |
| --- | --- |
| UzEx/GIZ on-demand acquisition (`tender_tasks`): existing-document load, compiled master text, terminal counts | notice not loaded; never enters `compiled_master_text` or acquisition counts |
| ADB enrichment worker | returns `skipped_official_notice`, row untouched |
| GIZ hydration and coverage (`giz_document_hydration`) | notice not loaded; not flipped to `access_required`, not downloaded |
| `persist_document_descriptors` | never matched as an attachment |
| Explorer document-status summary and filters, sync diagnostics, legacy analysis input, `GET /tenders/{id}/documents` | ignore the row |
| Tender Details attachment counts, `omitted_unknown_count`, acquisition state | ignore the row |

### Download endpoint

`GET /tenders/documents/{id}/download` on an OFFICIAL_NOTICE row returns **404** with "This is the official notice text, not a downloadable file. Open the notice at its source." (after the tender-access check). Reasons: there is no file, so 404 matches the existing "no stored file" answer; 409 would imply the caller can resolve a conflict; a redirect would send the app's authenticated blob request to another origin, where it fails on CORS and hands the source a customer request. The UI never offers a download for the row.

## Presentation

* Tender Details, "Official source documents": `documents.data.official_notice` (`document_id`, `source_url`, `character_count`, `created_at`) is a separate field from `items` and every count. The UI shows an "Official notice text" row (en/ru/uz/ar) with an "Open at source" link (`safeSourceUrl`) and no download button. When it is the only document the section is `AVAILABLE` rather than `EMPTY`. The details read model still uses the same number of SQL statements (the notice is read by the existing counts query).
* Pack candidate: `display_name = "Official notice text"`, `role = OFFICIAL_NOTICE`, `file_type = text/plain`, `source_url` = tender URL, `page_count_known = false`; sealing sets `locator_type = PARAGRAPH`. The pursuit pages show the role label localized.

## Backfill

```
python scripts/backfill_official_notices.py                       # report only
python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
   [--source world_bank] [--include-closed] [--batch-size 200] [--json]
```

Open tenders by default; one transaction per batch; the same function as refresh, so re-runs are no-ops. Reports, per source: tenders, substantive notices, created, updated, unchanged, below threshold or empty, failed, and documents present afterwards.

## Verification

* `test_d1_03_official_notice.py`: 22 tests. Normalization determinism (entities, lists, tables, whitespace, the real connector's `clean_notice_html`), header composition with missing fields and date-only deadlines, threshold on every source, migration up/down/drift/uniqueness, refresh create/update/no-op/repair with statement-log and `xmin` proofs, set-wise statement count independent of batch size, concurrent writers, attachment-at-tender-URL, passive reads and pursuit commands, presentation, download refusal, ADB worker skip, tenant markers, World Bank project/leadership row digests, backfill idempotence and scope, pack candidate → seal → mocked-provider run → notice amended → sealed copy unchanged and `inputs_changed` true → FK restrict.
* Regression (Linux/WSL, `PYTHONUTF8=1`, disposable databases): W2–W4 17 passed; W5–W8 13; S13 on-demand attachments 8; source-connector gate 198 passed, 1 skipped; security group 127 passed (including `test_release_reads`, whose per-request statement budget caught an extra query in the first version of the details read model). Whole backend suite (`test_*.py`): 858 passed, 1 skipped (missing local storage fixture), 10 errors in `test_s10_5_communications.py`, which need a release-gate loopback PostgreSQL env var and error identically on the untouched D1-01 checkout.
* Frontend: `tsc --noEmit`, `audit:literals`, and the localization/project-context node tests pass.
* Existing tests that pinned the old migration head, the version-file count (40 → 41) or "the head's parent is W8" were updated; the P0 migration test now runs its drift check at the repository head.
* `test_historical_migrations_are_untouched` hashes migration bytes and fails in a CRLF (Windows `autocrlf`) checkout run from WSL; run against LF files it passes. Unrelated to this change.

## Decisions and risks

* Migration head moves; any other branch that adds a migration on `20261002_0001_p0_extraction_trust_gate` needs a merge revision.
* Notice text changes (including a normalization change) change the candidate hash of unsealed reviews and mark runs sealed from the old text as stale, by design.
* The stored deadline is UTC because connectors attach UTC to the source's local wall-clock time; the notice repeats that stored value and does not correct it.
* Tenders whose `description` is short or empty (in the local data: every UzEx row and most ADB/EBRD/GIZ rows) get no document; nothing is synthesized for them.
