# Cost per use: AI cost of an analysis, an EOI and a prospect preview (M2 evidence)

**Data: local runs only.** Every provider call of the local AI cost ledger (`ai_call_costs`) of the disposable
clone `plasma_s05b4b_s1int_local`, **2026-10-11 14:18 UTC to 2026-10-13 07:06 UTC**: 130 calls (69 analysis
chunks, 61 EOI relevance notes), all made by the S1 prospect-preview seed and its tests against real World Bank
REOIs with Gemini. These are demo runs, not customer use: no production data, small n, one model (every call went
to `gemini-3.8-flash`; no fallback and no LONG-route call happened).

**Prices: the official table only.** Each call is re-priced from its own token counts with the release price
table (`backend/app/core/ai_pricing.py`, version `gemini-api-pricing-2026-10-09`, taken from
https://ai.google.dev/gemini-api/docs/pricing, "Last updated 2026-10-09 UTC"): `gemini-3.8-flash` USD 0.75 per
million input tokens and 3.75 per million output tokens, thinking billed as output. The stored estimates agree
(the same Flash price was in force for every call). Script: a read-only query of `ai_call_costs` joined to the
analysis runs (route from `extraction_diagnostics`), re-priced with `app.core.ai_pricing`.

## Per analysis run

One run = every chunk call of one `pursuit_analysis_runs` row (the SHORT route makes two independent passes, so
at least two calls; failed attempts and retries included).

| Model | Route | n | Median USD | p90 USD | Min | Max |
| --- | --- | --- | --- | --- | --- | --- |
| gemini-3.8-flash | SHORT (official notice ≤ the LONG threshold) | 33 | **0.0338** | **0.0758** | 0.0147 | 0.0783 |
| gemini-3.1-pro-preview | LONG | 0 | — | — | — | — |

Notices in the sample: 3,400 to 16,900 characters (REOIs). No local run took the LONG route (pro model at USD
2.00 / 12.00 per million): its cost per run is **not measured**; expect it to be several times the SHORT figure.

## Per EOI

One EOI = the relevance-note calls of one EOI draft (one note per selected reference; the DOCX and PDF are built
without AI).

| Model | n | Median USD | p90 USD | Min | Max |
| --- | --- | --- | --- | --- | --- |
| gemini-3.8-flash | 17 | **0.0146** | **0.0198** | 0.0034 | 0.0199 |

## Per prospect preview

| Unit | n | Median USD | p90 USD | Min | Max |
| --- | --- | --- | --- | --- | --- |
| One preview pursuit (its analysis + its EOI notes) | 33 | **0.0405** | **0.0782** | 0.0190 | 0.0926 |
| One best-of-N command (`--candidates 3`; every analysed candidate counts) | 6 | **0.176** | 0.212 | 0.102 | 0.212 |
| One pinned or single-candidate command | 8 | 0.031 | 0.067 | 0.022 | 0.067 |

Best-of-N commands: the five S1-7 runs (USD 0.1019, 0.1550, 0.1757, 0.1765, 0.2123) and the S1-8 Kreston replay run
(0.2115; four analyses: one refused short open notice and three replay candidates). Single runs: the S1-8 runs that
stopped at the one open notice (0.0238-0.0311) and the four pinned replays (0.0223-0.0669).

## The 2027-01-01 Flash price change

The official page lists `gemini-3.8-flash` (and `3.6-flash`) at USD 0.75 / 3.75 **through 2026-12-31** and **1.50 /
7.50 from 2027-01-01**. Every call above was Flash, so every figure **doubles**:

| Unit | Median now → 2027 | p90 now → 2027 |
| --- | --- | --- |
| Analysis run (SHORT) | 0.0338 → **0.0676** | 0.0758 → **0.1516** |
| EOI | 0.0146 → **0.0292** | 0.0198 → **0.0395** |
| Preview pursuit | 0.0405 → **0.0811** | 0.0782 → **0.1563** |
| Best-of-3 preview command | 0.176 → **0.35** | 0.212 → **0.42** |

The application keeps estimating at the old price until `AI_PRICE_TABLE_JSON` is set (Deploy 4 runbook, step 16);
rows already written keep their estimate and `price_table_version`.

## Tokens behind the figures

| Call kind | Calls | Input tokens | Output tokens | Thinking tokens |
| --- | --- | --- | --- | --- |
| Analysis chunks | 69 | 171,235 | 235,184 | 94,945 |
| EOI relevance notes | 61 | 25,355 | 3,168 | 51,964 |

Output and thinking dominate the cost (output is priced five times input): an analysis spends about 1.9 output +
thinking tokens per input token; an EOI note mostly thinks.

## Limits

- Local demo runs over two days; production use (other notices, long tender packs, the LONG route, fallbacks after
  provider errors) will differ. Re-run this query on production `ai_call_costs` after a few weeks of use.
- `gemini-3.7-flash` (a configured fallback) is not on the official price page; its calls would show no estimate.
  None occurred here.
- Costs are provider list prices; no taxes, free tier or discounts.
