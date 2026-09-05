"""
Validation script for the forensic TenderRequirement model.
"""

import asyncio

from pydantic import ValidationError

from app.core.agents import requirement_extractor as extractor
from app.core.agents.requirement_extractor import (
    EXTRACTOR_SCHEMA_VERSION,
    MAX_EXACT_QUOTE_WORDS,
    MAX_HEADLINE_WORDS,
    MAX_PAYLOAD_CHARS,
    MODEL_NAME,
    REQUIREMENT_RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    EvidenceValidationStatus,
    RequirementCategory,
    RequirementScope,
    ScopeReviewStatus,
    TenderRequirement,
    _build_extraction_prompt,
    _deduplicate_requirements,
    _split_traceable_payload_chunks,
    build_extraction_warnings,
    classify_requirement_scope,
    extract_requirements_with_coverage,
    validate_requirement_evidence,
)


print(f"Model: {MODEL_NAME}")
assert MODEL_NAME == "gemini-3.1-pro-preview"
assert EXTRACTOR_SCHEMA_VERSION == "requirement_extractor_scope_v5"

schema_props = list(REQUIREMENT_RESPONSE_SCHEMA["items"]["properties"].keys())
expected_fields = [
    "category",
    "headline",
    "source_filename",
    "source_page",
    "exact_quote",
]
assert schema_props == expected_fields, schema_props
assert REQUIREMENT_RESPONSE_SCHEMA["items"]["required"] == expected_fields


def expect_validation_error(**payload):
    try:
        TenderRequirement(**payload)
        raise AssertionError("Expected ValidationError")
    except ValidationError:
        pass


dq = TenderRequirement(
    category="DQ",
    headline="Construction License Required",
    source_filename="qualification.pdf",
    source_page=7,
    exact_quote="valid construction license",
)
assert dq.category == RequirementCategory.DQ
assert dq.headline == "Construction License Required"
assert dq.source_filename == "qualification.pdf"
assert dq.source_page == 7
assert dq.exact_quote == "valid construction license"
assert dq.is_dealbreaker is False
assert dq.raw_text_snippet == dq.exact_quote
assert dq.validation_status == EvidenceValidationStatus.NEEDS_REVIEW
assert dq.source_verified is False
assert dq.requirement_scope == RequirementScope.INFORMATIONAL
assert dq.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW
assert dq.affects_bid_eligibility is False

nice = TenderRequirement(
    category="NICE_TO_HAVE",
    headline="Similar Work Preferred",
    source_filename="criteria.pdf",
    source_page=3,
    exact_quote="similar work is preferred",
)
assert nice.category == RequirementCategory.NICE_TO_HAVE
assert nice.is_dealbreaker is False

compliant = TenderRequirement(
    category="COMPLIANT",
    headline="Electronic Submission Accepted",
    source_filename="instructions.pdf",
    source_page=1,
    exact_quote="submitted through the electronic portal",
)
assert compliant.category == RequirementCategory.COMPLIANT
assert compliant.is_dealbreaker is False

expect_validation_error(
    category="MANDATORY_LEGAL",
    headline="Legacy Category",
    source_filename="legacy.pdf",
    source_page=1,
    exact_quote="legacy category",
)
expect_validation_error(
    category="DQ",
    headline="Bad Page",
    source_filename="bad.pdf",
    source_page=0,
    exact_quote="bad page",
)
expect_validation_error(
    category="DQ",
    headline="Empty Filename",
    source_filename="",
    source_page=1,
    exact_quote="empty filename",
)
expect_validation_error(
    category="DQ",
    headline="Quote Too Long",
    source_filename="long.pdf",
    source_page=1,
    exact_quote=" ".join(f"word{i}" for i in range(MAX_EXACT_QUOTE_WORDS + 1)),
)
expect_validation_error(
    category="DQ",
    headline="Extra Field",
    source_filename="extra.pdf",
    source_page=1,
    exact_quote="extra field",
    confidence_score=0.99,
)
expect_validation_error(
    category="DQ",
    headline="Legacy Description Field",
    description="This field should fail.",
    source_filename="extra.pdf",
    source_page=1,
    exact_quote="extra field",
)

long_headline = TenderRequirement(
    category="COMPLIANT",
    headline="one two three four five six seven",
    source_filename="headline.pdf",
    source_page=1,
    exact_quote="headline quote",
)
assert long_headline.headline == "one two three four five..."
assert len(long_headline.headline.removesuffix("...").split()) == MAX_HEADLINE_WORDS

markerless_prompt = _build_extraction_prompt(
    "[archive.rar]\n[contract.docx]\nПоставщик обязуется поставить товар."
)
assert "[[FILE: contract.docx]]" in markerless_prompt
assert "[[PAGE 1]]" in markerless_prompt

assert "You are a forensic legal auditor for B2G procurement. You are mathematically precise." in SYSTEM_PROMPT
assert "reserved EXCLUSIVELY" in SYSTEM_PROMPT
assert "MUST be categorized as `NICE_TO_HAVE`" in SYSTEM_PROMPT
assert "DO NOT extract blank form fields" in SYSTEM_PROMPT
assert "Evidence-first extraction" in SYSTEM_PROMPT
assert "Do not force" in SYSTEM_PROMPT
assert "majority (approx. 80%)" not in SYSTEM_PROMPT
assert "exactly 1 or 2" not in SYSTEM_PROMPT
assert "[[FILE: filename.ext]]" in SYSTEM_PROMPT
assert "[[PAGE N]]" in SYSTEM_PROMPT
assert "COMPLIANT means verified non-risk evidence" in SYSTEM_PROMPT

source_text = """[[FILE: qualification.pdf]]
[[PAGE 7]]
The bidder must have a valid construction license before contract award.

[[FILE: criteria.pdf]]
[[PAGE 3]]
Similar work is preferred for evaluation.
"""

validated = validate_requirement_evidence(dq, source_text)
assert validated.validation_status == EvidenceValidationStatus.ACCEPTED
assert validated.source_verified is True
assert "Exact quote found" in validated.validation_reason
classified = classify_requirement_scope(validated, source_text)
assert classified.requirement_scope == RequirementScope.ELIGIBILITY
assert classified.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified.affects_bid_eligibility is True
assert classified.is_dealbreaker is True

normalized = TenderRequirement(
    category="NICE_TO_HAVE",
    headline="Similar Work Preferred",
    source_filename="criteria.pdf",
    source_page=3,
    exact_quote="similar work is preferred",
)
validated_normalized = validate_requirement_evidence(normalized, source_text)
assert validated_normalized.validation_status == EvidenceValidationStatus.ACCEPTED
assert validated_normalized.source_verified is True
assert "normalization" in validated_normalized.validation_reason

wrong_page = TenderRequirement(
    category="DQ",
    headline="Wrong Page",
    source_filename="qualification.pdf",
    source_page=2,
    exact_quote="valid construction license",
)
validated_wrong_page = validate_requirement_evidence(wrong_page, source_text)
assert validated_wrong_page.validation_status == EvidenceValidationStatus.NEEDS_REVIEW
assert validated_wrong_page.source_verified is False

unsupported = TenderRequirement(
    category="DQ",
    headline="Unsupported",
    source_filename="qualification.pdf",
    source_page=7,
    exact_quote="unlisted nuclear certificate",
)
validated_unsupported = validate_requirement_evidence(unsupported, source_text)
assert validated_unsupported.validation_status == EvidenceValidationStatus.REJECTED
assert validated_unsupported.source_verified is False

mixed_legacy_text = """[[FILE: markerized.pdf]]
[[PAGE 1]]
Verified markerized text.

[legacy.pdf]
legacy requirement text without parser provenance
"""
legacy_requirement = TenderRequirement(
    category="DQ",
    headline="Legacy Markerless",
    source_filename="legacy.pdf",
    source_page=1,
    exact_quote="legacy requirement text",
)
validated_legacy = validate_requirement_evidence(legacy_requirement, mixed_legacy_text)
assert validated_legacy.validation_status == EvidenceValidationStatus.REJECTED
assert validated_legacy.source_verified is False

warnings = build_extraction_warnings("x" * 130_000)
assert warnings == []

large_text = (
    "[[FILE: large.pdf]]\n"
    "[[PAGE 1]]\n"
    + ("filler text for early page only. " * 3_600)
    + "\n[[PAGE 2]]\n"
    + ("late-page context padding. " * 80)
    + "The bidder must hold late requirement license.\n"
)
assert large_text.find("late requirement license") > MAX_PAYLOAD_CHARS
large_chunks = _split_traceable_payload_chunks(large_text)
assert len(large_chunks) == 2
assert all("[[FILE: large.pdf]]" in chunk for chunk in large_chunks)
assert all("[[PAGE " in chunk for chunk in large_chunks)

duplicate_low = TenderRequirement(
    category="COMPLIANT",
    headline="License Mentioned",
    source_filename="large.pdf",
    source_page=2,
    exact_quote="late requirement license",
)
duplicate_high = TenderRequirement(
    category="DQ",
    headline="License Required",
    source_filename="large.pdf",
    source_page=2,
    exact_quote="late requirement license",
)
deduped = _deduplicate_requirements([duplicate_low, duplicate_high])
assert len(deduped) == 1
assert deduped[0].category == RequirementCategory.DQ

original_resolve_key = extractor._resolve_gemini_api_key
original_extract_sync = extractor._extract_requirements_sync


def fake_extract_sync(
    text_payload: str,
    api_key: str,
    analysis_language: object = "en",
) -> list[TenderRequirement]:
    assert len(text_payload) <= MAX_PAYLOAD_CHARS
    if "late requirement license" not in text_payload:
        return []
    return [
        TenderRequirement(
            category="DQ",
            headline="License Required",
            source_filename="large.pdf",
            source_page=2,
            exact_quote="late requirement license",
        )
    ]


try:
    extractor._resolve_gemini_api_key = lambda: "test-api-key"
    extractor._extract_requirements_sync = fake_extract_sync
    extraction_result = asyncio.run(extract_requirements_with_coverage(large_text))
finally:
    extractor._resolve_gemini_api_key = original_resolve_key
    extractor._extract_requirements_sync = original_extract_sync

assert len(extraction_result.requirements) == 1
assert extraction_result.requirements[0].source_chunk_index == 1
assert extraction_result.requirements[0].source_chunk_start_char is not None
assert extraction_result.requirements[0].source_chunk_end_char is not None
assert extraction_result.requirements[0].extraction_batch_id
assert extraction_result.coverage_metadata.coverage_status == "complete"
assert extraction_result.coverage_metadata.chunk_count == 2
assert extraction_result.coverage_metadata.chunks_failed == 0
assert extraction_result.coverage_metadata.coverage_warnings == []
assert "truncated" not in " ".join(
    extraction_result.coverage_metadata.coverage_warnings
).casefold()

late_validated = validate_requirement_evidence(
    extraction_result.requirements[0],
    large_text,
)
assert late_validated.validation_status == EvidenceValidationStatus.ACCEPTED
assert late_validated.source_verified is True
assert late_validated.source_chunk_index == 1

scope_text = """[[FILE: contract.pdf]]
[[PAGE 2]]
The successful bidder shall provide performance security before signing the contract.

[[FILE: bid.pdf]]
[[PAGE 4]]
Failure to submit performance security with the bid shall result in rejection.

[[FILE: technical.pdf]]
[[PAGE 8]]
The contractor shall provide monthly reports and as-built records during contract execution.

[[FILE: execution.pdf]]
[[PAGE 10]]
The Contractor shall not subcontract the whole of the Works.
The Contractor shall appoint an accident prevention officer at the Site.
The Contractor shall not appoint any proposed Subcontractor until the Subcontractors have been approved in writing by the Employer.
The Contractor shall prepare, and keep up-to-date, a complete set of "as-built" records of the execution.

[[FILE: ambiguous.pdf]]
[[PAGE 9]]
Mandatory performance security submission is required.
"""

post_award_security = TenderRequirement(
    category="DQ",
    headline="Performance Security",
    source_filename="contract.pdf",
    source_page=2,
    exact_quote="provide performance security",
)
classified_post_award = classify_requirement_scope(
    validate_requirement_evidence(post_award_security, scope_text),
    scope_text,
)
assert classified_post_award.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_post_award.requirement_scope == RequirementScope.POST_AWARD_OBLIGATION
assert classified_post_award.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_post_award.affects_bid_eligibility is False
assert classified_post_award.is_dealbreaker is False

bid_security = TenderRequirement(
    category="DQ",
    headline="Performance Security",
    source_filename="bid.pdf",
    source_page=4,
    exact_quote="performance security with the bid",
)
classified_bid_security = classify_requirement_scope(
    validate_requirement_evidence(bid_security, scope_text),
    scope_text,
)
assert classified_bid_security.requirement_scope == RequirementScope.FINANCIAL_SUBMISSION
assert classified_bid_security.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_bid_security.affects_bid_eligibility is True
assert classified_bid_security.is_dealbreaker is True

operational_technical = TenderRequirement(
    category="DQ",
    headline="Monthly Reports",
    source_filename="technical.pdf",
    source_page=8,
    exact_quote="monthly reports and as-built records",
)
classified_operational = classify_requirement_scope(
    validate_requirement_evidence(operational_technical, scope_text),
    scope_text,
)
assert classified_operational.requirement_scope == RequirementScope.CONTRACT_EXECUTION
assert classified_operational.affects_bid_eligibility is False
assert classified_operational.is_dealbreaker is False

subcontracting_restriction = TenderRequirement(
    category="DQ",
    headline="No Whole Subcontract",
    source_filename="execution.pdf",
    source_page=10,
    exact_quote="not subcontract the whole of the Works",
)
classified_subcontracting = classify_requirement_scope(
    validate_requirement_evidence(subcontracting_restriction, scope_text),
    scope_text,
)
assert classified_subcontracting.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_subcontracting.requirement_scope == RequirementScope.CONTRACT_EXECUTION
assert classified_subcontracting.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_subcontracting.affects_bid_eligibility is False
assert classified_subcontracting.is_dealbreaker is False

accident_officer = TenderRequirement(
    category="DQ",
    headline="Accident Prevention Officer",
    source_filename="execution.pdf",
    source_page=10,
    exact_quote="appoint an accident prevention officer at the Site",
)
classified_accident_officer = classify_requirement_scope(
    validate_requirement_evidence(accident_officer, scope_text),
    scope_text,
)
assert classified_accident_officer.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_accident_officer.requirement_scope == RequirementScope.CONTRACT_EXECUTION
assert classified_accident_officer.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_accident_officer.affects_bid_eligibility is False
assert classified_accident_officer.is_dealbreaker is False

subcontractor_approval = TenderRequirement(
    category="DQ",
    headline="Obtain Written Subcontractor Approval",
    source_filename="execution.pdf",
    source_page=10,
    exact_quote="until the Subcontractors have been approved in writing by the Employer",
)
classified_subcontractor_approval = classify_requirement_scope(
    validate_requirement_evidence(subcontractor_approval, scope_text),
    scope_text,
)
assert classified_subcontractor_approval.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_subcontractor_approval.requirement_scope == RequirementScope.CONTRACT_EXECUTION
assert classified_subcontractor_approval.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_subcontractor_approval.affects_bid_eligibility is False
assert classified_subcontractor_approval.is_dealbreaker is False

as_built_records = TenderRequirement(
    category="DQ",
    headline="Maintain As-Built Records",
    source_filename="execution.pdf",
    source_page=10,
    exact_quote='prepare, and keep up-to-date, a complete set of "as-built" records of the execution',
)
classified_as_built_records = classify_requirement_scope(
    validate_requirement_evidence(as_built_records, scope_text),
    scope_text,
)
assert classified_as_built_records.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_as_built_records.requirement_scope == RequirementScope.CONTRACT_EXECUTION
assert classified_as_built_records.scope_review_status == ScopeReviewStatus.ACCEPTED
assert classified_as_built_records.affects_bid_eligibility is False
assert classified_as_built_records.is_dealbreaker is False

ambiguous_security = TenderRequirement(
    category="DQ",
    headline="Performance Security",
    source_filename="ambiguous.pdf",
    source_page=9,
    exact_quote="Mandatory performance security submission",
)
classified_ambiguous = classify_requirement_scope(
    validate_requirement_evidence(ambiguous_security, scope_text),
    scope_text,
)
assert classified_ambiguous.validation_status == EvidenceValidationStatus.ACCEPTED
assert classified_ambiguous.source_verified is True
assert classified_ambiguous.requirement_scope == RequirementScope.POST_AWARD_OBLIGATION
assert classified_ambiguous.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW
assert classified_ambiguous.affects_bid_eligibility is False
assert classified_ambiguous.is_dealbreaker is False
assert "bid-stage eligibility impact is not explicit" in classified_ambiguous.eligibility_reason

print("All forensic extractor validator checks passed.")
