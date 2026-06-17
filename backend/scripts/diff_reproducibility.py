#!/usr/bin/env python3
"""Diff two admin reproducibility endpoint exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).casefold().strip()


def _canonical_source_filename(value: Any) -> str:
    if value is None:
        return ""

    decoded = unquote(str(value)).replace("\\", "/")
    parsed = urlparse(decoded)
    if parsed.scheme or parsed.netloc:
        decoded = parsed.path or decoded

    name = Path(decoded).name.strip()
    if not name:
        return ""

    name = unicodedata.normalize("NFC", name)
    storage_match = re.match(r"^[0-9a-fA-F]{32}_(.+)$", name)
    if storage_match:
        name = storage_match.group(1)

    return re.sub(r"\s+", " ", name.replace("\u00a0", " ")).casefold().strip()


def _route_source_filename_canonical(item: dict[str, Any]) -> str:
    return str(item.get("source_filename_canonical") or "").strip() or _canonical_source_filename(
        item.get("source_filename")
    )


def _route_comparison_key(item: dict[str, Any]) -> str:
    return "|".join(
        (
            _route_source_filename_canonical(item),
            str(item.get("source_page") or "").strip(),
            _normalize(item.get("exact_quote")),
        )
    )


def _route_comparison_fingerprint(item: dict[str, Any]) -> str:
    return hashlib.sha256(_route_comparison_key(item).encode("utf-8")).hexdigest()


def _latest_routes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    analyses = payload.get("latest_analyses") or []
    if not analyses:
        return []
    return [
        item
        for item in analyses[0].get("requirement_route_summary") or []
        if isinstance(item, dict)
    ]


def _by_fingerprint(routes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _route_comparison_fingerprint(item): item
        for item in routes
        if _route_comparison_key(item).strip("|")
    }


def _by_quote(routes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in routes:
        key = _route_comparison_key(item)
        if key:
            grouped.setdefault(key, []).append(item)
    return grouped


def _quote_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "fingerprint": item.get("requirement_fingerprint"),
        "comparison_fingerprint": _route_comparison_fingerprint(item)
        if _route_comparison_key(item).strip("|")
        else None,
        "bucket": item.get("final_bucket"),
        "headline": item.get("headline"),
        "category": item.get("category"),
        "source_filename": item.get("source_filename"),
        "source_filename_display": item.get("source_filename_display")
        or item.get("source_filename"),
        "source_filename_canonical": _route_source_filename_canonical(item),
        "source_page": item.get("source_page"),
    }


def _route_context(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "quote": _normalize(item.get("exact_quote")),
        "source_filename_canonical": _route_source_filename_canonical(item),
        "source_page": item.get("source_page"),
    }


def _first(items: list[dict[str, Any]]) -> dict[str, Any]:
    return items[0] if items else {}


def diff_exports(local: dict[str, Any], prod: dict[str, Any]) -> dict[str, Any]:
    local_routes = _latest_routes(local)
    prod_routes = _latest_routes(prod)
    local_by_fp = _by_fingerprint(local_routes)
    prod_by_fp = _by_fingerprint(prod_routes)

    common_fps = set(local_by_fp) & set(prod_by_fp)
    local_only = sorted(set(local_by_fp) - set(prod_by_fp))
    prod_only = sorted(set(prod_by_fp) - set(local_by_fp))

    bucket_movements = []
    for fingerprint in sorted(common_fps):
        left = local_by_fp[fingerprint]
        right = prod_by_fp[fingerprint]
        if left.get("final_bucket") != right.get("final_bucket"):
            bucket_movements.append(
                {
                    "requirement_fingerprint": fingerprint,
                    "local_bucket": left.get("final_bucket"),
                    "prod_bucket": right.get("final_bucket"),
                    "local": _quote_identity(left),
                    "prod": _quote_identity(right),
                }
            )

    local_by_quote = _by_quote(local_routes)
    prod_by_quote = _by_quote(prod_routes)
    common_quotes = set(local_by_quote) & set(prod_by_quote)

    headline_or_category = []
    validation = []
    scope = []
    vault = []
    for comparison_key in sorted(common_quotes):
        left = _first(local_by_quote[comparison_key])
        right = _first(prod_by_quote[comparison_key])
        if (
            _normalize(left.get("headline")) != _normalize(right.get("headline"))
            or _normalize(left.get("category")) != _normalize(right.get("category"))
        ):
            headline_or_category.append(
                {
                    **_route_context(left),
                    "local": _quote_identity(left),
                    "prod": _quote_identity(right),
                }
            )
        if left.get("validation_status") != right.get("validation_status"):
            validation.append(
                {
                    **_route_context(left),
                    "local_validation_status": left.get("validation_status"),
                    "prod_validation_status": right.get("validation_status"),
                    "local": _quote_identity(left),
                    "prod": _quote_identity(right),
                }
            )
        if (
            left.get("requirement_scope") != right.get("requirement_scope")
            or left.get("scope_review_status") != right.get("scope_review_status")
            or left.get("affects_bid_eligibility") != right.get("affects_bid_eligibility")
        ):
            scope.append(
                {
                    **_route_context(left),
                    "local_scope": {
                        "requirement_scope": left.get("requirement_scope"),
                        "scope_review_status": left.get("scope_review_status"),
                        "affects_bid_eligibility": left.get("affects_bid_eligibility"),
                    },
                    "prod_scope": {
                        "requirement_scope": right.get("requirement_scope"),
                        "scope_review_status": right.get("scope_review_status"),
                        "affects_bid_eligibility": right.get("affects_bid_eligibility"),
                    },
                    "local": _quote_identity(left),
                    "prod": _quote_identity(right),
                }
            )
        if (
            left.get("vault_match_type") != right.get("vault_match_type")
            or left.get("vault_match_confidence") != right.get("vault_match_confidence")
            or left.get("vault_missing_reason") != right.get("vault_missing_reason")
        ):
            vault.append(
                {
                    **_route_context(left),
                    "local_vault": {
                        "vault_match_type": left.get("vault_match_type"),
                        "vault_match_confidence": left.get("vault_match_confidence"),
                        "vault_missing_reason": left.get("vault_missing_reason"),
                    },
                    "prod_vault": {
                        "vault_match_type": right.get("vault_match_type"),
                        "vault_match_confidence": right.get("vault_match_confidence"),
                        "vault_missing_reason": right.get("vault_missing_reason"),
                    },
                    "local": _quote_identity(left),
                    "prod": _quote_identity(right),
                }
            )

    return {
        "same_fingerprint_different_bucket": bucket_movements,
        "local_only_fingerprint": [
            _quote_identity(local_by_fp[fingerprint])
            for fingerprint in local_only
        ],
        "prod_only_fingerprint": [
            _quote_identity(prod_by_fp[fingerprint])
            for fingerprint in prod_only
        ],
        "same_quote_different_headline_or_category": headline_or_category,
        "same_quote_different_validation_status": validation,
        "same_quote_different_scope_decision": scope,
        "same_quote_different_vault_decision": vault,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diff two reproducibility endpoint JSON exports."
    )
    parser.add_argument("local_export", type=Path)
    parser.add_argument("prod_export", type=Path)
    args = parser.parse_args()

    local = json.loads(args.local_export.read_text(encoding="utf-8"))
    prod = json.loads(args.prod_export.read_text(encoding="utf-8"))
    print(json.dumps(diff_exports(local, prod), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
