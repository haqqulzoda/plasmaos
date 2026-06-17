"""Reproducibility helpers for compliance analysis snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.tender_sources.keys import (
    canonical_source_key as build_canonical_source_key,
)


FILE_MARKER_RE = re.compile(r"\[\[FILE:\s*([^\]]+?)\s*\]\]")
PAGE_MARKER_RE = re.compile(r"\[\[PAGE\s+(\d+)\]\]")

REQUIREMENT_BUCKETS: tuple[tuple[str, str], ...] = (
    ("failed_dealbreakers", "failed"),
    ("manual_reviews_required", "manual"),
    ("satisfied_requirements", "satisfied"),
    ("recorded_obligations", "recorded"),
)

INTERNAL_REQUIREMENT_DIAGNOSTIC_KEYS = {
    "requirement_fingerprint",
    "final_bucket",
    "source_key",
    "source_chunk_index",
    "source_filename_display",
    "source_filename_canonical",
}


def sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalize_source_file_markers(text: str | None) -> str:
    if not text:
        return ""

    def replace_marker(match: re.Match[str]) -> str:
        canonical_filename = canonical_source_filename(match.group(1)) or ""
        return f"[[FILE: {canonical_filename}]]"

    return FILE_MARKER_RE.sub(replace_marker, text)


def canonical_marker_text_sha256(text: str | None) -> str:
    return sha256_text(canonicalize_source_file_markers(text)) or ""


def stable_document_order_key(
    *,
    source_filename: Any,
    file_type: Any = None,
    file_size: Any = None,
    parsed_text: str | None = None,
    parsed_text_canonical_marker_sha256: str | None = None,
    created_at: Any = None,
    document_id: Any = None,
) -> tuple[str, str, int, str, str, str]:
    try:
        normalized_file_size = int(file_size or 0)
    except (TypeError, ValueError):
        normalized_file_size = 0

    return (
        canonical_source_filename(source_filename) or "",
        str(file_type or "").casefold().strip().lstrip("."),
        normalized_file_size,
        parsed_text_canonical_marker_sha256
        or canonical_marker_text_sha256(parsed_text),
        str(created_at or ""),
        str(document_id or ""),
    )


def stable_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def marker_counts(text: str | None) -> dict[str, int]:
    payload = text or ""
    return {
        "file_marker_count": len(FILE_MARKER_RE.findall(payload)),
        "page_marker_count": len(PAGE_MARKER_RE.findall(payload)),
    }


def infer_source_system(source_url: str | None) -> str:
    host = (urlparse(source_url or "").netloc or "").casefold()
    if "worldbank.org" in host:
        return "world_bank"
    if "adb.org" in host:
        return "adb"
    if "uzex.uz" in host or "etender" in host:
        return "uzex"
    return "uzex"


def canonical_source_key(source_system: str, external_id: str) -> str:
    return build_canonical_source_key(source_system, external_id)


def safe_basename(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(str(value)).name.strip()
    return name or None


def canonical_source_filename(value: Any) -> str | None:
    if value is None:
        return None

    decoded = unquote(str(value)).replace("\\", "/")
    parsed = urlparse(decoded)
    if parsed.scheme or parsed.netloc:
        decoded = parsed.path or decoded

    name = Path(decoded).name.strip()
    if not name:
        return None

    name = unicodedata.normalize("NFC", name)
    storage_match = re.match(r"^[0-9a-fA-F]{32}_(.+)$", name)
    if storage_match:
        name = storage_match.group(1)

    name = re.sub(r"\s+", " ", name.replace("\u00a0", " ")).casefold().strip()
    return name or None


def normalize_requirement_text(value: Any) -> str:
    normalized = str(value or "").replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold().strip()


def requirement_source_key(
    *,
    source_filename: Any,
    source_page: Any,
    exact_quote: Any,
) -> str:
    return "|".join(
        (
            canonical_source_filename(source_filename) or "",
            str(source_page or "").strip(),
            normalize_requirement_text(exact_quote),
        )
    )


def requirement_fingerprint(requirement: dict[str, Any]) -> str:
    return hashlib.sha256(
        requirement_source_key(
            source_filename=requirement.get("source_filename"),
            source_page=requirement.get("source_page"),
            exact_quote=requirement.get("exact_quote"),
        ).encode("utf-8")
    ).hexdigest()


def requirement_quote_key(requirement: dict[str, Any]) -> str:
    return normalize_requirement_text(requirement.get("exact_quote"))


def sanitize_internal_requirement_diagnostics(value: Any) -> Any:
    """Remove only internal routing diagnostics from customer payloads."""
    if isinstance(value, list):
        return [sanitize_internal_requirement_diagnostics(item) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize_internal_requirement_diagnostics(item)
            for key, item in value.items()
            if key not in INTERNAL_REQUIREMENT_DIAGNOSTIC_KEYS
        }
    return value


def _chunk_index_for_requirement(
    requirement: dict[str, Any],
    source_chunk_index_by_fingerprint: dict[str, int | None],
) -> int | None:
    return source_chunk_index_by_fingerprint.get(requirement_fingerprint(requirement))


def annotate_requirement(
    requirement: dict[str, Any],
    *,
    final_bucket: str,
    source_chunk_index_by_fingerprint: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    annotated = dict(requirement)
    fingerprint = requirement_fingerprint(annotated)
    source_filename = annotated.get("source_filename")
    source_filename_display = safe_basename(str(source_filename)) if source_filename else None
    source_filename_canonical = canonical_source_filename(source_filename)
    annotated["requirement_fingerprint"] = fingerprint
    annotated["final_bucket"] = final_bucket
    annotated["source_filename_display"] = source_filename_display
    annotated["source_filename_canonical"] = source_filename_canonical
    annotated["source_key"] = requirement_source_key(
        source_filename=source_filename,
        source_page=annotated.get("source_page"),
        exact_quote=annotated.get("exact_quote"),
    )
    if source_chunk_index_by_fingerprint is not None:
        annotated["source_chunk_index"] = _chunk_index_for_requirement(
            annotated,
            source_chunk_index_by_fingerprint,
        )
    return annotated


def annotate_hybrid_compliance(
    hybrid_compliance: dict[str, Any],
    *,
    source_chunk_index_by_fingerprint: dict[str, int | None],
) -> dict[str, Any]:
    annotated = dict(hybrid_compliance)
    for field_name, final_bucket in REQUIREMENT_BUCKETS:
        annotated[field_name] = [
            annotate_requirement(
                item,
                final_bucket=final_bucket,
                source_chunk_index_by_fingerprint=source_chunk_index_by_fingerprint,
            )
            for item in annotated.get(field_name) or []
            if isinstance(item, dict)
        ]
    return annotated


def annotate_evidence_validation(
    evidence_validation: dict[str, Any],
    *,
    final_bucket_by_fingerprint: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated = dict(evidence_validation)
    final_bucket_by_fingerprint = final_bucket_by_fingerprint or {}
    for field_name, default_bucket in (
        ("accepted_requirements", "skipped"),
        ("needs_review_requirements", "manual"),
        ("rejected_requirements", "rejected_internal"),
    ):
        items = []
        for item in annotated.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            fingerprint = requirement_fingerprint(item)
            items.append(
                annotate_requirement(
                    item,
                    final_bucket=final_bucket_by_fingerprint.get(
                        fingerprint,
                        default_bucket,
                    ),
                )
            )
        annotated[field_name] = items
    return annotated


def requirement_route_records(hybrid_compliance: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for field_name, final_bucket in REQUIREMENT_BUCKETS:
        for item in hybrid_compliance.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            records.append(
                {
                    "requirement_fingerprint": item.get("requirement_fingerprint")
                    or requirement_fingerprint(item),
                    "final_bucket": item.get("final_bucket") or final_bucket,
                    "source_key": requirement_source_key(
                        source_filename=item.get("source_filename"),
                        source_page=item.get("source_page"),
                        exact_quote=item.get("exact_quote"),
                    ),
                    "headline": item.get("headline"),
                    "category": item.get("category"),
                    "source_filename": item.get("source_filename"),
                    "source_filename_display": item.get("source_filename_display")
                    or safe_basename(str(item.get("source_filename")))
                    if item.get("source_filename")
                    else None,
                    "source_filename_canonical": item.get("source_filename_canonical")
                    or canonical_source_filename(item.get("source_filename")),
                    "source_page": item.get("source_page"),
                    "exact_quote": item.get("exact_quote"),
                    "validation_status": item.get("validation_status"),
                    "requirement_scope": item.get("requirement_scope"),
                    "scope_review_status": item.get("scope_review_status"),
                    "affects_bid_eligibility": item.get("affects_bid_eligibility"),
                    "vault_match_type": item.get("vault_match_type"),
                    "vault_match_confidence": item.get("vault_match_confidence"),
                    "vault_missing_reason": item.get("vault_missing_reason"),
                    "source_chunk_index": item.get("source_chunk_index"),
                }
            )
    return records


def evidence_validation_route_records(
    evidence_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for field_name in (
        "accepted_requirements",
        "needs_review_requirements",
        "rejected_requirements",
    ):
        for item in evidence_validation.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            final_bucket = item.get("final_bucket")
            if final_bucket not in {"skipped", "rejected_internal"}:
                continue
            records.append(
                {
                    "requirement_fingerprint": item.get("requirement_fingerprint")
                    or requirement_fingerprint(item),
                    "final_bucket": final_bucket,
                    "source_key": requirement_source_key(
                        source_filename=item.get("source_filename"),
                        source_page=item.get("source_page"),
                        exact_quote=item.get("exact_quote"),
                    ),
                    "headline": item.get("headline"),
                    "category": item.get("category"),
                    "source_filename": item.get("source_filename"),
                    "source_filename_display": item.get("source_filename_display")
                    or safe_basename(str(item.get("source_filename")))
                    if item.get("source_filename")
                    else None,
                    "source_filename_canonical": item.get("source_filename_canonical")
                    or canonical_source_filename(item.get("source_filename")),
                    "source_page": item.get("source_page"),
                    "exact_quote": item.get("exact_quote"),
                    "validation_status": item.get("validation_status"),
                    "requirement_scope": item.get("requirement_scope"),
                    "scope_review_status": item.get("scope_review_status"),
                    "affects_bid_eligibility": item.get("affects_bid_eligibility"),
                    "vault_match_type": item.get("vault_match_type"),
                    "vault_match_confidence": item.get("vault_match_confidence"),
                    "vault_missing_reason": item.get("vault_missing_reason"),
                    "source_chunk_index": item.get("source_chunk_index"),
                }
            )
    return records


def engine_metadata(
    *,
    extractor_schema_version: str,
    requirement_model_name: str,
    temperature: float,
    max_payload_chars: int,
    extractor_mode: str | None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "extractor_schema_version": extractor_schema_version,
        "prompt_schema_version": extractor_schema_version,
        "requirement_model_name": requirement_model_name,
        "temperature": temperature,
        "max_payload_chars": max_payload_chars,
        "chunking_version": "traceable_page_chunks_v1",
        "extractor_mode": extractor_mode,
        "scope_classifier_version": extractor_schema_version,
        "vault_matching_version": "vault_deterministic_v1",
        "code_build_sha": os.getenv("PLASMA_BUILD_SHA") or None,
        "build_time": os.getenv("PLASMA_BUILD_TIME") or None,
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
    }
