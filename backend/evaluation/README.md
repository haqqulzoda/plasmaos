# Requirement-extraction evaluation (English, Russian, Uzbek)

This harness scores how well the extraction pipelines find tender requirements, by
document language, script and other attributes, against a hand-labelled set of public
tender notices. It has two modes:

* **Offline** (default): scores outputs that are already stored on disk. No network, no
  API key, no database. Safe in CI.
* **Live**: runs the real pipeline on the labelled set and stores its outputs. It calls
  the paid model provider. Only an operator runs it, with their own key. Tests and CI
  never run it.

The labelled set is a **draft**. A procurement expert has not reviewed it. Any number the
harness produces against it describes agreement with draft labels, not validated
accuracy. See [`datasets/req_eval_v0_draft/README.md`](datasets/req_eval_v0_draft/README.md).

Bias checks and their definitions: [`docs/M3_EVAL_READINESS.md`](../../docs/M3_EVAL_READINESS.md).

## Commands

Run from `backend/` with the backend test dependencies installed
(`pip install -r requirements-test.txt`).

```bash
python scripts/eval_requirement_extraction.py validate
```

Checks that every gold quote is found in its source text and that every source text
matches the SHA-256 in the manifest. Prints counts by language and script. Exit 1 on
any problem.

```bash
python scripts/eval_requirement_extraction.py score --outputs <dir> --label <name> --out ../.private-storage/eval_reports
```

Scores stored outputs (one `<doc_id>.json` per document; formats below). Prints a
markdown report and, with `--out`, writes JSON and markdown. `.private-storage/` is
gitignored. Documents without an output file are left out of the scores and counted.

```bash
python scripts/eval_requirement_extraction.py scope-check --out ../.private-storage/eval_reports
```

Offline language check of the compliance extractor's keyword-based scope classifier
(`classify_requirement_scope`). No model is called. See "Scope-classifier check" below.

```bash
python scripts/eval_requirement_extraction.py live --pipeline pursuit \
  --out ../.private-storage/eval_runs/pursuit-$(date +%Y%m%d) --confirm-live-provider-calls
```

Live mode. It refuses to start without `--confirm-live-provider-calls`, without a
Gemini key (taken from `GEMINI_API_KEY` in the shell, or from the app settings in the
root `.env`), or with `ENVIRONMENT=production`. Options:

* `--pipeline pursuit` runs `pursuit_analyzer.analyze_pack_items` (W4 pursuit
  analysis) with its configured routing, retries and fallbacks; `--pipeline compliance`
  runs `requirement_extractor.extract_requirements` plus evidence validation and scope
  classification.
* `--analysis-language document|en|ru|uz` sets the language of generated fields
  (default: the document's own language). Quotes are always source text.
* `--max-docs N`, `--only <doc_id> ...` and `--resume` limit or continue a run.
* It stops at the first HTTP 401/402/403 from the provider.

The full set is 35 documents. With `--pipeline pursuit`, each short document is one
analyzer run (two extraction passes by default). Check your provider budget first. Then
score the run:

```bash
python scripts/eval_requirement_extraction.py score --outputs ../.private-storage/eval_runs/pursuit-YYYYMMDD --label pursuit-YYYYMMDD
```

```bash
python scripts/eval_requirement_extraction.py build-sources
```

Refetches every public source, rebuilds its text with the same redactions and reports
`unchanged` or `CHANGED` against the stored SHA-256. It never overwrites stored texts,
because the labels were made against them. Uses the public network.

## Stored output formats

Each `<doc_id>.json` may be any of:

```json
{"doc_id": "en-wb-OP00477942", "pipeline": "pursuit", "model": "…",
 "items": [{"quote": "fluency in Kyrgyz and Russian", "obligation": "MANDATORY"}]}
```

* a list of pursuit-analyzer facts with `original_quote`, `kind`, `distinction` (or
  `{"fact": {...}}` wrappers);
* a list of compliance requirements with `exact_quote` and `category`
  (`DQ` → mandatory, `NICE_TO_HAVE` → not mandatory, `COMPLIANT` → informational).

`run.json` in the same directory is run metadata and is ignored by `score`.

## How matching works

* Quotes are located in the source text after normalization: Unicode NFKC, case
  folding, whitespace runs, and apostrophe, dash and quotation-mark variants (Uzbek
  Latin `o‘`/`g‘` appear as `‘ ’ ʻ ʼ ' \``). Wording and word order are never relaxed.
* A prediction matches a gold item when their spans overlap by at least 50% of the
  shorter span. This is the rule `scripts/bench_pursuit_models.py` already uses.
  Alternative quotes (the same requirement stated twice, e.g. in both Uzbek scripts)
  count as extra spans of one item.
* Assignment is one-to-one, greedy by overlap. A second prediction of an already
  matched item is a *duplicate*: reported, not counted against precision.
* A predicted quote that cannot be located is *unlocated*. It counts against precision
  and is reported as a provenance failure.
* *Optional* gold items (borderline statements) are not in the recall denominator. A
  prediction matching one is neither a hit nor a false positive.

Metrics: recall, precision, F1, agreement on "mandatory or not" for matched items
(only where the pipeline outputs an obligation), and the unlocated-quote rate.

Group comparisons use a document-level bootstrap (2,000 resamples, fixed seed). Every
group and its gap to the reference group is computed on the same resample. A group with
fewer than 10 documents or 30 required items is flagged `insufficient`. Do not use such
a group to claim or rule out a difference. A gap whose 95% interval includes 0 is not
evidence of a difference.

## Scope-classifier check

`classify_requirement_scope` runs after the compliance extractor and decides, using
keyword lists, whether a requirement can block a bid. The check takes every gold item
labelled `MANDATORY` with type ELIGIBILITY, QUALIFICATION, FINANCIAL, DOCUMENT or
SUBMISSION. It simulates a correct extraction: category `DQ`, evidence accepted, the
gold quote cut to the extractor's 15-word limit, headline `-`, and the whole notice as
page 1. It then records whether the classifier marks the requirement as bid-blocking
(`affects_bid_eligibility` and review status `accepted`). This isolates product code
from model quality. It also counts the keyword lists by language.

Limits: in production the headline is model-written in the analysis language, and page
blocks are usually shorter than a whole notice. Both can change the keyword context.

## Tests

```bash
python -m pytest -q test_eval_requirement_extraction.py
```

These tests are offline. Live mode is tested with the pipeline call replaced, so no
provider is contacted.
