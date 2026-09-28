"""W1 regression: generated content must not become a customer's bid price."""

import json
import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.api.endpoints.proposals import (
    AIDraftResponse,
    PDFGenerateRequest,
    _export_scope_items,
    ai_draft_proposal,
    export_proposal_docx,
    generate_proposal_pdf,
    update_proposal,
)
from app.models.all_models import ProposalStatus
from app.schemas.proposal import ProposalItemUpdate, ProposalUpdate
from app.core.ai import (
    FILE_ANALYSIS_PROMPT,
    STRATEGIC_DRAFT_PROMPT,
    TENDER_ANALYSIS_PROMPT,
    StrategicDraftSchema,
    TenderAnalysisSchema,
    _validate_with_schema,
)


ROOT = Path(__file__).resolve().parent.parent


def test_analysis_and_draft_schema_reject_generated_commercial_values():
    for schema in (TenderAnalysisSchema, StrategicDraftSchema):
        assert not {"suggested_price", "estimated_cost_breakdown", "our_price"} & schema.model_fields.keys()
    for prompt in (TENDER_ANALYSIS_PROMPT, FILE_ANALYSIS_PROMPT):
        assert "estimated_cost_breakdown" not in prompt
        assert "suggested_price" not in prompt
    assert "without prices" in STRATEGIC_DRAFT_PROMPT

    model_output = json.dumps({
        "strategic_summary": "Scope only",
        "suggested_price": 850,
        "line_items": [{"name": "Delivery", "quantity": 1, "unit": "lot", "unit_price": 850, "total": 850}],
    })
    for response in (model_output, f"```json\n{model_output}\n```"):
        result = _validate_with_schema(response, StrategicDraftSchema)
        assert "suggested_price" not in result
        assert result["line_items"] == [{"name": "Delivery", "quantity": 1.0, "unit": "lot"}]
    assert "suggested_price" not in AIDraftResponse.model_fields


def test_historical_commercial_fields_are_scope_only_at_export_boundary():
    historical = {"our_price": 850, "grand_total": 850, "ai_items": [
        {"name": "Delivery", "quantity": 1, "unit": "lot", "unit_price": 850, "total": 850},
    ]}
    original = json.dumps(historical, sort_keys=True)
    assert _export_scope_items(historical) == [{"name": "Delivery", "quantity": 1, "unit": "lot"}]
    assert json.dumps(historical, sort_keys=True) == original
    assert PDFGenerateRequest(price=700, delivery_days=20).price == 700


def test_ai_draft_never_returns_or_persists_model_prices_and_preserves_history():
    historical = {"our_price": 850, "ai_items": [{"name": "Old", "unit_price": 850, "total": 850}]}
    tender = SimpleNamespace(compiled_master_text="Technical tender scope " * 12, budget=1000)
    proposal = SimpleNamespace(id=uuid4(), tender_id=uuid4(), tender=tender,
                               structured_data=historical.copy(), ai_confidence_score=0)
    user = SimpleNamespace(id=uuid4(), company_name="Fixture", name="Fixture",
                           core_services="", past_experience="")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(scalar_one_or_none=lambda: proposal),
        SimpleNamespace(scalar_one_or_none=lambda: None),
        SimpleNamespace(all=lambda: []),
    ]), commit=AsyncMock())
    generated = {"strategic_summary": "Scope", "delivery_days": "20 calendar days",
                 "suggested_price": 900,
                 "line_items": [{"name": "Delivery", "quantity": 1, "unit": "lot",
                                 "unit_price": 900, "total": 900}]}
    with patch("app.api.endpoints.proposals.is_tender_actionable", return_value=True), \
         patch("app.core.ai.draft_strategic_proposal_async", AsyncMock(return_value=generated)):
        response = asyncio.run(ai_draft_proposal(proposal.id, False, user, db))
    assert "suggested_price" not in response.model_dump()
    assert response.line_items[0].model_dump() == {"name": "Delivery", "quantity": 1.0, "unit": "lot"}
    assert proposal.structured_data["our_price"] == historical["our_price"]
    assert proposal.structured_data["ai_items"] == historical["ai_items"]
    assert "suggested_price" not in str(proposal.structured_data["price_free_draft"])
    assert "unit_price" not in str(proposal.structured_data["price_free_draft"])
    db.commit.assert_awaited_once()


def test_new_pdf_and_docx_use_only_explicit_price_with_historical_data_present():
    from docx import Document
    import pymupdf

    historical = {
        "our_price": 850,
        "grand_total": 850,
        "ai_items": [{"name": "Delivery", "quantity": 1, "unit": "lot", "unit_price": 850}],
        "strategic_summary": "Historical text",
        "price_free_draft": {"strategic_summary": "Current scope summary.",
                             "line_items": [{"name": "Delivery", "quantity": 1, "unit": "lot"}]},
    }
    original = json.dumps(historical, sort_keys=True)
    tender = SimpleNamespace(external_id="fixture", budget=1000, currency="USD")
    proposal = SimpleNamespace(id=uuid4(), tender=tender, structured_data=historical.copy(), status=None)
    user = SimpleNamespace(id=uuid4(), company_name="Fixture Company", director_name="Director", address="")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: proposal)),
                         commit=AsyncMock())
    request = PDFGenerateRequest(price=700, delivery_days=20, company_name="Fixture Company")

    async def exported_bytes(export):
        response = await export(proposal.id, request, user, db)
        return b"".join([chunk async for chunk in response.body_iterator])

    pdf_bytes = asyncio.run(exported_bytes(generate_proposal_pdf))
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        pdf_text = "\n".join(page.get_text() for page in document)
    docx_bytes = asyncio.run(exported_bytes(export_proposal_docx))
    document = Document(io.BytesIO(docx_bytes))
    docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    for output in (pdf_text, docx_text):
        assert "700" in output and "850" not in output
        assert "1,000" in output  # Separate authoritative Tender budget fact.
        assert "Current scope summary" in output and "Historical text" not in output
    assert json.dumps(historical, sort_keys=True) == original
    assert proposal.structured_data == historical


def test_explicit_manual_item_costs_remain_separate_from_source_budget():
    historical = {"our_price": 850, "ai_items": [{"name": "Old", "unit_price": 850}]}
    proposal = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), tender_id=uuid4(), status=ProposalStatus.DRAFT,
        ai_confidence_score=0, structured_data=historical.copy(), final_pdf_url=None,
        margin_percent=0, include_vat=False, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: proposal)),
                         commit=AsyncMock(), refresh=AsyncMock())
    update = ProposalUpdate(
        items=[ProposalItemUpdate(name="User scope", unit="lot", quantity=1, base_cost=100)],
        margin_percent=10, include_vat=True,
    )
    response = asyncio.run(update_proposal(proposal.id, update, SimpleNamespace(id=proposal.user_id), db))
    assert response.structured_data["our_price"] == 123.2
    assert response.structured_data["commercial_price_origin"] == "USER_ENTERED"
    assert response.structured_data["priced_items"][0]["unit_price"] == 110
    assert response.structured_data["ai_items"] == historical["ai_items"]


def test_structured_data_cannot_relabel_historical_price_as_user_entered():
    proposal = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), tender_id=uuid4(), status=ProposalStatus.DRAFT,
        ai_confidence_score=0, structured_data={"our_price": 850}, final_pdf_url=None,
        margin_percent=0, include_vat=False, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: proposal)),
                         commit=AsyncMock(), refresh=AsyncMock())
    incoming = {"our_price": 999, "commercial_price_origin": "USER_ENTERED", "note": "scope"}
    update = ProposalUpdate(structured_data=incoming)
    response = asyncio.run(update_proposal(proposal.id, update, SimpleNamespace(id=proposal.user_id), db))
    assert response.structured_data == {"our_price": 850, "note": "scope"}

    explicit = ProposalUpdate(structured_data=incoming, our_price=700)
    response = asyncio.run(update_proposal(proposal.id, explicit, SimpleNamespace(id=proposal.user_id), db))
    assert response.structured_data["our_price"] == 700
    assert response.structured_data["commercial_price_origin"] == "USER_ENTERED"


def test_active_routes_cannot_restore_budget_heuristics_or_reuse_stored_price():
    proposals = (ROOT / "backend/app/api/endpoints/proposals.py").read_text()
    ai = (ROOT / "backend/app/core/ai.py").read_text()
    assert "* 0.85" not in proposals and "* 0.75" not in proposals
    assert "suggested_price" not in proposals and "suggested_price" not in ai
    draft_route = proposals.split("async def ai_draft_proposal", 1)[1].split("async def upload_tender_tz", 1)[0]
    upload_route = proposals.split("async def upload_tender_tz", 1)[1].split("async def generate_proposal_pdf", 1)[0]
    for route in (draft_route, upload_route):
        assert 'current_data["our_price"]' not in route
        assert 'current_data["ai_items"]' not in route
    for export in ("generate_proposal_pdf", "export_proposal_docx"):
        route = proposals.split(f"async def {export}", 1)[1]
        assert "our_price = pdf_data.price" in route
        assert 'structured_data.get("our_price"' not in route
        assert 'item.get("unit_price"' not in route


def test_price_and_readiness_copy_have_truthful_active_labels():
    for locale in ("en", "uz", "ru", "ar"):
        catalog = ROOT / f"frontend/messages/{locale}"
        bid = json.loads((catalog / "bidPreparation.json").read_text())
        compliance = json.loads((catalog / "compliance.json").read_text())
        assert "enteredPrice" in bid and "suggestedPrice" not in bid
        assert "verified" not in compliance["workspace"]["readinessSupported"].lower()
    detail = (ROOT / "frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx").read_text()
    listing = (ROOT / "frontend/app/dashboard/bid-preparation/page.tsx").read_text()
    assert 'structured.commercial_price_origin === "USER_ENTERED"' in detail
    assert 'proposal.structured_data?.commercial_price_origin === "USER_ENTERED"' in listing
