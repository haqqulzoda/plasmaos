"""UzEx source-scope helpers for enterprise tender filtering."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, and_, cast, func, or_

from app.services.tender_sources.uzex_constants import (
    UZEX_ENTERPRISE_ROUTE,
    UZEX_ENTERPRISE_TYPE_ID,
    UZEX_SMALL_SCALE_ROUTE,
)


def uzex_source_metadata(*, type_id: int = UZEX_ENTERPRISE_TYPE_ID) -> dict[str, Any]:
    """Persist enough route context to keep UzEx tender scope auditable."""
    route = UZEX_ENTERPRISE_ROUTE if type_id == UZEX_ENTERPRISE_TYPE_ID else UZEX_SMALL_SCALE_ROUTE
    return {
        "uzex_type_id": type_id,
        "source_route": route,
        "source_list_url": f"https://etender.uzex.uz{route}0",
    }


def uzex_small_scale_tender_condition(tender_model: Any):
    """SQLAlchemy predicate matching route-tagged small-scale UzEx tenders."""
    source_url_text = func.lower(func.coalesce(tender_model.source_url, ""))
    metadata_text = func.lower(func.coalesce(cast(tender_model.source_metadata_json, Text), ""))
    return and_(
        tender_model.source_system == "uzex",
        or_(
            source_url_text.like(f"%{UZEX_SMALL_SCALE_ROUTE}%"),
            metadata_text.like(f"%{UZEX_SMALL_SCALE_ROUTE}%"),
            metadata_text.like('%"uzex_type_id": 1%'),
            metadata_text.like('%"uzex_type_id":1%'),
            metadata_text.like('%"type_id": 1%'),
            metadata_text.like('%"type_id":1%'),
            metadata_text.like('%"typeid": 1%'),
            metadata_text.like('%"typeid":1%'),
            metadata_text.like('%"uzex_type_id": "1"%'),
            metadata_text.like('%"uzex_type_id":"1"%'),
            metadata_text.like('%"type_id": "1"%'),
            metadata_text.like('%"type_id":"1"%'),
            metadata_text.like('%"typeid": "1"%'),
            metadata_text.like('%"typeid":"1"%'),
        ),
    )


def uzex_enterprise_tender_condition(tender_model: Any):
    """SQLAlchemy predicate matching route-tagged enterprise UzEx tenders."""
    source_url_text = func.lower(func.coalesce(tender_model.source_url, ""))
    metadata_text = func.lower(func.coalesce(cast(tender_model.source_metadata_json, Text), ""))
    return and_(
        tender_model.source_system == "uzex",
        or_(
            source_url_text.like(f"%{UZEX_ENTERPRISE_ROUTE}%"),
            metadata_text.like(f"%{UZEX_ENTERPRISE_ROUTE}%"),
            metadata_text.like('%"uzex_type_id": 2%'),
            metadata_text.like('%"uzex_type_id":2%'),
            metadata_text.like('%"type_id": 2%'),
            metadata_text.like('%"type_id":2%'),
            metadata_text.like('%"typeid": 2%'),
            metadata_text.like('%"typeid":2%'),
            metadata_text.like('%"uzex_type_id": "2"%'),
            metadata_text.like('%"uzex_type_id":"2"%'),
            metadata_text.like('%"type_id": "2"%'),
            metadata_text.like('%"type_id":"2"%'),
            metadata_text.like('%"typeid": "2"%'),
            metadata_text.like('%"typeid":"2"%'),
        ),
    )


def customer_visible_tender_condition(tender_model: Any):
    """Customer corpus guard: keep non-UzEx sources and confirmed enterprise UzEx."""
    return or_(
        tender_model.source_system != "uzex",
        uzex_enterprise_tender_condition(tender_model),
    )
