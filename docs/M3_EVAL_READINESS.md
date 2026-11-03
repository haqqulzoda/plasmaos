# M3: Uzbek and Russian evaluation readiness

Branch `cloud/m3-eval-readiness`, based on `pilot/deploy-5-1-hotfix` at `8fa4bd4`. Written
2026-11-03. No model was called and no production system was touched for this work.

Contents:

1. What the repository measures today, and what it does not
2. The evaluation harness and the draft labelled set
3. Bias checks: definitions and how each is measured
4. What was run for this document, with exact results
5. Open decisions

## 1. What is measured today, and what is not

### The analysis pipeline

| Stage | Code | What it does |
| --- | --- | --- |
| Document text | `backend/app/core/parser.py` | Native PDF text with PyMuPDF. A page with fewer than 50 native characters goes to OCR: Tesseract with `uzb+rus+eng`, at most `TENDER_OCR_MAX_PAGES` pages (default 2), and Gemini OCR when Tesseract is unavailable. |
| Pursuit analysis (W4) | `backend/app/core/agents/pursuit_analyzer.py` | Gemini extracts corporate requirements and positions as structured facts. Every quote is verified verbatim against the sealed text (with layout normalization) or rejected. Packs of at most 60,000 characters take the short route with two passes; longer packs take the long route. |
| Compliance analysis | `backend/app/core/agents/requirement_extractor.py` | Gemini extracts requirements as DQ / NICE_TO_HAVE / COMPLIANT with a quote of at most 15 words. Evidence is validated against the cited page. A keyword classifier (`classify_requirement_scope`) then decides whether each requirement can block a bid. |
| Analysis language | `backend/app/core/analysis_languages.py` | Sets the language of generated fields (English, Uzbek Latin, Russian; Arabic gated). It is independent of the document's language. The product does not record the source document's language anywhere. |

### Existing benchmarks

| Benchmark | Where | Inputs | What it measures |
| --- | --- | --- | --- |
| D1 model bench | `backend/scripts/bench_pursuit_models.py`, `docs/audits/d1/model-bench*.md` | B4a communications-consultant RFP (English, 8 pages); two World Bank REOIs for Mongolia (`OP00464527`, `OP00465103`, English); one long GIZ RFP from the local database | Success and failure classes, latency, retries, tokens; coverage of 19 golden B4a obligations by English keyword anchors; long-RFP recall against the union of a stronger model's runs (not against human labels). Analysis language is always `en`. |
| D2 analysis quality | `docs/audits/d2/analysis-quality-benchmark.md` | B4a and Mongolia REOI `OP00468882` (English) | Run-to-run stability over 5 runs: golden 19/19, 5 core REOI items, duplicates, spread, provider time. |
| P0 golden fixture | `docs/audits/p0/real-rfp-golden-benchmark.md`, `backend/test_p0_real_rfp_extraction.py` | B4a text fixture (English) | Schema, provenance and persistence with fixed, schema-valid facts. No live model. |
| P0R live coverage | `docs/audits/p0r/live-semantic-coverage.md` | B4a (English) | One live run checked against the 19 obligations. |
| S8.2 language QA | `backend/scripts/qa_s8_2_live_model_languages.py` | One synthetic two-sentence English document | Whether generated fields come back in en / uz / ru / ar, with valid schema and verbatim evidence. Output language only. |

### Measured today

* Extraction reliability, latency and run-to-run stability on English documents.
* Coverage of 19 hand-defined obligations in one English RFP (keyword anchors, not human
  adjudication of each run).
* Long-document recall relative to a stronger model, not relative to ground truth.
* Whether generated text follows the selected analysis language, on one synthetic
  English input.

### Not measured (before this branch)

* **Any Russian or Uzbek source document.** Every input to every extraction benchmark is
  English. Russian and Uzbek appear only as output languages.
* **Human-labelled ground truth** beyond the 19 B4a obligations. No precision against
  labels anywhere.
* **Quality by document language, script, source, country or procurement type.** Nothing
  is broken down by these, and the product does not store document language, so it cannot
  be monitored in production either.
* **Scanned documents and OCR.** OCR quality, the 2-page OCR cap and the Tesseract
  language set are untested for extraction quality. The image installs `tesseract-ocr-uzb`
  (Uzbek Latin) and `tesseract-ocr-rus`, but no Uzbek Cyrillic model (`uzb_cyrl`).
* **The keyword scope classifier's language coverage.** Measured for the first time below.
* **Fairness of downstream matching** (gap analysis, candidate retrieval) by firm size or
  firm country.

## 2. Harness and labelled set

* Harness: `backend/evaluation/` (usage in `backend/evaluation/README.md`), CLI
  `backend/scripts/eval_requirement_extraction.py`, tests
  `backend/test_eval_requirement_extraction.py`.
  * Offline mode scores stored outputs.
  * Live mode runs the pursuit or compliance pipeline with the operator's own key, behind
    an explicit confirmation flag.
  * Matching reuses the D1 rule: span overlap of at least 50% of the shorter span.
* Labelled set: `backend/evaluation/datasets/req_eval_v0_draft/` (README there).
  * 35 public notices: 12 English and 12 Russian World Bank notices, and 11 Uzbek UzEx
    e-tender lots.
  * 465 required and 37 optional hand-labelled items.
  * Sources and SHA-256s are recorded per document.
  * **Status: draft until a procurement expert has reviewed it.**

## 3. Bias checks

Each check names the question, the metric, how it is computed, and whether the v0 set
can answer it. All extraction metrics come from `score`, which reports per group: recall,
precision, F1, mandatory agreement, unlocated-quote rate, document-bootstrap 95% intervals,
the recall gap to a reference group with its interval, and an `insufficient` flag (fewer
than 10 documents or 30 required items).

| # | Question | Metric and method | Reference | v0 status |
| --- | --- | --- | --- | --- |
| B1 | Does extraction quality differ by **document language**? | `score` grouping `language`: recall, precision, F1, mandatory agreement per language; recall gap and 95% CI from a joint document bootstrap. | English | Ready; needs one live run per pipeline. Language is confounded with source (see B9). |
| B2 | Does it differ by **script** (Latin vs Cyrillic)? | `score` grouping `script`. Recall by the script of each gold quote; precision by the script of each predicted quote. To separate script from language, compare Uzbek Latin with Uzbek Cyrillic items only (same language, same source). | Latin | Ready. Within Uzbek, script is confounded with the UzEx standard sentences (mostly Cyrillic). |
| B3 | Does it differ for **scanned vs digital** documents? | Same notices in two forms: the digital text, and the text the product's parser produces from a scanned or image-only PDF. Report OCR character error rate against the digital text, the share of pages that got any text (the 2-page OCR cap), and extraction recall on parser text vs digital text against the same labels. `format` grouping in `score`. | Digital | **Not measurable with v0**: 0 scanned documents. Needs a scanned subset, e.g. UzEx lots with scanned attachments, run through `parser.py`. |
| B4 | Does it differ by **firm size**? | Extraction reads tender documents, so firm size does not enter it directly. Two places it can: (a) proxy on the document side, recall by contract `value_band` and `procurement_type`; (b) downstream, counterfactual pairs of firm profiles that differ only in size (staff count, turnover band) against the same extracted requirements. The metric is the share of gap verdicts that flip where no requirement mentions size. It should be 0. Where a requirement states a threshold, the verdict must follow the threshold. | Largest band | (a) partially ready: value band is unknown for all v0 documents. (b) defined, not implemented. |
| B5 | Does it differ by **country**? | (a) Issuer country: `score` grouping `country`. (b) Bidder country in matching: counterfactual firm profiles that differ only in country. The flip rate should be 0 unless a requirement names nationality, local registration or local presence (several v0 items do, e.g. staff based in Uzbekistan, Belarus references). | UZ | (a) ready, but every country except UZ and TJ has fewer than 10 documents (`insufficient`). (b) defined, not implemented. |
| B6 | Does deterministic **post-processing** treat languages equally? | `scope-check`: share of gold mandatory bid-stage requirements that `classify_requirement_scope` marks bid-blocking, per language and script, with a document bootstrap. Plus keyword-list size per language. No model involved. | English | **Measured** (section 4). |
| B7 | Does **quote verification** reject more in some languages? | `score` unlocated-quote rate per language and script on live outputs. Offline stress test: rewrite apostrophe-like characters in gold quotes as ASCII `'` and run the analyzer's `_locate`. | English | Offline stress test run (section 4); live part needs a run. |
| B8 | Does the **analysis language** change extraction? | Same documents, two live runs: `--analysis-language document` and `--analysis-language en`. Compare recall per language. | `document` | Ready; needs two live runs. |
| B9 | Is a language gap really a **source or format** gap? | Compare groupings `source` and `procurement_type` alongside `language`. Extend the set with Russian UzEx lots and English or Uzbek prose notices so that language and source vary independently. | — | Partly: v0 has Russian only from the World Bank and Uzbek only from UzEx. |

Reporting rule: report every group, but claim a difference only where both groups have
sufficient data and the 95% gap interval excludes 0. Results on the draft set are
agreement with draft labels, not validated accuracy.

## 4. What was run for this document

Python 3.13.18 in a fresh virtual environment with `backend/requirements-test.txt`;
Node 22; no Postgres or Redis running. Bootstrap seed `20261109`, 2,000 resamples.

1. `python scripts/eval_requirement_extraction.py validate`: 35 documents (en 12, ru 12,
   uz 11); required items en 125, ru 133, uz 207; optional en 19, ru 16, uz 2; problems 0.
2. `python -m pytest -q test_eval_requirement_extraction.py`: 17 passed.
   `python scripts/eval_requirement_extraction.py build-sources` against the live public
   APIs: 35 of 35 stored texts unchanged (exit 0). An earlier attempt exited 1; its
   output was not kept, and the rerun matched all 35.
3. `score` on an oracle run (gold quotes fed back as outputs): 100% on every metric. This
   only checks the harness. It is not a measurement of any pipeline.
4. **No live run was made.** No extraction accuracy for any pipeline, model or language
   was measured. The first live run is the operator's step (`backend/evaluation/README.md`).
5. `python scripts/eval_requirement_extraction.py scope-check` (B6). Simulated correct
   extractions of gold mandatory requirements of types ELIGIBILITY, QUALIFICATION,
   FINANCIAL, DOCUMENT and SUBMISSION, passed through the product's
   `classify_requirement_scope`:

   | Document language | Docs | Items | Marked bid-blocking | Share | 95% CI | Needs review |
   | --- | ---: | ---: | ---: | ---: | --- | ---: |
   | English | 12 | 91 | 60 | 65.9% | 49.0% to 83.1% | 20 |
   | Russian | 12 | 107 | 57 | 53.3% | 38.8% to 65.8% | 49 |
   | Uzbek | 11 | 173 | 14 | 8.1% | 3.1% to 14.7% | 64 |

   * 95 of the 173 Uzbek items were classified `post_award_obligation`.
   * In all 95 the only post-award keyword present in the classifier's 300-character
     context was the Uzbek Cyrillic `шартнома` ("contract"), from `_POST_AWARD_TERMS`.
     Only 27 of the 173 quotes contain the word themselves. The rest pick it up from
     neighbouring standard qualification lines such as "legal right to conclude a
     contract", which are bid-stage eligibility conditions.
   * Within Uzbek, the share marked bid-blocking was 3 of 69 standard Cyrillic sentences,
     0 of 12 standard Latin sentences, 2 of 38 lot-specific Cyrillic items and 9 of 54
     lot-specific Latin items.
   * Keyword lists: 182 English terms, 34 Russian, 6 Uzbek Latin and 1 Uzbek Cyrillic. The
     Uzbek words for exclusion used in these lots (`chetlatiladi`, `diskvalifikatsiya`,
     `четлаштирилади`) are not in the rejection list.

   Limits: the labels are a draft; the simulation uses headline `-` and the whole notice
   as one page; Uzbek is confounded with the UzEx source. Even so, the mechanism above is
   in product code and does not depend on any model.
6. B7 offline stress test.
   * Every gold quote containing an apostrophe-like character was rewritten with ASCII `'`
     and passed to `pursuit_analyzer._locate`. All were still located: Uzbek 61 of 61,
     English 13 of 13.
   * The sources in v0 use `‘ ’ '`; the Uzbek modifier letter `ʼ` (U+02BC) occurs once,
     outside any gold quote, and `ʻ` (U+02BB) never.
   * The analyzer's normalization does not fold `ʻ`, `ʼ` or `` ` ``. That remains an
     untested risk for sources that use them.
7. Repository checks:
   * Backend suite (`cd backend && python -m pytest -q`, with the CI workflow's synthetic
     environment variables), before this branch's changes: 1164 passed, 68 failed,
     10 errors, 1 skipped, 100 subtests passed. After them: 1181 passed (the 17 new tests
     added), with the same 68 failures and 10 errors. In the tracebacks, 77 errors are a refused connection to Postgres on
     127.0.0.1:5432. The remaining ones are in `test_shared_redis_replay_rate_and_processing_leases`:
     a refused connection to Redis on 6379 and the auth bridge's resulting HTTP 503.
     Neither service ran here; CI provides both.
   * Frontend (`cd frontend`): `npm ci`, `npm run typecheck` and `npm run lint` exited 0;
     `node --no-warnings --experimental-strip-types --test tests/*.test.mjs` gave 422
     passed, 0 failed.

## 5. Open decisions

* **Licence.** The repository has no licence file. Choosing one (or none) is a founder
  decision.
* **Rights to the stored notice texts.** The reuse terms of World Bank and UzEx notices
  have not been confirmed. Either confirm them or switch the set to fetch-on-demand (the
  builder already exists).
* **Expert review.** Name the procurement expert who reviews the Russian and Uzbek labels
  (checklist in the dataset README).
* **Live run budget.** One run of the full set per pipeline; B8 needs a second pursuit run.
* **Scope classifier.** Whether to change `classify_requirement_scope` for Uzbek and
  Russian, e.g. the `шартнома` post-award trigger and the missing exclusion words. That is
  a product change, outside this branch.
