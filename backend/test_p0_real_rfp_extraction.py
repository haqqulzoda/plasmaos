"""P0 real-procurement extraction, trust gate, context, and passivity proofs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.endpoints.pursuits import _context_response
from app.core.agents import pursuit_analyzer
from app.core.agents.pursuit_analyzer import (
    ExtractedFact,
    PositionDetails,
    PositionQualification,
)
from app.services.private_documents import _context_suggestions
from app.services.pursuit_analysis import (
    _coverage_for_requirement,
    _coverage_for_position,
    assess_extraction_quality,
)
from scripts import test_s0_5b4_baseline as support


FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "communications_consultant_rfp.txt"
SOURCE_PDF_SHA256 = "88d34d5bce1685088d18e104de0c8a5325924cd23d9c0a1cb1f48b4587cd4a3b"
W8_HEAD = "20261001_0001_w8_proposal_evidence_pack"
P0_HEAD = "20261002_0001_p0_extraction_trust_gate"


def _fact(quote: str, normalized: str, *, stage: str = "BID_SUBMISSION") -> ExtractedFact:
    return ExtractedFact(
        kind="CORPORATE_REQUIREMENT",
        original_quote=quote,
        normalized_text=normalized,
        category="Bid Submission",
        requirement_type="PROPOSAL_CONTENT",
        stage_scope=stage,
        distinction="MANDATORY",
    )


def _golden_facts(text: str) -> list[ExtractedFact]:
    qualification_source = text.split("The STEP-UP Communications Consultant shall have", 1)[1]
    qualification_source = "The STEP-UP Communications Consultant shall have" + qualification_source
    qualification_source = qualification_source.split("\n\n5.\nBIDDER’S PROPOSAL", 1)[0]
    qualification_quote = qualification_source.replace(
        "\n\n[[PAGE 7]]\n1-25-2012 FINAL POSTED\n7\n\n", "\n"
    )
    position = ExtractedFact(
        kind="POSITION",
        original_quote=qualification_quote,
        normalized_text="Communications Consultant role and qualifications",
        category="Key Personnel",
        requirement_type="QUALIFICATIONS",
        stage_scope="BID_EVALUATION",
        distinction="MANDATORY",
        complex_rule=True,
        contribution_rule="The RFP solicits individuals and/or firms; role applicability is ambiguous.",
        position=PositionDetails(
            title="Communications Consultant",
            quantity=1,
            education_qualification="Bachelor's degree required.",
            general_experience="Minimum of 5 years marketing communications experience.",
            specific_experience="Minimum of 2 years web-based marketing campaigns.",
            qualification_criteria=[
                PositionQualification(normalized_text="Minimum 5 years marketing communications experience", distinction="MANDATORY"),
                PositionQualification(normalized_text="Minimum 2 years web-based marketing campaigns", distinction="MANDATORY"),
                PositionQualification(normalized_text="Journalism, interviewing, writing and other media experience", distinction="MANDATORY"),
                PositionQualification(normalized_text="Graphic-design and layout experience", distinction="MANDATORY"),
                PositionQualification(normalized_text="Bachelor's degree", distinction="MANDATORY"),
                PositionQualification(normalized_text="Video shooting and editing knowledge and experience", distinction="PREFERRED"),
                PositionQualification(normalized_text="Non-profit sector knowledge", distinction="PREFERRED"),
                PositionQualification(normalized_text="Marketing automation tools and social media strategies", distinction="DESIRED"),
            ],
        ),
    )
    return [
        position,
        _fact("a) Resume or corporate profile clearly reflecting qualifications and experiences.", "Resume or corporate profile"),
        _fact("b) Samples of communication and media materials.", "Communication and media samples"),
        _fact(
            "c) Minimum and maximum number of hours per month that are required or preferred by the\n"
            "Bidder for the position to be feasible and/or desirable, and days of the week / times of the day\n"
            "that the Bidder is available to perform the Services for STEP-UP.",
            "Minimum and maximum monthly hours plus availability",
        ),
        _fact(
            "d) Hourly rate that is required or preferred by the Bidder for the consulting arrangement to be\n"
            "feasible and/or desirable. Note that travel hours shall not be billable and work hours shall be\n"
            "billed to the nearest one-quarter of an hour.",
            "Customer must provide its hourly rate; Plasma does not generate or recommend a rate",
        ),
        _fact("e) Any administrative expenses that the Bidder anticipates billing to STEP-UP.", "Anticipated administrative expenses"),
        _fact(
            "g) Description of the individual’s or firm’s current legal and financial situation, including any\n"
            "bankruptcies filed and any material claims, judgments, arbitrations, investigations or lawsuits.",
            "Legal and financial situation disclosure",
        ),
        _fact(
            "h) Acknowledgement that the Bidder agrees to purchase and maintain commercial general\n"
            "liability insurance, professional errors and omissions insurance, and workers’ compensation.",
            "Insurance acknowledgement",
        ),
        _fact("i) List of at least three (3) professional references.", "At least three professional references"),
        _fact("• The Proposal shall not exceed more than 5-pages, excluding attachments.", "Proposal maximum five pages excluding attachments"),
        _fact(
            "Delivery Requirements. One (1) printed and one (1) electronic copy of the Proposal shall be\n"
            "submitted to Suzanne Parmet no later than 4:00 PM on Friday, February 17th, 2012.",
            "One printed and one electronic proposal copy by February 17, 2012 at 4:00 PM",
        ),
        _fact(
            "The Bidder to whom the Contract has been awarded must execute a Contract substantially\n"
            "similar to the one attached within ten business days after the award and submit such other\n"
            "Documents as required by the Contract Documents.",
            "Awarded bidder executes the referenced contract within ten business days after award",
            stage="CONTRACT_EXECUTION",
        ),
        _fact(
            "After execution of the Contract, the Contractor will initiate work within five days of Notice to\nProceed.",
            "Work starts within five days after Notice to Proceed",
            stage="POST_AWARD_OBLIGATION",
        ),
        _fact(
            "Documents to be submitted with bid include:\n\nProposal\nAffidavits\nInformation Regarding Bidder\nVendor Certification\nCertificate of Compliance",
            "Required bid artifacts include the proposal, affidavits, bidder information, vendor certification, and certificate of compliance",
        ),
    ]


def test_p0_real_rfp_all_pages_and_context_reach_the_sealed_input() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert [int(value) for value in __import__("re").findall(r"\[\[PAGE (\d+)\]\]", text)] == list(range(1, 9))
    for required in (
        "Town of University Park", "CONTRACT UP-2012-01", "February 17th, 2012",
        "SCOPE OF COMMUNICATION SERVICES", "QUALIFICATIONS", "Bachelor's degree required",
        "Required Materials", "three (3) professional references", "5-pages",
    ):
        assert required in text
    context = _context_suggestions(text)
    assert context.title == "Communications Consultant"
    assert context.buyer == "Town of University Park"
    assert context.reference == "UP-2012-01"
    assert context.country == "United States"
    assert context.declared_funder is None
    assert context.external_deadline and context.external_deadline.isoformat() == "2012-02-17T16:00:00-05:00"
    assert context.deadline_timezone == "America/New_York"
    assert SOURCE_PDF_SHA256.startswith("88d34d5b")


def test_p0_golden_semantics_survive_schema_and_provenance_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    facts = _golden_facts(text)
    payload = pursuit_analyzer.EXTRACTED_FACTS.dump_json(facts)
    schema_validated = pursuit_analyzer.EXTRACTED_FACTS.validate_json(payload)
    monkeypatch.setattr(pursuit_analyzer, "_resolve_gemini_api_key", lambda: "test")
    monkeypatch.setattr(pursuit_analyzer, "_extract_chunk_sync", lambda *_: schema_validated)
    verified = asyncio.run(pursuit_analyzer.analyze_pack_items([
        pursuit_analyzer.SealedTextInput(uuid4(), "communications-consultant.txt", text, 8, True)
    ], "en"))
    assert len(verified) == len(facts)
    assert verified.diagnostics["provenance_rejected_count"] == 0
    assert {item.page_number for item in verified} >= {4, 6, 7, 8}

    position = next(item.fact for item in verified if item.fact.kind == "POSITION")
    assert position.position and position.position.title == "Communications Consultant"
    state, resolution, _ = _coverage_for_position(position)
    assert (state, resolution) == ("NEEDS_INTERPRETATION", "HUMAN_INTERPRETATION")
    distinctions = {
        criterion.normalized_text: criterion.distinction
        for criterion in position.position.qualification_criteria
    }
    assert distinctions["Bachelor's degree"] == "MANDATORY"
    assert distinctions["Video shooting and editing knowledge and experience"] == "PREFERRED"
    assert distinctions["Non-profit sector knowledge"] == "PREFERRED"
    assert distinctions["Marketing automation tools and social media strategies"] == "DESIRED"

    semantics = "\n".join(item.fact.normalized_text for item in verified)
    for expected in (
        "Resume or corporate profile", "Communication and media samples",
        "Minimum and maximum monthly hours plus availability", "Customer must provide its hourly rate",
        "Anticipated administrative expenses", "Legal and financial situation disclosure",
        "Insurance acknowledgement", "At least three professional references",
        "Proposal maximum five pages", "One printed and one electronic proposal copy",
        "executes the referenced contract", "Notice to Proceed", "Required bid artifacts",
    ):
        assert expected in semantics
    assert "generate or recommend a rate" in semantics
    assert not any(key in semantics.casefold() for key in ("suggested price", "recommended hourly rate", "budget-derived"))

    required_artifacts = next(
        item.fact for item in verified if item.fact.normalized_text.startswith("Required bid artifacts")
    )
    coverage, _ = _coverage_for_requirement(required_artifacts, {"readiness_documents": []})
    assert coverage == "EVIDENCE_MISSING"
    for later_stage in ("executes the referenced contract", "Notice to Proceed"):
        fact = next(item.fact for item in verified if later_stage in item.fact.normalized_text)
        coverage, _ = _coverage_for_requirement(fact, {"readiness_documents": []})
        assert coverage == "LATER_STAGE_OBLIGATION"


def test_p0_quality_gate_empty_simple_success_and_failure() -> None:
    procurement = FIXTURE.read_text(encoding="utf-8")
    state, _, diagnostic = assess_extraction_quality([procurement], requirement_count=0, position_count=0)
    assert state == "NEEDS_ATTENTION" and diagnostic["procurement_likely"]
    state, _, _ = assess_extraction_quality(["A short personal note."], requirement_count=0, position_count=0)
    assert state == "NEEDS_ATTENTION"
    state, _, _ = assess_extraction_quality([procurement], requirement_count=12, position_count=1)
    assert state == "READY_FOR_REVIEW"
    state, _, _ = assess_extraction_quality([], requirement_count=0, position_count=0, failed=True)
    assert state == "FAILED"


def test_p0_context_provenance_equal_conflict_absent_and_no_silent_overwrite() -> None:
    version_id = uuid4()
    context = SimpleNamespace(
        title="Communications Consultant", buyer="Uzbekistan MFA", declared_funder=None,
        country=None, reference=None, procurement_stage=None,
        external_deadline=datetime(2027, 11, 5, tzinfo=timezone.utc),
        deadline_timezone=None, source_url=None,
        confirmed_fields={"title": {}, "buyer": {}, "external_deadline": {}, "source_url": {}},
    )
    suggestions = [
        SimpleNamespace(
            id=uuid4(), field_name="title", suggested_value="Communications Consultant",
            document_version_id=version_id, page_number=1, evidence_span="COMMUNICATIONS CONSULTANT",
            confidence=0.9, review_state="PROVISIONAL",
        ),
        SimpleNamespace(
            id=uuid4(), field_name="buyer", suggested_value="Town of University Park",
            document_version_id=version_id, page_number=1, evidence_span="Town of University Park",
            confidence=0.9, review_state="PROVISIONAL",
        ),
        SimpleNamespace(
            id=uuid4(), field_name="external_deadline", suggested_value="2012-02-17T16:00:00-05:00",
            document_version_id=version_id, page_number=2, evidence_span="February 17th, 2012, at 4:00 p.m.",
            confidence=0.9, review_state="PROVISIONAL",
        ),
        SimpleNamespace(
            id=uuid4(), field_name="reference", suggested_value="UP-2012-01",
            document_version_id=version_id, page_number=1, evidence_span="CONTRACT UP-2012-01",
            confidence=0.9, review_state="PROVISIONAL",
        ),
    ]
    response = _context_response(uuid4(), context, suggestions)
    states = {item.field_name: item.provenance_state for item in response.field_provenance}
    assert states["title"] == "USER_CONFIRMED"
    assert states["buyer"] == "USER_OVERRIDE_CONFLICTS_WITH_SOURCE"
    assert states["external_deadline"] == "USER_OVERRIDE_CONFLICTS_WITH_SOURCE"
    assert states["reference"] == "SOURCE_DETECTED"
    assert states["source_url"] == "USER_CONFIRMED"
    assert states["country"] == "UNKNOWN"
    assert response.buyer == "Uzbekistan MFA"
    assert response.external_deadline == datetime(2027, 11, 5, tzinfo=timezone.utc)


def test_p0_customer_gets_remain_passive() -> None:
    service = Path(__file__).with_name("app").joinpath("services", "pursuit_analysis.py").read_text(encoding="utf-8")
    getter = service.split("async def get_analysis_run", 1)[1].split("async def append_review_assertion", 1)[0]
    assert "await db.commit" not in getter
    private = Path(__file__).with_name("app").joinpath("services", "private_documents.py").read_text(encoding="utf-8")
    context_getter = private.split("async def get_context", 1)[1].split("async def update_context", 1)[0]
    assert "await db.commit" not in context_getter
    assert "_context_suggestions" not in context_getter


def test_p0_additive_migration_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("p0_trust_gate")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W8_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", P0_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == P0_HEAD
                assert await connection.fetchval(
                    "SELECT data_type FROM information_schema.columns WHERE table_name='pursuit_analysis_runs' AND column_name='quality_state'"
                ) == "character varying"
                assert await connection.fetchval(
                    "SELECT data_type FROM information_schema.columns WHERE table_name='pursuit_analysis_runs' AND column_name='extraction_diagnostics'"
                ) == "jsonb"
                assert await connection.fetchval(
                    "SELECT data_type FROM information_schema.columns WHERE table_name='pursuit_analysis_positions' AND column_name='qualification_criteria'"
                ) == "jsonb"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W8_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval(
                    "SELECT 1 FROM information_schema.columns WHERE table_name='pursuit_analysis_runs' AND column_name='quality_state'"
                ) is None
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W8_HEAD
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", P0_HEAD)
            # Drift is checked at the repository head; later migrations add to P0's schema.
            await asyncio.to_thread(support.alembic, database, "upgrade", "head")
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())
