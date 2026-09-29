# D1-01 pursuit analyzer reliability

Scope: `backend/app/core/agents/pursuit_analyzer.py` (`_extract_chunk_sync`, `analyze_pack_items`), the worker's failure mapping and the run's `model_name` in `backend/app/services/pursuit_analysis.py`. Prompt text, response schema, quote/provenance verification, quality-state rules, W4–W8 semantics, the no-AI-pricing boundary and passive GETs are unchanged.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_PURSUIT_MODEL` | `gemini-3.7-flash` | Primary model. Exported as `pursuit_analyzer.MODEL_NAME`, which is also the value stored on a run when it is queued. |
| `GEMINI_PURSUIT_FALLBACK_MODELS` | `gemini-3.8-flash,gemini-3.6-flash` | Ordered fallbacks, used per chunk only after the primary has exhausted its single retry. Empty disables them. |
| `GEMINI_PURSUIT_MAX_OUTPUT_TOKENS` | `32768` | `max_output_tokens` on every provider call. |
| `GEMINI_PURSUIT_TIMEOUT_SECONDS` | `90` | Per-request read timeout (connecting is capped at 10 s). |
| `PURSUIT_ANALYSIS_CHUNK_BUDGET_SECONDS` | `240` | Per-chunk budget: no new attempt starts if elapsed + backoff + timeout would exceed it. |
| `PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS` | `480` | Per-run budget: once spent, chunks not yet started are not started and the run fails. |
| `PURSUIT_ANALYSIS_CHUNK_CONCURRENCY` | `3` | Chunks extracted concurrently per run. |

The API and the `worker_pursuit_analysis` service both read these through `env_file: .env`; no compose change is required. Values are read at import, like the other extractors.

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
- The `pursuit_analysis` Celery worker runs with `--concurrency=1`, so a run occupying its worker for up to 12 minutes delays queued runs behind it.

## Concurrency

Chunks run in `asyncio.to_thread` under a semaphore. Results are merged strictly in item/chunk order, so de-duplication (first occurrence wins), counters and persisted order do not depend on completion order. After the first chunk failure no new provider call is started; the raised exception is that of the earliest failed chunk, and it is the original exception type (not an `ExceptionGroup`).

## Diagnostics (count-only)

Added to `extraction_diagnostics` on success: `model_name` (accepted models, primary first, comma-joined; the worker copies it to `run.model_name`), `analysis_models`, `chunk_count`, `attempt_count`, `retry_count`, `fallback_chunk_count`, `chunk_concurrency`, `max_output_tokens`, `request_timeout_seconds`, `chunk_budget_seconds`, `run_budget_seconds`, and per-chunk `chunks[]` with `item_index`, `chunk_index`, `model_name`, `attempts`, `retry_count`, `latency_ms`, `failure_classes` (exception class names, with the HTTP status for provider errors) and token counts when the provider reports them. No source text, model output, or exception message is logged or stored. Each failed attempt is logged as `pursuit_analysis_chunk_attempt_failed model=… attempt=… error=<class>`.

## Verification

`backend/test_d1_01_analyzer_reliability.py` mocks the client for retry-once, double failure, timeout, fallback order, cap/timeout propagation (including through the real SDK request path), the chunk budget (a fake clock proves no attempt after the first starts past the budget), the run budget, 429/503/504 backoff, 401/402/403, concurrency ordering, de-duplication and diagnostics. `test_w4_pursuit_analysis.py` additionally asserts, against a disposable database, that a run records the model that produced its accepted output and that `PROVIDER_ACCOUNT` and `RUN_BUDGET_EXCEEDED` failures leave quality `FAILED`, clear the lease, and preserve the prior successful run.
