# D1-01 pursuit analyzer reliability

Scope: `backend/app/core/agents/pursuit_analyzer.py` (`_extract_chunk_sync`, `analyze_pack_items`), the worker's failure mapping, the run's `model_name` and the persisted context origin in `backend/app/services/pursuit_analysis.py`, and the `worker_pursuit_analysis` concurrency in `docker-compose.yml`. Response schema, the verbatim-quote check (`_locate`), quality-state rules, W4–W8 semantics, the no-AI-pricing boundary and passive GETs are unchanged. Pipeline version: `pursuit_analysis_pipeline_d1_v3`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_PURSUIT_MODEL` | `gemini-3.1-pro-preview` | Primary model. Exported as `pursuit_analyzer.MODEL_NAME`, which is also the value stored on a run when it is queued. |
| `GEMINI_PURSUIT_FALLBACK_MODELS` | `gemini-3.8-flash,gemini-3.7-flash` | Ordered fallbacks, used per chunk only after the primary has exhausted its single retry. Empty disables them. |
| `GEMINI_PURSUIT_MAX_OUTPUT_TOKENS` | `32768` | `max_output_tokens` on every provider call. |
| `GEMINI_PURSUIT_TIMEOUT_SECONDS` | `90` | Per-request read timeout (connecting is capped at 10 s). |
| `PURSUIT_ANALYSIS_CHUNK_BUDGET_SECONDS` | `240` | Per-chunk budget: no new attempt starts if elapsed + backoff + timeout would exceed it. |
| `PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS` | `480` | Per-run budget: once spent, chunks not yet started are not started and the run fails. |
| `GEMINI_PURSUIT_MODEL_TIMEOUTS` | `gemini-3.1-pro-preview=150` | Per-model overrides of the request timeout, `model=seconds,model=seconds`. The chunk budget check uses the timeout of the model about to be tried. |
| `PURSUIT_ANALYSIS_CHUNK_CONCURRENCY` | `3` | Chunks extracted concurrently per run. |
| `PURSUIT_ANALYSIS_WORKER_CONCURRENCY` | `2` | Celery `--concurrency` of `worker_pursuit_analysis` (compose interpolation). |

The API and the `worker_pursuit_analysis` service read the analyzer variables through `env_file: .env`; `PURSUIT_ANALYSIS_WORKER_CONCURRENCY` is interpolated by compose from the shell or the project `.env`. Values are read at import, like the other extractors.

## Model recommendation (D1, 2026-09-29)

Rule set by the owner: primary = the flash model with golden 19/19 in >= 4/5 B4a runs AND long-RFP recall >= 75% against the gemini-3.1-pro-preview reference set (prefer gemini-3.8-flash if both qualify; tie-break by recall, then p90). If none qualifies, gemini-3.1-pro-preview is primary for this week with a 150 s per-model timeout and the flash models as fallbacks. Recall is applied as the median per-run recall; the union of runs is reported too.

| Arm (pipeline d1_v3) | Model | Golden 19/19 runs | Long-RFP recall median (union) | Qualifies |
| --- | --- | --- | --- | --- |
| A: source-window contexts, prompt p0_v2 (`model-bench-r3.md`) | gemini-3.8-flash | 0/5 | 41% (48%) | no |
| A | gemini-3.7-flash | 0/5 | 37% (39%) | no |
| B: A + two prompt instructions, prompt d1_v3 (`model-bench-r3b.md`) | gemini-3.8-flash | 5/5 | 37% (46%) | no |
| B | gemini-3.7-flash | 5/5 | 39% (44%) | no |

Outcome: no flash model qualifies. Implemented defaults: primary `gemini-3.1-pro-preview` with `GEMINI_PURSUIT_MODEL_TIMEOUTS=gemini-3.1-pro-preview=150`; fallbacks `gemini-3.8-flash,gemini-3.7-flash` (3.8 first per the owner's stated preference; it also had the higher union recall). `gemini-3.6-flash` was dropped from the chain: it was not re-benched after the first bench and was the slowest flash model there. Prompt arm B is kept (`PROMPT_VERSION = pursuit_analysis_d1_v3`): it took both flash models from 0/5 to 5/5 golden runs and roughly doubled verified B4a requirements without changing the verification rules.

With a 150 s primary timeout and the 240 s chunk budget, a primary timeout at 150 s leaves no room for a primary retry (150 + 150 > 240); that attempt is skipped and the first fallback (90 s) still fits (150 + 90 = 240). A malformed primary response before 90 s is still retried on the primary.

## Source context (pipeline d1_v3)

Owner decision: the verbatim quote remains the sole trust anchor and its check (`_locate`) is unchanged; a fact whose quote is not found is still rejected and is the only thing counted in `provenance_rejected_count`. Customer-visible `source_context` must always be exact source text.

| Model-supplied `source_context` | Result | `context_origin` |
| --- | --- | --- |
| absent | unchanged (no context) | `NONE` |
| found in the sealed text (`_normalized_contains`, i.e. equal up to whitespace, NFKC, apostrophe/dash and page-decoration normalization) | kept as supplied | `MODEL_VERBATIM` |
| not found | the fact is kept and its context is **replaced** by an exact window of the sealed text | `SOURCE_WINDOW` |
| not found, and the quote alone is longer than 800 characters | the context is dropped (`None`) | `NONE` |

The origin is persisted in each requirement's and position's `source_locator` JSON (`context_origin`) and is therefore returned read-only by the existing requirement/position API responses; no migration. Run diagnostics count `context_model_verbatim`, `context_source_window` and `context_none` over verified facts.

**Window algorithm** (`_source_window`, deterministic, operates on the item's sealed text and the verified quote offsets):

1. Scan whole lines backward from the line containing the quote start, at most 1,500 characters, for the nearest *anchor*: a list preamble (line ending with `:`) or a short section heading (<= 100 characters): a section number alone (`5.`, `3.2`, `A.`, `IV.`), a numbered heading not ending in `.`/`;`/`,` (`3.2 Eligibility`, but not the list sentence `2. The consultant shall …`), or an ALL-CAPS line starting with a letter (Unicode-aware). Page markers, running headers such as `1-25-2012 FINAL POSTED` and bare page numbers are not anchors.
2. Window start = that anchor line, else the start of the quote's paragraph (after the previous blank line). Window end = end of the quote's paragraph (before the next blank line).
3. Cap 800 characters: cut the tail after the quote first, then the head, always at a line break when one is in range, else at other whitespace, never inside the quote; strip outer whitespace. The result is `text[start:end]`, an exact substring containing the quote.

### Output cap

The largest successful historical response was about 18.5K characters (P0R attempt 2). At a pessimistic 2 characters per token (Cyrillic/Arabic analysis languages, JSON punctuation) that is about 9.3K tokens; 3x headroom is about 27.8K, rounded up to 32,768. The cap also has to cover thinking tokens, which count against `max_output_tokens` on thinking models, so a tighter value risks truncated JSON. It bounds the runaway outputs seen live (366K characters after about 345 s, malformed at the same character).

### Timeout

The pinned `google-genai==0.3.0` exposes no request timeout: `HttpOptions` is a `TypedDict` without one and `ApiClient._request_unauthorized` calls `requests` with no timeout. `_TimeoutApiClient` overrides only that method to pass `http_options["timeout"]` to `requests` as `(connect, read)` = `(min(10, timeout), timeout)`, and `_TimeoutClient` installs it. It is a socket timeout, so for a non-streaming call it is effectively the wait for the response, not a total wall-clock deadline. Remove the shim when the SDK pin moves to a release with `HttpOptions.timeout`.

## Retry, fallback, and provider error classes

Per chunk the plan is: primary, primary again, then each fallback once (four attempts with the default fallbacks).

| Condition | Behavior |
| --- | --- |
| Malformed JSON, schema `ValidationError`, empty response, timeout | Retried immediately (no backoff). |
| HTTP 429 / 503 / 504 (`google.genai.errors.APIError.code`) | Retried after a jittered 2–8 s backoff, within the chunk budget. |
| HTTP 401 / 402 / 403 | Never retried. Raised at once as `ProviderAccountError` (`code = "PROVIDER_ACCOUNT"`, status code only, no provider detail, no exception chain). An operator warning `pursuit_analysis_provider_account_error status=<code>` is logged: status code only, no key, no content. Other chunks stop starting. |
| Anything else (other 4xx/5xx, connection refused, …) | Raised on first occurrence exactly as before. |

Failure classification is unchanged for the retryable classes: after the last attempt the last exception is re-raised unchanged, so the worker's existing handling applies (`QUEUED` while attempts remain, otherwise `FAILED`; quality `FAILED`; lease cleared; a prior successful run untouched).

### Worker mapping

`classify_analysis_failure` in `services/pursuit_analysis.py` is the only change to the worker's failure path. Quality-state semantics are unchanged.

| Exception | `failure_stage` | `failure_reason` (customer-visible) | `extraction_diagnostics` |
| --- | --- | --- | --- |
| `ProviderAccountError` | `EXTRACTION` | "The analysis provider is temporarily unavailable. Plasma has been notified." | `failure_code: PROVIDER_ACCOUNT`, `error_type: ProviderAccountError` |
| `RunBudgetExceeded` | `EXTRACTION` | "The analysis time budget was exhausted before every document section could be processed" | `failure_code: RUN_BUDGET_EXCEEDED` |
| everything else | `EXTRACTION` | bounded exception text, as before | no `failure_code` key |

## Time budgets and worst-case time to failure

Notation: timeout `T = 90 s`, connect cap `C = 10 s`, chunk budget `B = 240 s`, run budget `R = 480 s`, backoff `<= 8 s`.

- **One attempt** lasts at most `C + T = 100 s` (a slow connect followed by a full read wait).
- **One chunk.** An attempt after the first starts only if `elapsed + backoff + T <= B`, so the last attempt starts at `<= 150 s` and the chunk ends at `<= 150 + 100 = 250 s`. The first attempt always runs.
  - All-timeouts case: attempts run 0–90 s and 90–180 s; a third would end at 270 s > 240 s and is not started, so the chunk fails at about **180 s** (at most 200 s with slow connects).
  - Provider 503 storm: each backoff (2–8 s) counts against the budget, so a chunk gives up as soon as the next attempt cannot finish inside 240 s.
  - HTTP 401/402/403: fails immediately.
- **One run.** No chunk starts once `R = 480 s` has elapsed, but a chunk that started just before that keeps its own budget, so a run fails after at most `480 + 250 = 730 s` (about 12 minutes). A one-chunk document (up to 100,000 characters) is bounded by the chunk budget alone: at most 250 s.
- **Across worker retries.** `max_attempts` is 3; after a failed attempt the run is requeued with a 30 s delay and the dispatch sweep runs every 10 s, so a run that keeps failing at the ceiling reaches terminal `FAILED` after about `3 x 730 + 2 x (30..40) = 2,270 s` (about 38 minutes). The typical all-timeout single-chunk failure is about `3 x 200 + 80 = 680 s` (about 11 minutes).
- The `pursuit_analysis` Celery worker now runs with `--concurrency=${PURSUIT_ANALYSIS_WORKER_CONCURRENCY:-2}`, so one slow run no longer blocks every queued run. With chunk concurrency 3 that is up to 6 simultaneous provider calls per worker container.
- With per-model timeouts the bound is unchanged: an attempt starts only if `elapsed + backoff + T_model <= B`, so a chunk still ends by `B + C = 250 s`. A skipped attempt (for example a 150 s primary retry after 150 s) does not stop a later model with a shorter timeout from being tried.

### Worker concurrency safety

A run is claimed in `process_analysis_run` with `SELECT … FOR UPDATE` on its row; a worker that finds the run `RUNNING` with an unexpired lease owned by another worker returns without doing anything, and `COMPLETED`/`FAILED` runs are no-ops. Each Celery task has a distinct `worker_id` (`hostname:task-id`) and its own heartbeat that renews only its own lease. The dispatch sweep uses `FOR UPDATE SKIP LOCKED`. `test_w4_pursuit_analysis.py` proves both properties against a disposable database: two workers process two different runs concurrently (peak 2 in-flight analyses, both `COMPLETED` with `attempt_count` 1), and two workers racing for one run execute the analyzer exactly once.

## Concurrency

Chunks run in `asyncio.to_thread` under a semaphore. Results are merged strictly in item/chunk order, so de-duplication (first occurrence wins), counters and persisted order do not depend on completion order. After the first chunk failure no new provider call is started; the raised exception is that of the earliest failed chunk, and it is the original exception type (not an `ExceptionGroup`).

## Diagnostics (count-only)

Added to `extraction_diagnostics` on success: `model_name` (accepted models, primary first, comma-joined; the worker copies it to `run.model_name`), `analysis_models`, `chunk_count`, `attempt_count`, `retry_count`, `fallback_chunk_count`, `chunk_concurrency`, `max_output_tokens`, `request_timeout_seconds`, `chunk_budget_seconds`, `run_budget_seconds`, and per-chunk `chunks[]` with `item_index`, `chunk_index`, `model_name`, `attempts`, `retry_count`, `latency_ms`, `failure_classes` (exception class names, with the HTTP status for provider errors) and token counts when the provider reports them. No source text, model output, or exception message is logged or stored. Each failed attempt is logged as `pursuit_analysis_chunk_attempt_failed model=… attempt=… error=<class>`.

## Verification

`backend/test_d1_01_analyzer_reliability.py` mocks the client for retry-once, double failure, timeout, fallback order, cap/timeout propagation (including through the real SDK request path), the chunk budget (a fake clock proves no attempt after the first starts past the budget), the run budget, 429/503/504 backoff, 401/402/403, concurrency ordering, de-duplication and diagnostics. `test_w4_pursuit_analysis.py` additionally asserts, against a disposable database, that a run records the model that produced its accepted output and that `PROVIDER_ACCOUNT` and `RUN_BUDGET_EXCEEDED` failures leave quality `FAILED`, clear the lease, and preserve the prior successful run.
