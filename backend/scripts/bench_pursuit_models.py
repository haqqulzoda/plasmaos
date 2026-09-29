#!/usr/bin/env python3
"""D1-02 engineering tool: compare Gemini models on the real pursuit analyzer.

Runs ``pursuit_analyzer.analyze_pack_items`` (same prompt, response schema,
retry, quote/provenance verification) directly on text inputs. It creates no
analysis runs, packs, or any other database rows: the local database is read
with a read-only session, only on a loopback host, and only for these inputs:
the locally uploaded B4a private document's extracted text, two World Bank
notice descriptions, and one long compiled tender text.

The report and JSON are count-only. Source text, model output and exception
messages are never written to them; only counts, latencies, ids, hashes and
exception class names are. Two local files under ``.private-storage/d1_bench``
(gitignored) hold character offsets and, for human spot-checking, the quotes of
reference items a model missed. They never go into ``docs/``.

Fallbacks are switched off for the bench so every result belongs to exactly one
model. A failed run therefore means "the model exhausted its retry", which is
precisely when production would move to the next fallback model. The bench stops
at once if any call is rejected with HTTP 401/402/403 (account/billing/key).

Long-RFP recall: the union of verified requirement quote spans from the reference
model's successful runs is the reference set. A candidate item matches a
reference item when their character spans overlap by at least 50% of the shorter
span. Recall is reported per run and over the union of a model's runs, together
with "model-only" items (verified by the model but matching no reference item).

Usage (from ``backend/``, local stack only)::

    python scripts/bench_pursuit_models.py --preset r2          # the D1 re-run matrix
    python scripts/bench_pursuit_models.py --runs 3             # uniform matrix
    python scripts/bench_pursuit_models.py --runs 1 --inputs b4a_full --models gemini-3.7-flash
    python scripts/bench_pursuit_models.py --preset r2 --resume # continue an interrupted bench
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.agents import pursuit_analyzer as analyzer  # noqa: E402


REPO_ROOT = BACKEND_DIR.parent
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "communications_consultant_rfp.txt"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "audits" / "d1"
PRIVATE_DIR = REPO_ROOT / ".private-storage" / "d1_bench"  # gitignored; never published
DEFAULT_MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro-preview")
REFERENCE_MODEL = "gemini-3.1-pro-preview"  # quality reference only, never a selection candidate
INPUT_ORDER = ("b4a", "b4a_full", "reoi_1", "reoi_2", "long_rfp")
DEFAULT_INPUTS = ("b4a_full", "reoi_1", "reoi_2", "long_rfp")
GOLDEN_INPUTS = {"b4a", "b4a_full"}
B4A_SOURCE_SHA256 = "88d34d5bce1685088d18e104de0c8a5325924cd23d9c0a1cb1f48b4587cd4a3b"
# The D1 re-run matrix: candidates on every input, the reference model only on the long RFP.
PRESETS: dict[str, dict[str, dict[str, int]]] = {
    "r2": {
        "gemini-3.7-flash": {"b4a_full": 5, "reoi_1": 5, "reoi_2": 5, "long_rfp": 3},
        "gemini-3.8-flash": {"b4a_full": 5, "reoi_1": 5, "reoi_2": 5, "long_rfp": 3},
        "gemini-3.1-pro-preview": {"long_rfp": 3},
    },
    # D1 final: gemini-3.1-pro-preview verification on every input; its long-RFP runs are the new reference.
    "r4": {"gemini-3.1-pro-preview": {"b4a_full": 3, "reoi_1": 3, "reoi_2": 3, "long_rfp": 3}},
    # D1 v3 (source-window contexts): candidates only; the long-RFP reference is reused from r2.
    "r3": {
        "gemini-3.8-flash": {"b4a_full": 5, "reoi_1": 5, "reoi_2": 5, "long_rfp": 3},
        "gemini-3.7-flash": {"b4a_full": 5, "reoi_1": 5, "reoi_2": 5, "long_rfp": 3},
    },
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
CENTRAL_ASIA = ("Uzbekistan", "Kazakhstan", "Kyrgyz Republic", "Kyrgyzstan", "Tajikistan", "Turkmenistan")
LATER_STAGE_SCOPES = {"CONTRACT_EXECUTION", "POST_AWARD_OBLIGATION", "LATER_STAGE"}
# Failure classes the analyzer retries; only these can reach the fallback models in production.
RETRY_EXHAUSTED_CLASSES = {
    "SCHEMA_OUTPUT_FAILURE", "TIMEOUT", "EMPTY_RESPONSE", "PROVIDER_HTTP_429", "PROVIDER_HTTP_503", "PROVIDER_HTTP_504",
}
# Selection rule (reported, not applied): success ratio >= 8/9, p90 latency <= 150 s, golden 19/19.
SELECTION_MIN_SUCCESS_RATIO = 8 / 9
SELECTION_MAX_P90_SECONDS = 150.0
SPAN_MATCH_MIN_OVERLAP = 0.5


# --- golden semantic coverage (B4a inputs only) ---------------------------------
# The 19 obligations of docs/audits/p0r/live-semantic-coverage.md, expressed as
# anchor checks over *verified* facts. Distinction expectations are the ones
# already asserted by backend/test_p0_real_rfp_extraction.py. This is an
# automated proxy: wording may vary, so anchors are source words, not model words.


def _text(fact: analyzer.ExtractedFact) -> str:
    # source_context is deliberately excluded: a context (especially a SOURCE_WINDOW)
    # can span neighbouring list items the model never extracted as facts.
    parts = [fact.original_quote, fact.normalized_text]
    if fact.position is not None:
        parts.append(json.dumps(fact.position.model_dump(), ensure_ascii=False))
    return " ".join(parts).casefold()


def _any_fact(facts: list[analyzer.ExtractedFact], *needles: str, all_of: bool = True) -> bool:
    check = all if all_of else any
    return any(check(needle in _text(fact) for needle in needles) for fact in facts)


def _criteria(facts: list[analyzer.ExtractedFact]) -> list[analyzer.PositionQualification]:
    return [
        criterion
        for fact in facts
        if fact.position is not None
        for criterion in fact.position.qualification_criteria
    ]


def _criterion_distinction(facts: list[analyzer.ExtractedFact], needle: str, expected: str) -> bool:
    matching = [item for item in _criteria(facts) if needle in item.normalized_text.casefold()]
    return bool(matching) and all(item.distinction == expected for item in matching)


def _hourly_rate_is_customer_input(facts: list[analyzer.ExtractedFact]) -> bool:
    for fact in facts:
        if "hourly rate" not in _text(fact):
            continue
        generated = f"{fact.normalized_text} {fact.generated_interpretation or ''}"
        if re.search(r"[$€£]\s*\d|\d+(?:\.\d+)?\s*(?:usd|eur|per hour|/\s*h)", generated, re.IGNORECASE):
            continue  # a generated value crossed the no-pricing boundary
        return True
    return False


GOLDEN_OBLIGATIONS: tuple[tuple[str, Callable[[list[analyzer.ExtractedFact]], bool]], ...] = (
    ("Communications Consultant role",
     lambda f: any(x.position and "communications consultant" in x.position.title.casefold() for x in f)),
    ("5+ years marketing communications",
     lambda f: _any_fact(f, "5 years", "marketing communications")),
    ("2+ years web campaigns", lambda f: _any_fact(f, "2 years", "web-based")),
    ("Bachelor's degree required",
     lambda f: _criterion_distinction(f, "bachelor", "MANDATORY")
     or any(x.position and "bachelor" in (x.position.education_qualification or "").casefold() for x in f)),
    ("Journalism/interview/media", lambda f: _any_fact(f, "journalism")),
    ("Graphic design/layout", lambda f: _any_fact(f, "graphic", "layout")),
    ("Video capability preferred, not mandatory", lambda f: _criterion_distinction(f, "video", "PREFERRED")),
    ("Non-profit knowledge preferred", lambda f: _criterion_distinction(f, "non-profit", "PREFERRED")),
    ("Marketing automation/social media desired",
     lambda f: _criterion_distinction(f, "marketing automation", "DESIRED")),
    ("Resume/profile", lambda f: _any_fact(f, "resume", "corporate profile", all_of=False)),
    ("Work samples", lambda f: _any_fact(f, "samples")),
    ("Availability/hours", lambda f: _any_fact(f, "hours per month", "availab", all_of=False)),
    ("Hourly rate as customer-provided input", _hourly_rate_is_customer_input),
    ("Legal/financial disclosure", lambda f: _any_fact(f, "legal and financial", "bankruptc", all_of=False)),
    ("Insurance", lambda f: _any_fact(f, "insurance")),
    ("At least 3 references", lambda f: _any_fact(f, "reference", "three")),
    ("5-page maximum", lambda f: _any_fact(f, "5-page", "5 page", "five page", "five-page", all_of=False)),
    ("Printed and electronic submission", lambda f: _any_fact(f, "printed", "electronic")),
    ("Later-stage contract/Notice-to-Proceed obligations",
     lambda f: any(
         x.stage_scope.upper() in LATER_STAGE_SCOPES
         and any(n in _text(x) for n in ("notice to proceed", "execute a contract", "business days"))
         for x in f
     )),
)
assert len(GOLDEN_OBLIGATIONS) == 19


def golden_coverage(verified: list[analyzer.VerifiedFact]) -> tuple[int, list[str]]:
    facts = [item.fact for item in verified]
    missing = [label for label, check in GOLDEN_OBLIGATIONS if not check(facts)]
    return len(GOLDEN_OBLIGATIONS) - len(missing), missing


# --- long-RFP recall by quote-span overlap ----------------------------------------

Span = tuple[int, int]


def span_overlap_ratio(first: Span, second: Span) -> float:
    """Overlap as a fraction of the shorter span."""
    shorter = min(first[1] - first[0], second[1] - second[0])
    if shorter <= 0:
        return 0.0
    return max(0, min(first[1], second[1]) - max(first[0], second[0])) / shorter


def spans_match(first: Span, second: Span) -> bool:
    return span_overlap_ratio(first, second) >= SPAN_MATCH_MIN_OVERLAP


def distinct_spans(spans: list[Span]) -> list[Span]:
    """Greedy de-duplication: a span that matches an earlier kept span is the same item."""
    kept: list[Span] = []
    for span in spans:
        if not any(spans_match(span, existing) for existing in kept):
            kept.append(span)
    return kept


def _matched(reference: list[Span], candidate: list[Span]) -> int:
    return sum(1 for item in reference if any(spans_match(item, other) for other in candidate))


def _only(candidate: list[Span], reference: list[Span]) -> list[Span]:
    return [item for item in distinct_spans(candidate) if not any(spans_match(item, ref) for ref in reference)]


def recall_summary(
    spans_by_model: dict[str, dict[str, list[Span]]], reference_model: str = REFERENCE_MODEL
) -> dict[str, object] | None:
    """Recall of each non-reference model against the union of the reference model's runs."""
    reference_runs = list(spans_by_model.get(reference_model, {}).values())
    reference = distinct_spans([span for run in reference_runs for span in run])
    if not reference:
        return None
    models: dict[str, object] = {}
    for model, runs in spans_by_model.items():
        if model == reference_model or not runs:
            continue
        per_run = [_matched(reference, spans) / len(reference) for spans in runs.values()]
        union = [span for spans in runs.values() for span in spans]
        only_per_run = [len(_only(spans, reference)) for spans in runs.values()]
        models[model] = {
            "runs": len(runs),
            "recall_per_run": [round(value, 3) for value in per_run],
            "recall_median": round(statistics.median(per_run), 3),
            "recall_union": round(_matched(reference, union) / len(reference), 3),
            "model_only_per_run": only_per_run,
            "model_only_median": statistics.median(only_per_run),
            "model_only_union": len(_only(union, reference)),
        }
    return {
        "reference_model": reference_model, "reference_runs": len(reference_runs),
        "reference_items": len(reference),
        "reference_items_per_run": [len(distinct_spans(run)) for run in reference_runs],
        "span_match_min_overlap": SPAN_MATCH_MIN_OVERLAP, "models": models,
    }


def export_unmatched_reference_items(
    path: Path, text: str, spans_by_model: dict[str, dict[str, list[Span]]], reference_model: str = REFERENCE_MODEL
) -> int:
    """Local, private side-by-side list for human spot-checking. Contains source quotes."""
    reference = distinct_spans([span for run in spans_by_model.get(reference_model, {}).values() for span in run])
    candidates = {m: runs for m, runs in spans_by_model.items() if m != reference_model and runs}
    lines = [
        "# PRIVATE - unmatched reference items (do not publish or commit)", "",
        f"Reference: {reference_model} union of {len(spans_by_model.get(reference_model, {}))} run(s), {len(reference)} distinct items.",
        "Each row lists how many of a model's runs matched the reference item (>= 50% overlap of the shorter span)"
        " and the closest partially overlapping quote that model produced.", "",
    ]
    listed = 0
    for index, item in enumerate(reference, start=1):
        hits = {
            model: sum(1 for spans in runs.values() if any(spans_match(item, other) for other in spans))
            for model, runs in candidates.items()
        }
        if all(hits[model] == len(candidates[model]) for model in candidates):
            continue
        listed += 1
        lines += [f"## Reference item {index} (chars {item[0]}-{item[1]})", "", "> " + text[item[0]:item[1]].replace("\n", "\n> "), ""]
        for model, runs in candidates.items():
            closest = max(
                ((span_overlap_ratio(item, other), other) for spans in runs.values() for other in spans),
                default=(0.0, None), key=lambda pair: pair[0],
            )
            lines.append(f"- **{model}**: matched in {hits[model]}/{len(runs)} run(s); closest overlap {closest[0]:.0%}")
            if closest[1] is not None and closest[0] > 0 and hits[model] < len(runs):
                lines.append("  > " + text[closest[1][0]:closest[1][1]].replace("\n", "\n  > "))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return listed


# --- inputs -----------------------------------------------------------------


@dataclass(frozen=True)
class BenchInput:
    name: str
    description: str
    source_ref: str  # public identifier only, never text
    text: str
    page_count: int | None
    page_count_known: bool

    def public(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "source_ref": self.source_ref,
            "characters": len(self.text),
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            "page_markers": len(re.findall(r"\[\[PAGE \d+\]\]", self.text)),
            "chunks": len(analyzer._chunks(self.text)),
        }


def _guard_local_database() -> None:
    from app.core.config import settings

    if settings.POSTGRES_SERVER not in LOOPBACK_HOSTS:
        raise SystemExit("Refusing to read: POSTGRES_SERVER is not a loopback host (local stack only).")


async def _read_only_connection():
    import asyncpg

    from app.core.config import settings

    _guard_local_database()
    connection = await asyncpg.connect(
        user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER, port=settings.POSTGRES_PORT, database=settings.POSTGRES_DB,
    )
    await connection.execute("SET default_transaction_read_only = on")
    return connection


async def load_inputs(wanted: set[str], long_tender_id: UUID | None) -> list[BenchInput]:
    inputs: list[BenchInput] = []
    if "b4a" in wanted:
        text = FIXTURE.read_text(encoding="utf-8")
        markers = [int(value) for value in re.findall(r"\[\[PAGE (\d+)\]\]", text)]
        inputs.append(BenchInput(
            "b4a", "P0 benchmark B4a Communications Consultant RFP (condensed repo fixture)",
            f"fixture:{FIXTURE.name}", text, max(markers), True,
        ))
    if wanted & {"b4a_full", "reoi_1", "reoi_2", "long_rfp"}:
        connection = await _read_only_connection()
        try:
            if "b4a_full" in wanted:
                row = await connection.fetchrow(
                    """
                    SELECT r.extracted_text, r.extracted_sha256, r.page_count, r.page_count_status
                    FROM private_document_versions v
                    JOIN private_document_processing_results r ON r.document_version_id = v.id
                    WHERE v.sha256 = $1 AND r.extracted_text IS NOT NULL
                    ORDER BY r.created_at DESC LIMIT 1
                    """,
                    B4A_SOURCE_SHA256,
                )
                if row is None:
                    raise SystemExit("The uploaded B4a private document (source SHA-256 88d34d5b...) was not found locally.")
                text = row["extracted_text"]
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["extracted_sha256"]:
                    raise SystemExit("B4a extracted text does not match its recorded extracted_sha256.")
                inputs.append(BenchInput(
                    "b4a_full", "B4a Communications Consultant RFP, full extracted text of the local upload",
                    f"private_document_source_sha256:{B4A_SOURCE_SHA256[:8]}", text,
                    row["page_count"], row["page_count_status"] == "KNOWN",
                ))
            if wanted & {"reoi_1", "reoi_2"}:
                rows = await connection.fetch(
                    """
                    SELECT external_id, description FROM tenders
                    WHERE source_system = 'world_bank' AND notice_type = 'Request for Expression of Interest'
                      AND length(description) > 4000
                    ORDER BY (country = 'Mongolia') DESC, (country = ANY($1::text[])) DESC,
                             length(description) DESC, external_id
                    LIMIT 2
                    """,
                    list(CENTRAL_ASIA),
                )
                for name, row in zip(("reoi_1", "reoi_2"), rows):
                    if name in wanted:
                        inputs.append(BenchInput(
                            name, "World Bank Request for Expression of Interest (tenders.description)",
                            f"world_bank:{row['external_id']}", row["description"], None, False,
                        ))
            if "long_rfp" in wanted:
                pages = "(length(compiled_master_text) - length(replace(compiled_master_text, '[[PAGE ', ''))) / 7"
                if long_tender_id is None:
                    row = await connection.fetchrow(
                        f"""
                        SELECT id, source_system, compiled_master_text FROM tenders
                        WHERE source_system IN ('giz', 'world_bank', 'adb', 'ebrd') AND compiled_master_text IS NOT NULL
                          AND {pages} BETWEEN 60 AND 120
                          AND title ~* '(evaluation|consult|advis|technical assistance|assessment|study)'
                        ORDER BY {pages} DESC, id LIMIT 1
                        """
                    )
                else:
                    row = await connection.fetchrow(
                        "SELECT id, source_system, compiled_master_text FROM tenders WHERE id = $1", long_tender_id
                    )
                if row is None:
                    raise SystemExit(
                        "No local consulting RFP of 60-120 pages found. Provide one (--long-tender-id) or a file."
                    )
                text = row["compiled_master_text"]
                markers = [int(value) for value in re.findall(r"\[\[PAGE (\d+)\]\]", text)]
                inputs.append(BenchInput(
                    "long_rfp", "Long consulting RFP (tenders.compiled_master_text)",
                    f"{row['source_system']}:{row['id']}", text, max(markers) if markers else None, bool(markers),
                ))
        finally:
            await connection.close()
    order = {name: index for index, name in enumerate(INPUT_ORDER)}
    return sorted(inputs, key=lambda item: order[item.name])


# --- running ------------------------------------------------------------------


def classify_failure(exc: BaseException) -> str:
    name = type(exc).__name__
    if isinstance(exc, analyzer.ProviderAccountError):
        return exc.code
    if isinstance(exc, analyzer.RunBudgetExceeded):
        return exc.code
    if name in {"ValidationError", "JSONDecodeError"}:
        return "SCHEMA_OUTPUT_FAILURE"
    if analyzer._is_timeout(exc):  # type: ignore[arg-type]
        return "TIMEOUT"
    if isinstance(exc, RuntimeError) and str(exc) == analyzer.EMPTY_RESPONSE_MESSAGE:
        return "EMPTY_RESPONSE"
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return f"PROVIDER_HTTP_{code}"
    return name


def _sum(chunks: list[dict[str, object]], key: str) -> int | None:
    values = [int(chunk[key]) for chunk in chunks if key in chunk]
    return sum(values) if values else None


async def run_once(
    model: str, item: BenchInput, run_number: int, spans_out: list[Span] | None = None
) -> dict[str, object]:
    # Attribute every result to exactly this model, whichever length route the input takes.
    analyzer.MODEL_NAME = analyzer.LONG_MODEL_NAME = model
    analyzer.FALLBACK_MODEL_NAMES = analyzer.LONG_FALLBACK_MODEL_NAMES = ()
    sealed = analyzer.SealedTextInput(
        uuid4(), item.name, item.text, page_count=item.page_count, page_count_known=item.page_count_known
    )
    record: dict[str, object] = {"model": model, "input": item.name, "run": run_number}
    started = time.perf_counter()
    try:
        verified = await analyzer.analyze_pack_items([sealed], "en")
    except Exception as exc:  # classify only; never record the message
        record.update(
            status="FAILURE", failure_class=classify_failure(exc), exception_type=type(exc).__name__,
            latency_s=round(time.perf_counter() - started, 2),
        )
        return record
    latency = round(time.perf_counter() - started, 2)
    diagnostics = verified.diagnostics
    chunks = list(diagnostics["chunks"])  # type: ignore[arg-type]
    record.update(
        status="SUCCESS", failure_class=None, latency_s=latency,
        chunk_count=diagnostics["chunk_count"], attempts=diagnostics["attempt_count"],
        retry_count=diagnostics["retry_count"],
        retry_failure_classes=sorted({name for chunk in chunks for name in chunk.get("failure_classes", [])}),
        max_chunk_latency_s=round(max(int(chunk["latency_ms"]) for chunk in chunks) / 1000, 2) if chunks else 0,
        raw_requirements=diagnostics["raw_requirement_count"], raw_positions=diagnostics["raw_position_count"],
        verified_requirements=diagnostics["verified_requirement_count"],
        verified_positions=diagnostics["verified_position_count"],
        provenance_rejected=diagnostics["provenance_rejected_count"],
        normalization_dropped=diagnostics["normalization_dropped_count"],
        duplicates=diagnostics["duplicate_count"],
        route=diagnostics.get("route"), route_chunk_characters=diagnostics.get("route_chunk_characters"),
        context_model_verbatim=diagnostics.get("context_model_verbatim"),
        context_source_window=diagnostics.get("context_source_window"),
        context_none=diagnostics.get("context_none"),
        pipeline_version=analyzer.PIPELINE_VERSION, prompt_version=analyzer.PROMPT_VERSION,
        prompt_tokens=_sum(chunks, "prompt_tokens"), output_tokens=_sum(chunks, "output_tokens"),
        thinking_tokens=_sum(chunks, "thinking_tokens"),
    )
    if item.name in GOLDEN_INPUTS:
        covered, missing = golden_coverage(list(verified))
        record.update(golden_covered=covered, golden_missing=missing)
    if spans_out is not None:
        spans_out.extend(
            (fact.char_start, fact.char_end) for fact in verified if fact.fact.kind == "CORPORATE_REQUIREMENT"
        )
    return record


def _checkpoint(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


# --- reporting ----------------------------------------------------------------


def _percentiles(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return statistics.median(values), statistics.quantiles(values, n=10, method="inclusive")[8]


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _calls_text(ok: list[dict[str, object]]) -> str:
    chunks = [int(r["chunk_count"]) for r in ok if "chunk_count" in r]
    calls = [int(r["attempts"]) for r in ok if "attempts" in r]
    return f"{statistics.median(chunks):g} / {statistics.median(calls):g}" if chunks and calls else "n/a"


def _median(values: list[int | float]) -> float | None:
    return statistics.median(values) if values else None


def summarize(
    records: list[dict[str, object]], models: list[str], inputs: list[dict[str, object]], runs: int,
    recall: dict[str, object] | None = None,
) -> dict[str, object]:
    per_model: dict[str, object] = {}
    for model in models:
        mine = [r for r in records if r["model"] == model]
        ok = [r for r in mine if r["status"] == "SUCCESS"]
        p50, p90 = _percentiles([float(r["latency_s"]) for r in ok])
        golden = [int(r["golden_covered"]) for r in ok if "golden_covered" in r]
        b4a_runs = [r for r in mine if r["input"] in GOLDEN_INPUTS]
        failures: dict[str, int] = {}
        for r in mine:
            if r["status"] != "SUCCESS":
                failures[str(r["failure_class"])] = failures.get(str(r["failure_class"]), 0) + 1
        thinking = [int(r["thinking_tokens"]) for r in ok if r.get("thinking_tokens") is not None]
        output = [int(r["output_tokens"]) for r in ok if r.get("output_tokens") is not None]
        total_planned = len(mine)
        ratio = len(ok) / total_planned if total_planned else 0.0
        golden_full = sum(1 for r in b4a_runs if r.get("golden_covered") == 19)
        per_model[model] = {
            "runs": total_planned, "successes": len(ok), "success_ratio": round(ratio, 3),
            "latency_p50_s": p50, "latency_p90_s": p90,
            "failure_classes": failures,
            "runs_needing_retry": sum(1 for r in ok if int(r.get("retry_count", 0)) > 0),
            "runs_where_fallback_would_be_needed": sum(
                1 for r in mine if r["status"] != "SUCCESS" and r["failure_class"] in RETRY_EXHAUSTED_CLASSES
            ),
            "provider_error_runs": sum(
                1 for r in mine if r["status"] != "SUCCESS" and r["failure_class"] not in RETRY_EXHAUSTED_CLASSES
            ),
            "b4a_runs": len(b4a_runs), "b4a_golden_19_of_19_runs": golden_full,
            "golden_min": min(golden) if golden else None,
            "thinking_tokens_median": _median(thinking), "output_tokens_median": _median(output),
            "selection_success": ratio >= SELECTION_MIN_SUCCESS_RATIO,
            "selection_p90": p90 is not None and p90 <= SELECTION_MAX_P90_SECONDS,
            "selection_golden": bool(b4a_runs) and golden_full == len(b4a_runs),
            "reference_only": model == REFERENCE_MODEL,
        }
    return {"per_model": per_model, "planned_runs_per_model_input": runs, "inputs": inputs, "long_rfp_recall": recall}


def selection_outcome(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    """D1 rule: golden 19/19 in >= 4/5 B4a runs AND median per-run long-RFP recall >= 75%."""
    recall = (summary.get("long_rfp_recall") or {}).get("models", {})  # type: ignore[union-attr]
    outcome: dict[str, dict[str, object]] = {}
    for model, entry in summary["per_model"].items():  # type: ignore[union-attr]
        if entry["reference_only"]:
            continue
        runs, full = int(entry["b4a_runs"]), int(entry["b4a_golden_19_of_19_runs"])
        median_recall = recall.get(model, {}).get("recall_median")
        outcome[model] = {
            "golden_19_runs": f"{full}/{runs}",
            "golden_ok": runs > 0 and full / runs >= 0.8,
            "recall_median": median_recall,
            "recall_ok": median_recall is not None and median_recall >= 0.75,
            "p90_s": entry["latency_p90_s"],
        }
        outcome[model]["qualifies"] = bool(outcome[model]["golden_ok"] and outcome[model]["recall_ok"])
    return outcome


def render_markdown(payload: dict[str, object]) -> str:
    records: list[dict[str, object]] = payload["records"]  # type: ignore[assignment]
    summary: dict[str, object] = payload["summary"]  # type: ignore[assignment]
    meta: dict[str, object] = payload["meta"]  # type: ignore[assignment]
    inputs: list[dict[str, object]] = summary["inputs"]  # type: ignore[assignment]
    models: list[str] = meta["models"]  # type: ignore[assignment]
    per_model: dict[str, dict[str, object]] = summary["per_model"]  # type: ignore[assignment]
    plan = meta.get("plan")
    runs = int(summary["planned_runs_per_model_input"])  # type: ignore[arg-type]
    run_text = (
        "Runs per model and input follow the plan: "
        + "; ".join(f"{m}: " + ", ".join(f"{i} x{n}" for i, n in per.items()) for m, per in plan.items())  # type: ignore[union-attr]
        if plan else f"{runs} runs per model per input, sequential"
    )
    lines = [
        "# D1-02 pursuit model bench", "",
        f"Generated {meta['generated_at']} by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).", "",
        "## Method", "",
        "- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.",
        f"- {run_text}. Analyzer settings: output cap {meta['max_output_tokens']} tokens, request timeout {meta['request_timeout_seconds']} s, chunk concurrency {meta['chunk_concurrency']}"
        + (f", chunk budget {meta['chunk_budget_seconds']} s, run budget {meta['run_budget_seconds']} s." if "chunk_budget_seconds" in meta else "."),
        "- Fallback models are disabled for the bench so each result belongs to one model; a failed run means the model exhausted its retry (the point where production would switch to a fallback).",
        f"- `{REFERENCE_MODEL}` is a quality reference only and is excluded from the selection rule.",
        f"- google-genai `{meta['sdk_version']}`; latency is wall time of the whole analyzer call including any retry; p90 uses linear interpolation over successful runs.",
        "- Thinking tokens are inferred as `total - prompt - candidates` (the pinned SDK does not surface `thoughts_token_count`).",
        "- Golden coverage (B4a inputs only) is an automated anchor-based proxy for the 19 obligations of `docs/audits/p0r/live-semantic-coverage.md`, evaluated on verified facts; it is not a human adjudication.", "",
        "## Inputs", "", "| Input | Description | Source ref | Characters | SHA-256 of text | Page markers | Chunks |", "| --- | --- | --- | ---: | --- | ---: | ---: |",
    ]
    for item in inputs:
        lines.append(
            f"| {item['name']} | {item['description']} | {item['source_ref']} | {item['characters']:,} | "
            f"`{item.get('text_sha256', 'n/a')}` | {item['page_markers']} | {item['chunks']} |"
        )
    lines += ["", "## Results by model and input", "",
              "| Model | Input | Successes | Latency p50 / p90 (s) | Chunks / provider calls per run (median) | Raw requirements (median) | Verified requirements min / median / max | Provenance-rejected (median) | Context origin verbatim / window / none (totals) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |",
              "| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- | ---: | ---: | --- | --- |"]
    for model in models:
        for item in inputs:
            mine = [r for r in records if r["model"] == model and r["input"] == item["name"]]
            if not mine:
                continue
            ok = [r for r in mine if r["status"] == "SUCCESS"]
            p50, p90 = _percentiles([float(r["latency_s"]) for r in ok])
            reqs = [int(r["verified_requirements"]) for r in ok]
            poss = [int(r["verified_positions"]) for r in ok]
            raws = [int(r["raw_requirements"]) for r in ok if "raw_requirements" in r]
            rejected = [int(r["provenance_rejected"]) for r in ok if "provenance_rejected" in r]
            origins = [r for r in ok if r.get("context_source_window") is not None]
            origin_text = (
                "/".join(str(sum(int(r[k]) for r in origins)) for k in ("context_model_verbatim", "context_source_window", "context_none"))
                if origins else "n/a"
            )
            failures: dict[str, int] = {}
            for r in mine:
                if r["status"] != "SUCCESS":
                    failures[str(r["failure_class"])] = failures.get(str(r["failure_class"]), 0) + 1
            golden = ""
            if item["name"] in GOLDEN_INPUTS:
                covered = [int(r["golden_covered"]) for r in ok if "golden_covered" in r]
                golden = f"{min(covered)} / {sum(1 for value in covered if value == 19)}" if covered else "n/a"
            label = f"{model} (reference)" if model == REFERENCE_MODEL else model
            lines.append(
                f"| {label} | {item['name']} | {len(ok)}/{len(mine)} | {_fmt(p50)} / {_fmt(p90)} | "
                f"{_calls_text(ok)} | "
                f"{'n/a' if not raws else f'{statistics.median(raws):g}'} | "
                f"{'n/a' if not reqs else f'{min(reqs)} / {statistics.median(reqs):g} / {max(reqs)}'} | "
                f"{'n/a' if not rejected else f'{statistics.median(rejected):g}'} | "
                f"{origin_text} | "
                f"{'n/a' if not poss else f'{statistics.median(poss):g}'} | "
                f"{sum(int(r.get('retry_count', 0)) for r in ok)} | "
                f"{', '.join(f'{k} x{v}' for k, v in failures.items()) or '-'} | {golden or '-'} |"
            )
    recall = summary.get("long_rfp_recall")
    lines += ["", "## Long-RFP recall against the reference model", ""]
    if recall:
        lines += [
            f"Reference set: union of verified requirement quote spans from {recall['reference_runs']} successful `{recall['reference_model']}` run(s), "
            f"{recall['reference_items']} distinct items (per run: {', '.join(str(n) for n in recall['reference_items_per_run'])}). "
            f"An item matches when spans overlap by >= {int(float(recall['span_match_min_overlap']) * 100)}% of the shorter span. "
            "The reference is itself imperfect: it defines what a stronger model found, not ground truth.", "",
            "| Model | Runs | Recall per run | Recall median | Recall of union of runs | Model-only items per run (median) | Model-only items (union of runs) |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
        for model, entry in recall["models"].items():  # type: ignore[union-attr]
            lines.append(
                f"| {model} | {entry['runs']} | {', '.join(f'{v:.0%}' for v in entry['recall_per_run'])} | "
                f"{entry['recall_median']:.0%} | {entry['recall_union']:.0%} | {entry['model_only_median']:g} | {entry['model_only_union']} |"
            )
        lines += ["", "A local, gitignored side-by-side list of reference items each model missed is written to `.private-storage/d1_bench/` for human spot-checking; it is not part of this report.", ""]
    else:
        lines += ["Not available: no successful reference-model run on the long RFP.", ""]
    lines += ["", "## Selection rule (reported only)", "",
              f"Rule: success ratio >= 8/9 (>= {SELECTION_MIN_SUCCESS_RATIO:.3f}), p90 latency <= {SELECTION_MAX_P90_SECONDS:g} s over successful runs, golden coverage 19/19 on every B4a run.", "",
              "| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for model in models:
        m = per_model[model]
        if m["reference_only"]:
            meets = "reference"
        elif not m["b4a_runs"]:
            meets = "n/a"
        else:
            meets = "yes" if m["selection_success"] and m["selection_p90"] and m["selection_golden"] else "no"
        lines.append(
            f"| {model} | {m['successes']}/{m['runs']} | {'pass' if m['selection_success'] else 'fail'} | "
            f"{_fmt(m['latency_p50_s'])} / {_fmt(m['latency_p90_s'])} | {'pass' if m['selection_p90'] else 'fail'} | "
            f"{m['b4a_golden_19_of_19_runs']}/{m['b4a_runs']} | {'pass' if m['selection_golden'] else 'fail' if m['b4a_runs'] else 'n/a'} | {meets} |"
        )
    outcome = selection_outcome(summary)
    if outcome:
        lines += ["", "## D1 primary-model rule", "",
                  "Rule: golden 19/19 in >= 4/5 B4a runs AND median per-run long-RFP recall >= 75% against the reference set.", "",
                  "| Model | Golden 19/19 runs | Golden rule | Long-RFP recall (median per run) | Recall rule | Qualifies |",
                  "| --- | --- | --- | ---: | --- | --- |"]
        for model, entry in outcome.items():
            recall_text = "n/a" if entry["recall_median"] is None else f"{float(entry['recall_median']):.0%}"
            lines.append(
                f"| {model} | {entry['golden_19_runs']} | {'pass' if entry['golden_ok'] else 'fail'} | {recall_text} | "
                f"{'pass' if entry['recall_ok'] else 'fail'} | {'yes' if entry['qualifies'] else 'no'} |"
            )
    lines += ["", "## Thinking, latency, and fallback notes", ""]
    for model in models:
        m = per_model[model]
        thinking, output = m["thinking_tokens_median"], m["output_tokens_median"]
        note = (
            f"- **{model}**: median run latency {_fmt(m['latency_p50_s'])} s, p90 {_fmt(m['latency_p90_s'])} s; "
            + (f"median thinking tokens {thinking:,.0f} vs {output:,.0f} output tokens per successful run"
               if thinking is not None and output is not None else "token usage not reported")
            + f"; retry used in {m['runs_needing_retry']} successful run(s); retry exhausted (fallback would be needed) in {m['runs_where_fallback_would_be_needed']} of {m['runs']} run(s)"
            + (
                f"; {m['provider_error_runs']} run(s) failed on a provider/account error the analyzer does not retry "
                f"(no fallback path) [{', '.join(f'{k} x{v}' for k, v in m['failure_classes'].items() if k not in RETRY_EXHAUSTED_CLASSES)}]"
                if m["provider_error_runs"] else ""
            )
            + "."
        )
        lines.append(note)
    needed = sum(int(per_model[m]["runs_where_fallback_would_be_needed"]) for m in models if m != REFERENCE_MODEL)
    lines += ["", f"Fallback ever needed among candidate models: {'yes' if needed else 'no'} ({needed} run(s) exhausted the primary retry).", ""]
    return "\n".join(lines)


RUN_NOTES_HEADING = "\n## Run notes\n"


def write_report(path: Path, markdown: str) -> None:
    """Write the generated report, keeping any hand-written '## Run notes' section."""
    notes = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if RUN_NOTES_HEADING in existing:
            notes = RUN_NOTES_HEADING + existing.split(RUN_NOTES_HEADING, 1)[1]
    path.write_text(markdown.rstrip("\n") + "\n" + notes, encoding="utf-8")


# --- entry point --------------------------------------------------------------


def build_plan(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    if args.preset:
        return {model: dict(per) for model, per in PRESETS[args.preset].items()}
    return {model: {name: args.runs for name in args.inputs} for model in args.models}


def _load_spans(path: Path) -> dict[str, dict[str, list[Span]]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {model: {run: [(s, e) for s, e in spans] for run, spans in runs.items()} for model, runs in raw.items()}


async def main_async(args: argparse.Namespace) -> int:
    api_key = analyzer._resolve_gemini_api_key()
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not configured.")
    if args.long_chunk_chars:
        analyzer.LONG_CHUNK_CHARACTERS = args.long_chunk_chars
    plan = build_plan(args)
    models = list(plan)
    wanted = {name for per in plan.values() for name in per}
    inputs = await load_inputs(wanted, args.long_tender_id)
    if "long_rfp" in wanted and not any(item.name == "long_rfp" for item in inputs):
        raise SystemExit("long_rfp input unavailable")
    suffix = f"-{args.tag}" if args.tag else ""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"model-bench{suffix}.json"
    private_dir = PRIVATE_DIR / (args.tag or "default")
    spans_path = private_dir / "long_rfp_spans.json"
    records: list[dict[str, object]] = []
    spans_by_model = _load_spans(spans_path) if args.resume else {}
    if args.reference_from:
        reused = _load_spans(PRIVATE_DIR / args.reference_from / "long_rfp_spans.json").get(REFERENCE_MODEL)
        if not reused:
            raise SystemExit(f"No {REFERENCE_MODEL} long-RFP spans stored for tag {args.reference_from!r}.")
        spans_by_model[REFERENCE_MODEL] = reused
    for tag in args.compare_tags:
        for model, runs in _load_spans(PRIVATE_DIR / tag / "long_rfp_spans.json").items():
            if model != REFERENCE_MODEL:
                spans_by_model[f"{model} ({tag})"] = runs
    if args.resume and json_path.exists():
        records = json.loads(json_path.read_text(encoding="utf-8"))["records"]
    done = {(r["model"], r["input"], r["run"]) for r in records}
    public_inputs = [item.public() for item in inputs]
    from google import genai

    def payload() -> dict[str, object]:
        return {
            "meta": {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "models": models, "plan": plan, "runs_per_model_input": args.runs,
                "max_output_tokens": analyzer.MAX_OUTPUT_TOKENS,
                "request_timeout_seconds": analyzer.REQUEST_TIMEOUT_SECONDS,
                "chunk_budget_seconds": analyzer.CHUNK_BUDGET_SECONDS,
                "run_budget_seconds": analyzer.RUN_BUDGET_SECONDS,
                "chunk_concurrency": analyzer.CHUNK_CONCURRENCY,
                "sdk_version": getattr(genai, "__version__", "unknown"),
                "prompt_version": analyzer.PROMPT_VERSION, "schema_version": analyzer.SCHEMA_VERSION,
                "pipeline_version": analyzer.PIPELINE_VERSION, "reference_from": args.reference_from,
                "long_chunk_characters": analyzer.LONG_CHUNK_CHARACTERS, "compare_tags": args.compare_tags,
                "long_pack_threshold_characters": analyzer.LONG_PACK_CHARACTERS,
            },
            "summary": summarize(records, models, public_inputs, args.runs, recall_summary(spans_by_model)),
            "records": records,
        }

    stopped = False
    for item in inputs:
        for model in models:
            for run_number in range(1, plan[model].get(item.name, 0) + 1):
                if (model, item.name, run_number) in done:
                    continue
                spans: list[Span] | None = [] if item.name == "long_rfp" else None
                record = await run_once(model, item, run_number, spans)
                records.append(record)
                if spans is not None and record["status"] == "SUCCESS":
                    spans_by_model.setdefault(model, {})[str(run_number)] = spans
                    private_dir.mkdir(parents=True, exist_ok=True)
                    spans_path.write_text(json.dumps(spans_by_model), encoding="utf-8")
                _checkpoint(json_path, payload())
                print(
                    f"{model:<24} {item.name:<9} run {run_number}/{plan[model][item.name]} {record['status']:<7} "
                    f"{record['latency_s']:>7}s "
                    + (f"verified={record['verified_requirements']}+{record['verified_positions']} "
                       f"retries={record['retry_count']}"
                       + (f" golden={record['golden_covered']}/19" if "golden_covered" in record else "")
                       if record["status"] == "SUCCESS" else f"class={record['failure_class']}"),
                    flush=True,
                )
                if record.get("failure_class") == analyzer.ProviderAccountError.code:
                    print("STOP: the provider rejected the request with HTTP 401/402/403; not continuing.", flush=True)
                    stopped = True
                    break
            if stopped:
                break
        if stopped:
            break
    final = payload()
    _checkpoint(json_path, final)
    write_report(args.output_dir / f"model-bench{suffix}.md", render_markdown(final))
    long_input = next((item for item in inputs if item.name == "long_rfp"), None)
    if long_input is not None and spans_by_model.get(REFERENCE_MODEL):
        listed = export_unmatched_reference_items(private_dir / "unmatched_reference_items.md", long_input.text, spans_by_model)
        print(f"Wrote {listed} unmatched reference item(s) to {private_dir / 'unmatched_reference_items.md'} (local, gitignored)")
    print(f"Wrote {args.output_dir / f'model-bench{suffix}.md'} and {json_path}")
    return 3 if stopped else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--inputs", nargs="+", choices=INPUT_ORDER, default=list(DEFAULT_INPUTS))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--preset", choices=sorted(PRESETS), help="named per-model/per-input run matrix (overrides --models/--inputs/--runs)")
    parser.add_argument("--tag", default=None, help="suffix for output files, e.g. r2 -> model-bench-r2.md (defaults to the preset name)")
    parser.add_argument(
        "--reference-from", default=None,
        help="reuse the reference model's long-RFP spans from an earlier tag (e.g. r2) instead of re-running it",
    )
    parser.add_argument("--long-chunk-chars", type=int, default=None, help="override the LONG route chunk size")
    parser.add_argument(
        "--compare-tags", nargs="*", default=[],
        help="also score the stored long-RFP runs of these earlier tags against this bench's reference set",
    )
    parser.add_argument("--long-tender-id", type=UUID, default=None, help="override the auto-selected long RFP")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--resume", action="store_true", help="skip runs already in the JSON output")
    parser.add_argument("--render-only", action="store_true", help="rebuild the markdown from the JSON output")
    args = parser.parse_args(argv)
    if args.tag is None:
        args.tag = args.preset
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.render_only:
        suffix = f"-{args.tag}" if args.tag else ""
        payload = json.loads((args.output_dir / f"model-bench{suffix}.json").read_text(encoding="utf-8"))
        write_report(args.output_dir / f"model-bench{suffix}.md", render_markdown(payload))
        return 0
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
