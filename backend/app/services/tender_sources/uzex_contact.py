"""Safe UzEx contact/submission metadata extraction helpers."""

from __future__ import annotations

import json
import re
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: Any, *, max_length: int = 500) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    text = _WHITESPACE_RE.sub(" ", str(value)).strip()
    if not text:
        return None
    return text[:max_length].strip() or None


def _first_text(
    raw: dict[str, Any],
    keys: tuple[str, ...],
    *,
    max_length: int = 500,
) -> str | None:
    for key in keys:
        value = _clean_text(raw.get(key), max_length=max_length)
        if value:
            return value
    return None


def _parse_contacts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return [{"Fullname": stripped}]

    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []

    contacts: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            contacts.append(item)
    return contacts


def _contact_person(raw: dict[str, Any]) -> str | None:
    contacts = _parse_contacts(raw.get("contacts"))
    rendered: list[str] = []
    for contact in contacts:
        name = _first_text(
            contact,
            ("Fullname", "full_name", "fullname", "name", "Name"),
            max_length=160,
        )
        title = _first_text(
            contact,
            ("Job_title", "job_title", "position", "Position", "title"),
            max_length=120,
        )
        if name and title:
            value = f"{name} ({title})"
        else:
            value = name or title
        if value and value not in rendered:
            rendered.append(value)

    if rendered:
        return "; ".join(rendered)

    return _first_text(
        raw,
        (
            "contact_person",
            "contact_name",
            "customer_contact",
            "responsible_person",
        ),
    )


def _address(raw: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in (
        "customer_street",
        "customer_address",
        "customer_district_name",
        "customer_region_name",
        "customer_zip",
    ):
        value = _clean_text(raw.get(key), max_length=220)
        if not value or value in {"0", "00000"} or value in parts:
            continue
        parts.append(value)

    if not parts:
        for key in (
            "delivering_address",
            "delivering_district_name",
            "delivering_region_name",
        ):
            value = _clean_text(raw.get(key), max_length=220)
            if value and value not in parts:
                parts.append(value)

    return "; ".join(parts) if parts else None


def extract_uzex_trade_list_contact_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Extract safe contact/submission hints available from TradeList rows."""
    if not isinstance(raw, dict):
        return {}

    metadata: dict[str, Any] = {}
    for target_key, source_keys in (
        ("buyer_agency", ("seller_name", "customer_name")),
        ("customer_tin", ("seller_tin", "customer_tin")),
        ("submission_deadline", ("end_date",)),
        ("question_deadline", ("clarific_date",)),
        ("uzex_display_no", ("display_no",)),
    ):
        value = _first_text(raw, source_keys)
        if value:
            metadata[target_key] = value
    return metadata


def extract_uzex_contact_info(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Extract whitelisted Contact & Submission fields from UzEx GetTrade."""
    if not isinstance(raw, dict):
        return {}

    metadata: dict[str, Any] = {}
    for target_key, source_keys in (
        ("buyer_agency", ("customer_name", "seller_name", "organization_name")),
        ("email", ("customer_email", "contact_email", "email", "mail")),
        (
            "phone",
            (
                "delivering_phone",
                "customer_phone",
                "contact_phone",
                "phone",
                "mobile_phone",
            ),
        ),
        ("submission_method", ("consider_procedure", "submission_method")),
        ("submission_deadline", ("end_date", "submission_deadline")),
        ("question_deadline", ("clarific_date", "question_deadline")),
        ("customer_tin", ("customer_tin", "seller_tin")),
    ):
        value = _first_text(raw, source_keys)
        if value:
            metadata[target_key] = value

    contact_person = _contact_person(raw)
    if contact_person:
        metadata["contact_person"] = contact_person

    address = _address(raw)
    if address:
        metadata["address"] = address

    metadata.setdefault(
        "document_access_notes",
        "Official tender documents are available from the UzEx source notice.",
    )
    metadata["uzex_contact_source"] = "GetTrade"
    return metadata
