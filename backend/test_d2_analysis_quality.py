"""D2 analysis quality: experience-match scope and two-pass SHORT-route extraction."""

from __future__ import annotations

import asyncio
from datetime import date
import threading
import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.agents import pursuit_analyzer as analyzer
from app.core.agents.pursuit_analyzer import ExtractedFact, NumericPredicate, SealedTextInput, VerifiedFact
from app.services import own_experience
from app.services.own_experience import EXPERIENCE_SCOPE, experience_scope, requirement_statement
from app.services.pursuit_analysis import _assess_requirement


# ---- A. experience-match scope ------------------------------------------------------------------
#
# Mongolia REOI OP00468882 wording, with the category/requirement_type the analyzer gave it in
# live d2_v1 runs. Financial capacity and certification do not occur in that notice; they use
# standard World Bank REOI wording.

GENUINE = [
    ("EXPERIENCE", "MINIMUM_THRESHOLD",
     "2. Specific Experience: Successful completion of at least two (2) contracts within the last ten (10) years "
     "involving the preparation of Detailed Engineering Designs for substations, overhead transmission lines, and "
     "cable lines rated at 110 kV or above, which shall have been approved by the relevant State Expert Review "
     "authority. Experience in projects financed by international financial institutions is an advantage."),
    ("EXPERIENCE", "QUALIFICATION",
     "Relevant experience in assignments of similar nature, scope, and complexity, particularly in detailed design "
     "of power transmission lines and substations."),
]
EXCLUDED = [
    (own_experience.SCOPE_LICENCE_LEGAL, "LEGAL_LICENSING", "QUALIFICATION",
     "3. Licensing Requirement: The firm shall hold valid licenses specified in Articles 8.1.3.1 and 8.1.14.7 of the "
     "Law of Mongolia on Permits (for high-complexity facility construction and engineering design)."),
    (own_experience.SCOPE_LICENCE_LEGAL, "LEGAL", "PERMIT",
     "3. Licensing Requirement: The firm shall hold valid licenses specified in Articles 8.1.3.1 and 8.1.14.7 of the "
     "Law of Mongolia on Permits (for high-complexity facility construction and engineering design)."),
    (own_experience.SCOPE_LICENCE_LEGAL, "CONSORTIUM", "LEGAL_REQUIREMENT",
     "Consultants may associate with other firms to enhance their qualifications but should indicate clearly whether "
     "the association is in the form of a joint venture and/or sub-consultancy."),
    (own_experience.SCOPE_FINANCIAL, "FINANCIAL", "QUALIFICATION",
     "Average annual turnover of at least USD 2 million over the last three years, supported by audited financial "
     "statements."),
    (own_experience.SCOPE_ORGANISATION, "TECHNICAL_CAPACITY", "QUALIFICATION",
     "4. Organizational and Technical Capability: Information demonstrating the firm's organizational structure, "
     "quality management systems, technical resources, professional capabilities and managerial capacity relevant "
     "to the assignment."),
    (own_experience.SCOPE_ORGANISATION, "TECHNICAL_CAPACITY", "QUALIFICATION",
     "Organizational capacity, availability of qualified personnel, quality assurance and monitoring approaches, and "
     "resources available to undertake the Services; and"),
    (own_experience.SCOPE_STAFFING, "PERSONNEL", "EVALUATION_CRITERIA",
     "Key Experts will not be evaluated at the shortlisting stage."),
    (own_experience.SCOPE_CORE_BUSINESS, "ADMINISTRATIVE", "QUALIFICATION",
     "Firm's core business, years in operation, and technical and managerial capabilities relevant to the assignment;"),
    (own_experience.SCOPE_CORE_BUSINESS, "EXPERIENCE", "MINIMUM_THRESHOLD",
     "1. General Experience: Minimum seven (7) years of continuous experience in the energy sector, with focus on the "
     "detailed engineering design of power transmission lines and substations."),
    (own_experience.SCOPE_CERTIFICATION, "QUALIFICATION", "CERTIFICATION",
     "The firm shall be certified to ISO 9001 for its quality management."),
    (own_experience.SCOPE_DOCUMENT, "DOCUMENTATION", "SUBMISSION_DOCUMENT",
     "Other supporting documentation demonstrating the firm's qualifications and experience, as appropriate."),
    (own_experience.SCOPE_DOCUMENT, "TECHNICAL", "REFERENCE",
     "The Bidder must submit a list of at least 3 professional references."),
]
# What the notice says around the requirements; it mentions "experience" and must never decide the scope.
CONTEXT = ("Interested firms must provide evidence demonstrating that they have the required qualifications and "
           "relevant experience to perform the Services, including:")


@pytest.mark.parametrize("category,requirement_type,quote", GENUINE)
def test_genuine_experience_requirements_are_in_scope(category, requirement_type, quote) -> None:
    assert experience_scope(category, requirement_type, requirement_statement(None, quote)) == EXPERIENCE_SCOPE


@pytest.mark.parametrize("scope,category,requirement_type,quote", EXCLUDED)
def test_every_excluded_class_is_out_of_scope(scope, category, requirement_type, quote) -> None:
    assert experience_scope(category, requirement_type, requirement_statement(None, quote)) == scope


def test_label_only_requirements_follow_the_vocabulary() -> None:
    # Included labels (category/requirement_type tokens): SIMILAR+ASSIGNMENT(S)/PROJECT(S)/CONTRACT(S),
    # TRACK+RECORD, PAST+PERFORMANCE, PROJECT/CORPORATE/SPECIFIC/FIRM+EXPERIENCE.
    for labels in (("ELIGIBILITY", "SIMILAR_ASSIGNMENTS"), ("QUALIFICATION", "TRACK_RECORD"),
                   ("EVALUATION", "PAST_PERFORMANCE"), ("EXPERIENCE", "CORPORATE_EXPERIENCE"),
                   ("Project Experience", "OTHER")):
        assert experience_scope(*labels, "") == EXPERIENCE_SCOPE, labels
    # "EXPERIENCE" alone, or references/terms of reference, are not enough without a statement saying so.
    for labels in (("EXPERIENCE", "QUALIFICATION"), ("SUBMISSION_REQUIREMENT", "REFERENCES"),
                   ("TERMS_OF_REFERENCE", "SCOPE")):
        assert experience_scope(*labels, "") != EXPERIENCE_SCOPE, labels


def _reference(**values):
    base = {"id": str(uuid4()), "project_name": "Detailed design of 110 kV substations and overhead lines",
            "client_name": "Grid PIU", "country": "Mongolia", "sector": "Energy", "service": "Detailed engineering design",
            "role": "LEAD", "start_date": "2020-03-01", "completion_date": "2022-11-30", "completion_state": "COMPLETED",
            "contract_value": None, "contract_currency": None, "value_basis": "UNKNOWN", "contract_share_percent": None,
            "relevant_scope": "Detailed engineering designs for substations and overhead transmission lines",
            "evidence_state": "UNVERIFIED", "evidence_basis": "METADATA_ONLY"}
    base.update(values)
    return base


def _requirement(category, requirement_type, quote, *, context=CONTEXT, predicate=None) -> ExtractedFact:
    return ExtractedFact(kind="CORPORATE_REQUIREMENT", original_quote=quote, normalized_text=quote, category=category,
                         requirement_type=requirement_type, stage_scope="SHORTLISTING", distinction="MANDATORY",
                         predicate=predicate, source_context=context)


def test_assessment_never_matches_references_outside_the_scope_even_with_experience_in_context() -> None:
    snapshot = {"own_project_references": [_reference()]}
    for _scope, category, requirement_type, quote in EXCLUDED:
        assessment = _assess_requirement(_requirement(category, requirement_type, quote), snapshot, as_of=date(2026, 10, 7))
        assert assessment.coverage != "PARTIAL" and not assessment.matched_reference_ids, quote
    contracts = _requirement(*GENUINE[0][:2], GENUINE[0][2], predicate=NumericPredicate(operator=">=", threshold=2, unit="contracts"))
    similar = _requirement(*GENUINE[1])
    for fact in (contracts, similar):
        assessment = _assess_requirement(fact, snapshot, as_of=date(2026, 10, 7))
        assert assessment.matched_reference_ids, fact.original_quote


# ---- B. two-pass extraction ---------------------------------------------------------------------

TEXT = (
    "Bidders must submit one printed copy and one electronic copy of the Proposal. "
    "The Bidder must submit a list of at least 3 professional references. "
    "The Proposal must not exceed 5 pages, excluding attachments. "
)
PRINTED = "Bidders must submit one printed copy and one electronic copy of the Proposal."
PRINTED_SHORT = "one printed copy and one electronic copy"
REFERENCES = "The Bidder must submit a list of at least 3 professional references."
PAGES = "The Proposal must not exceed 5 pages, excluding attachments."


def _fact(quote: str, **values) -> ExtractedFact:
    base = dict(kind="CORPORATE_REQUIREMENT", original_quote=quote, normalized_text=quote, category="TECHNICAL",
                requirement_type="REQUIRED_DOCUMENT", stage_scope="BID_SUBMISSION", distinction="MANDATORY")
    base.update(values)
    return ExtractedFact(**base)


def _note(quote: str) -> ExtractedFact:
    return _fact(quote, category="ADMINISTRATIVE", requirement_type="SUBMISSION_INSTRUCTION")


def _verified(item_id, quote: str, fact: ExtractedFact | None = None) -> VerifiedFact:
    start = TEXT.index(quote)
    return VerifiedFact(item_id, fact or _fact(quote), start, start + len(quote), None, 1)


def test_union_keeps_first_pass_order_appends_gains_and_drops_overlaps() -> None:
    item = uuid4()
    first = [_verified(item, PRINTED_SHORT), _verified(item, REFERENCES)]
    second = [_verified(item, PRINTED), _verified(item, REFERENCES), _verified(item, PAGES)]
    union, counts = analyzer.union_verified_facts([first, second])
    # The longer verified quote replaces the shorter in place; the identical one is a duplicate; PAGES is new.
    assert [fact.fact.original_quote for fact in union] == [PRINTED, REFERENCES, PAGES]
    assert counts == {"union_gain": 1, "union_replaced": 1, "union_duplicates_removed": 2}


def test_union_ties_keep_the_first_pass_and_other_items_or_kinds_never_merge() -> None:
    item, other = uuid4(), uuid4()
    first = [_verified(item, REFERENCES, _fact(REFERENCES, normalized_text="First pass wording"))]
    second = [
        _verified(item, REFERENCES, _fact(REFERENCES, normalized_text="Second pass wording")),  # tie
        _verified(other, REFERENCES),  # another pack item
    ]
    union, counts = analyzer.union_verified_facts([first, second])
    assert [(fact.pack_item_id, fact.fact.normalized_text) for fact in union] == [
        (item, "First pass wording"), (other, REFERENCES)]
    assert counts["union_gain"] == 1 and counts["union_duplicates_removed"] == 1
    # Overlap below 60% of the shorter span is two facts.
    start = TEXT.index("Bidders must submit")
    narrow = VerifiedFact(item, _fact("Bidders must submit one"), start, start + 23, None, 1)
    wide = VerifiedFact(item, _fact("x"), start + 12, start + 60, None, 1)
    assert len(analyzer.union_verified_facts([[narrow], [wide]])[0]) == 2


def test_a_note_in_one_pass_and_a_requirement_in_the_other_keeps_the_requirement() -> None:
    item = uuid4()
    note_first = analyzer.union_verified_facts([[_verified(item, PRINTED, _note(PRINTED))],
                                                [_verified(item, PRINTED_SHORT)]])[0]
    assert [fact.fact.requirement_type for fact in note_first] == ["REQUIRED_DOCUMENT"]  # even though shorter
    requirement_first = analyzer.union_verified_facts([[_verified(item, PRINTED_SHORT)],
                                                       [_verified(item, PRINTED, _note(PRINTED))]])[0]
    assert [fact.fact.requirement_type for fact in requirement_first] == ["REQUIRED_DOCUMENT"]


@pytest.fixture
def short_route(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "SHORT_PASSES", 2)
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 1)


def _chunk_facts(*facts: ExtractedFact) -> analyzer.ChunkFacts:
    return analyzer.ChunkFacts(list(facts), {"model_name": analyzer.MODEL_NAME, "attempts": 1})


def test_short_route_runs_two_concurrent_passes_unites_and_reports_diagnostics(short_route, monkeypatch) -> None:
    lock = threading.Lock()
    state = {"running": 0, "peak": 0, "passes": []}

    def stub(item, chunk, language, api_key, models=None):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            state["passes"].append(analyzer.CURRENT_PASS.get())
        time.sleep(0.05)
        with lock:
            state["running"] -= 1
        if analyzer.CURRENT_PASS.get() == 1:
            return _chunk_facts(_fact(REFERENCES), _fact("not in the text"))  # one fails the quote check
        return _chunk_facts(_fact(PRINTED), _fact(REFERENCES))

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))
    assert state["peak"] == 2 and sorted(state["passes"]) == [1, 2]  # one call per pass, side by side
    assert [fact.fact.original_quote for fact in result] == [REFERENCES, PRINTED]
    d = result.diagnostics
    assert (d["pass_count"], d["passes_completed"]) == (2, 2)
    assert (d["union_gain"], d["union_replaced"], d["union_duplicates_removed"]) == (1, 0, 1)
    first, second = d["passes"]
    assert (first["pass"], first["status"], first["raw_requirement_count"], first["verified_count"],
            first["provenance_rejected_count"]) == (1, "COMPLETED", 2, 1, 1)
    assert (second["pass"], second["status"], second["raw_requirement_count"], second["verified_count"]) == (2, "COMPLETED", 2, 2)
    assert all(isinstance(record["latency_ms"], int) for record in d["passes"])
    # Top-level counters describe the first pass; verified counts describe the union.
    assert (d["raw_requirement_count"], d["provenance_rejected_count"], d["verified_requirement_count"]) == (2, 1, 2)
    assert d["chunk_count"] == 1 and len(second["chunks"]) == 1
    assert analyzer.PIPELINE_VERSION == "pursuit_analysis_pipeline_d2_v2"


def test_a_failed_second_pass_is_recorded_and_does_not_fail_the_run(short_route, monkeypatch) -> None:
    def stub(item, chunk, language, api_key, models=None):
        if analyzer.CURRENT_PASS.get() == 2:
            raise analyzer.EXTRACTED_FACTS.validate_json("{not json")
        return _chunk_facts(_fact(REFERENCES))

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))
    assert [fact.fact.original_quote for fact in result] == [REFERENCES]
    d = result.diagnostics
    assert (d["pass_count"], d["passes_completed"], d["union_gain"]) == (2, 1, 0)
    assert d["passes"][1]["status"] == "FAILED" and d["passes"][1]["failure_class"] == "ValidationError"
    assert d["primary_pass"] == 1 and d["passes_failed"] == [{"pass": 2, "failure_class": "ValidationError"}]


def test_a_first_pass_timeout_with_a_completed_second_pass_uses_pass_2(short_route, monkeypatch) -> None:
    # INT-5: seen in the Deploy 2 rehearsal: pass 1 timed out twice while pass 2 completed.
    import requests

    def stub(item, chunk, language, api_key, models=None):
        if analyzer.CURRENT_PASS.get() == 1:
            raise requests.exceptions.ReadTimeout("read timed out (read timeout=90)")
        return _chunk_facts(_fact(PRINTED), _fact(REFERENCES))

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))
    assert [fact.fact.original_quote for fact in result] == [PRINTED, REFERENCES]  # pass 2's verified facts
    d = result.diagnostics
    assert (d["pass_count"], d["passes_completed"], d["primary_pass"]) == (2, 1, 2)
    assert d["passes_succeeded"] == [2] and d["passes_failed"] == [{"pass": 1, "failure_class": "ReadTimeout"}]
    assert d["passes"][0]["status"] == "FAILED" and d["passes"][1]["status"] == "COMPLETED"
    # top-level counters describe the primary (completed) pass
    assert (d["raw_requirement_count"], d["verified_requirement_count"], d["chunk_count"]) == (2, 2, 1)
    assert "chunks" not in d["passes"][1] and d["union_gain"] == 0


def test_when_every_pass_fails_the_run_fails_with_pass_1s_failure(short_route, monkeypatch) -> None:
    def stub(item, chunk, language, api_key, models=None):
        if analyzer.CURRENT_PASS.get() == 1:
            raise analyzer.EXTRACTED_FACTS.validate_json("{not json")
        raise TimeoutError("pass 2 timed out")

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    with pytest.raises(ValidationError):  # classified exactly as a single-pass failure
        asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))


def test_when_both_passes_complete_the_diagnostics_name_both(short_route, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "_extract_chunk_sync", lambda *args, **kwargs: _chunk_facts(_fact(REFERENCES)))
    d = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en")).diagnostics
    assert (d["primary_pass"], d["passes_succeeded"], d["passes_failed"]) == (1, [1, 2], [])
    assert d["union_duplicates_removed"] == 1  # the union is unchanged: identical facts dedupe


def test_the_long_route_and_one_configured_pass_run_a_single_pass(short_route, monkeypatch) -> None:
    calls: list[int] = []

    def stub(item, chunk, language, api_key, models=None):
        calls.append(analyzer.CURRENT_PASS.get())
        return _chunk_facts()

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    monkeypatch.setattr(analyzer, "LONG_PACK_CHARACTERS", 10)  # TEXT is a LONG pack now
    result = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))
    assert result.diagnostics["route"] == "LONG" and result.diagnostics["pass_count"] == 1 and set(calls) == {1}
    monkeypatch.setattr(analyzer, "LONG_PACK_CHARACTERS", 60_000)
    monkeypatch.setattr(analyzer, "SHORT_PASSES", 1)
    calls.clear()
    result = asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "rfp.txt", TEXT)], "en"))
    assert result.diagnostics["pass_count"] == 1 and calls == [1] and result.diagnostics["union_gain"] == 0


def test_the_pass_count_comes_from_the_environment() -> None:
    # A fresh interpreter: reloading the module here would replace classes other modules hold.
    import os
    import subprocess
    import sys

    def passes(value: str | None) -> int:
        env = {key: item for key, item in os.environ.items() if key != "PURSUIT_ANALYSIS_SHORT_PASSES"}
        if value is not None:
            env["PURSUIT_ANALYSIS_SHORT_PASSES"] = value
        output = subprocess.run(
            [sys.executable, "-c", "from app.core.agents import pursuit_analyzer as a; print(a.SHORT_PASSES)"],
            env=env, capture_output=True, text=True, check=True,
        ).stdout
        return int(output.strip().splitlines()[-1])

    assert (passes(None), passes("3"), passes("0")) == (2, 3, 1)  # default 2, at least one
