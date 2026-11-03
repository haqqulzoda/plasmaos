"""Live mode: run the real extraction pipeline on the evaluation set and store its outputs.

This calls the paid model provider. It is never run by tests or CI. It only runs when
the operator passes ``--confirm-live-provider-calls`` and has ``GEMINI_API_KEY`` set in
their own environment. It reads no database and writes only to ``--out``.

Pipelines:

* ``pursuit``: ``pursuit_analyzer.analyze_pack_items`` (W4 pursuit analysis), one sealed
  item per document, with the configured routing, retries and fallbacks unchanged.
* ``compliance``: ``requirement_extractor.extract_requirements`` (compliance analysis)
  on the document text wrapped in ``[[FILE]]``/``[[PAGE 1]]`` markers.

Outputs: ``<out>/<doc_id>.json`` in the harness format (see ``adapters.py``) plus
``<out>/run.json`` with counts, model names, pipeline/prompt versions and failures. No
source text is copied into ``run.json``; the per-document files hold only the
pipeline's own quotes and labels.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .dataset import Dataset

CONFIRM_FLAG = "--confirm-live-provider-calls"


class LiveModeRefused(RuntimeError):
    pass


def check_preconditions(confirmed: bool) -> None:
    if not confirmed:
        raise LiveModeRefused(f"Live mode calls the paid model provider. Re-run with {CONFIRM_FLAG}.")
    if (os.getenv("ENVIRONMENT") or "").strip().lower() == "production":
        raise LiveModeRefused("Refusing to run with ENVIRONMENT=production.")
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return
    try:  # the app also reads the key from its settings (.env); importing settings validates them
        from app.core.agents.requirement_extractor import _resolve_gemini_api_key

        resolved = _resolve_gemini_api_key()
    except Exception as exc:  # settings could not be loaded in this shell
        raise LiveModeRefused(
            f"No GEMINI_API_KEY in this shell and app settings could not be loaded ({type(exc).__name__})."
        ) from None
    if not (resolved or "").strip():
        raise LiveModeRefused("No Gemini API key configured; live mode uses only your own key.")


def _analysis_language(document_language: str, choice: str) -> str:
    return document_language if choice == "document" else choice


async def _run_pursuit(text: str, doc_id: str, language: str) -> tuple[list[dict], dict]:
    from app.core.agents import pursuit_analyzer as analyzer

    sealed = analyzer.SealedTextInput(uuid4(), doc_id, text, page_count=None, page_count_known=False)
    verified = await analyzer.analyze_pack_items([sealed], language)
    items = [{
        "quote": value.fact.original_quote,
        "obligation": value.fact.distinction,
        "kind": value.fact.kind,
        "requirement_type": value.fact.requirement_type,
        "stage_scope": value.fact.stage_scope,
    } for value in verified]
    diagnostics = getattr(verified, "diagnostics", {}) or {}
    meta = {
        "model": diagnostics.get("model_name"),
        "pipeline_version": analyzer.PIPELINE_VERSION,
        "prompt_version": analyzer.PROMPT_VERSION,
        "raw_requirement_count": diagnostics.get("raw_requirement_count"),
        "provenance_rejected_count": diagnostics.get("provenance_rejected_count"),
    }
    return items, meta


async def _run_compliance(text: str, doc_id: str, language: str) -> tuple[list[dict], dict]:
    from app.core.agents import requirement_extractor as rx

    payload = f"[[FILE: {doc_id}.txt]]\n[[PAGE 1]]\n{text}"
    requirements = rx.validate_requirements_evidence(await rx.extract_requirements(payload, language), payload)
    requirements = rx.classify_requirements_scope(requirements, payload)
    items = [{
        "quote": requirement.exact_quote,
        "obligation": {"DQ": "MANDATORY", "NICE_TO_HAVE": "PREFERRED_OR_SCORED", "COMPLIANT": "INFORMATIONAL"}.get(
            requirement.category.value
        ),
        "kind": "COMPLIANCE_REQUIREMENT",
        "category": requirement.category.value,
        "source_verified": requirement.source_verified,
        "affects_bid_eligibility": requirement.affects_bid_eligibility,
        "requirement_scope": requirement.requirement_scope.value,
    } for requirement in requirements]
    meta = {
        "model": rx.MODEL_NAME, "schema_version": rx.EXTRACTOR_SCHEMA_VERSION,
        "prompt_version": rx.PROMPT_TEMPLATE_VERSION,
    }
    return items, meta


RUNNERS = {"pursuit": _run_pursuit, "compliance": _run_compliance}


async def run(
    dataset: Dataset, *, pipeline: str, out: Path, confirmed: bool, analysis_language: str = "document",
    max_docs: int | None = None, only: list[str] | None = None, resume: bool = False,
) -> dict:
    check_preconditions(confirmed)
    runner = RUNNERS[pipeline]
    out.mkdir(parents=True, exist_ok=True)
    documents = [d for d in dataset.documents if not only or d.doc_id in only][: max_docs or None]
    summary: dict = {
        "pipeline": pipeline, "dataset_id": dataset.manifest.get("dataset_id"), "dataset_status": dataset.status,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_language": analysis_language, "documents": [], "failures": [],
    }
    for document in documents:
        target = out / f"{document.doc_id}.json"
        if resume and target.exists():
            continue
        language = _analysis_language(document.language, analysis_language)
        started = time.perf_counter()
        try:
            items, meta = await runner(document.text, document.doc_id, language)
        except Exception as exc:  # record the class only; provider messages can echo input
            summary["failures"].append({"doc_id": document.doc_id, "exception_type": type(exc).__name__})
            if type(exc).__name__ == "ProviderAccountError":
                break  # 401/402/403: key, billing or permission problem; stop spending attempts
            continue
        record = {
            "doc_id": document.doc_id, "pipeline": pipeline, "analysis_language": language,
            "latency_s": round(time.perf_counter() - started, 2), **meta, "items": items,
        }
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["documents"].append({"doc_id": document.doc_id, "items": len(items), "latency_s": record["latency_s"]})
    summary["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_sync(*args, **kwargs) -> dict:
    return asyncio.run(run(*args, **kwargs))
