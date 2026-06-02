"""
Validation script for forensic requirement categories in compliance engine.
"""

from datetime import date, timedelta
from types import SimpleNamespace

from app.core.agents.requirement_extractor import (
    EvidenceValidationStatus,
    RequirementScope,
    ScopeReviewStatus,
    TenderRequirement,
)
from app.services.compliance_engine import (
    ComplianceVerdictStatus,
    MatchMethod,
    MatchVerdict,
    evaluate_tender_compliance,
)


profile = SimpleNamespace(
    id="profile-1",
    certifications=[],
    licenses=[],
)


def scoped(
    req: TenderRequirement,
    *,
    scope: RequirementScope = RequirementScope.ELIGIBILITY,
    scope_review_status: ScopeReviewStatus = ScopeReviewStatus.ACCEPTED,
    affects_bid_eligibility: bool = True,
) -> TenderRequirement:
    return req.model_copy(
        update={
            "validation_status": EvidenceValidationStatus.ACCEPTED,
            "validation_reason": "Exact quote found in cited source page.",
            "source_verified": True,
            "requirement_scope": scope,
            "scope_review_status": scope_review_status,
            "affects_bid_eligibility": affects_bid_eligibility,
            "eligibility_reason": "Test scope classification.",
        }
    )

requirements = [
    scoped(
        TenderRequirement(
            category="COMPLIANT",
            headline="Electronic Submission Supported",
            source_filename="instructions.pdf",
            source_page=1,
            exact_quote="electronic tender submission",
        ),
        scope=RequirementScope.INFORMATIONAL,
        affects_bid_eligibility=False,
    ),
    scoped(
        TenderRequirement(
            category="NICE_TO_HAVE",
            headline="Similar Experience Preferred",
            source_filename="criteria.pdf",
            source_page=2,
            exact_quote="similar experience is preferred",
        ),
        scope=RequirementScope.INFORMATIONAL,
        affects_bid_eligibility=False,
    ),
]

result = evaluate_tender_compliance(requirements, profile)
assert result.is_eligible is True
assert result.failed_count == 0
assert result.manual_review_count == 0
assert result.satisfied_count == 0
assert result.recorded_obligations_count == 2
assert len(result.recorded_obligations) == 2
assert result.skipped_optional_count == 2
assert result.verdict_status == ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW

evidence = result.recorded_obligations[0]
assert evidence.category == "COMPLIANT"
assert evidence.headline == "Electronic Submission Supported"
assert evidence.source_filename == "instructions.pdf"
assert evidence.source_page == 1
assert evidence.exact_quote == "electronic tender submission"
assert evidence.is_dealbreaker is False
assert evidence.verdict == MatchVerdict.SATISFIED

dq = TenderRequirement(
    category="DQ",
    headline="ISO 9001 Certification",
    source_filename="qualification.pdf",
    source_page=4,
    exact_quote="must hold ISO 9001 certification",
)
dq_bid_stage = scoped(
    dq,
    scope=RequirementScope.ELIGIBILITY,
    affects_bid_eligibility=True,
)
dq_result = evaluate_tender_compliance([dq_bid_stage], profile)
assert dq_result.is_eligible is False
assert dq_result.verdict_status == ComplianceVerdictStatus.NOT_ELIGIBLE
assert dq_result.failed_count == 1
assert dq_result.failed_dealbreakers[0].category == "DQ"
assert dq_result.failed_dealbreakers[0].source_filename == "qualification.pdf"
assert dq_result.failed_dealbreakers[0].source_verified is True
assert dq_result.failed_dealbreakers[0].affects_bid_eligibility is True

post_award = scoped(
    TenderRequirement(
        category="DQ",
        headline="Performance Security",
        source_filename="contract.pdf",
        source_page=5,
        exact_quote="provide performance security after award",
    ),
    scope=RequirementScope.POST_AWARD_OBLIGATION,
    affects_bid_eligibility=False,
)
post_award_result = evaluate_tender_compliance([post_award], profile)
assert post_award_result.is_eligible is True
assert post_award_result.verdict_status == ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW
assert post_award_result.failed_count == 0
assert post_award_result.failed_dealbreakers == []
assert post_award_result.satisfied_count == 0
assert post_award_result.recorded_obligations_count == 1

execution_obligations = [
    scoped(
        TenderRequirement(
            category="DQ",
            headline="No Whole Subcontract",
            source_filename="contract.pdf",
            source_page=10,
            exact_quote="The Contractor shall not subcontract the whole of the Works.",
        ),
        scope=RequirementScope.CONTRACT_EXECUTION,
        affects_bid_eligibility=False,
    ),
    scoped(
        TenderRequirement(
            category="DQ",
            headline="Accident Prevention Officer",
            source_filename="contract.pdf",
            source_page=11,
            exact_quote="The Contractor shall appoint an accident prevention officer at the Site",
        ),
        scope=RequirementScope.CONTRACT_EXECUTION,
        affects_bid_eligibility=False,
    ),
    scoped(
        TenderRequirement(
            category="DQ",
            headline="Obtain Written Subcontractor Approval",
            source_filename="contract.pdf",
            source_page=12,
            exact_quote="until the Subcontractors have been approved in writing by the Employer",
        ),
        scope=RequirementScope.CONTRACT_EXECUTION,
        affects_bid_eligibility=False,
    ),
    scoped(
        TenderRequirement(
            category="DQ",
            headline="Maintain As-Built Records",
            source_filename="contract.pdf",
            source_page=13,
            exact_quote='prepare, and keep up-to-date, a complete set of "as-built" records of the execution',
        ),
        scope=RequirementScope.CONTRACT_EXECUTION,
        affects_bid_eligibility=False,
    ),
]
execution_result = evaluate_tender_compliance(execution_obligations, profile)
assert execution_result.is_eligible is True
assert execution_result.failed_count == 0
assert execution_result.failed_dealbreakers == []
assert execution_result.satisfied_count == 0
assert execution_result.recorded_obligations_count == 4
assert execution_result.verdict_status == ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW

ambiguous_scope = scoped(
    TenderRequirement(
        category="DQ",
        headline="Performance Security",
        source_filename="ambiguous.pdf",
        source_page=9,
        exact_quote="mandatory performance security submission",
    ),
    scope=RequirementScope.POST_AWARD_OBLIGATION,
    scope_review_status=ScopeReviewStatus.NEEDS_REVIEW,
    affects_bid_eligibility=False,
)
ambiguous_result = evaluate_tender_compliance([ambiguous_scope], profile)
assert ambiguous_result.is_eligible is True
assert ambiguous_result.verdict_status == ComplianceVerdictStatus.NEEDS_REVIEW
assert ambiguous_result.status_message == "No verified requirements yet — manual review required."
assert ambiguous_result.failed_count == 0
assert ambiguous_result.manual_review_count == 1
assert ambiguous_result.manual_reviews_required[0].verdict == MatchVerdict.NEEDS_MANUAL_REVIEW

matching_profile = SimpleNamespace(
    id="profile-2",
    certifications=[
        SimpleNamespace(
            id="cert-iso-9001",
            cert_type="ISO9001 certification",
            expiry_date=date.today() + timedelta(days=30),
        )
    ],
    licenses=[],
)
matched_result = evaluate_tender_compliance([dq_bid_stage], matching_profile)
assert matched_result.is_eligible is True
assert matched_result.verdict_status == ComplianceVerdictStatus.COMPLIANT
assert matched_result.satisfied_count == 1
assert matched_result.satisfied_requirements[0].match_method == MatchMethod.VAULT_DETERMINISTIC
assert matched_result.satisfied_requirements[0].vault_match_type == "certification"
assert matched_result.satisfied_requirements[0].vault_evidence_id == "cert-iso-9001"
assert matched_result.satisfied_requirements[0].vault_match_confidence == 1.0

expired_profile = SimpleNamespace(
    id="profile-3",
    certifications=[
        SimpleNamespace(
            id="cert-expired-iso-9001",
            cert_type="ISO-9001",
            expiry_date=date.today() - timedelta(days=1),
        )
    ],
    licenses=[],
)
expired_result = evaluate_tender_compliance([dq_bid_stage], expired_profile)
assert expired_result.is_eligible is False
assert expired_result.failed_count == 1
assert expired_result.failed_dealbreakers[0].vault_match_type == "certification"
assert "expired" in expired_result.failed_dealbreakers[0].vault_missing_reason.lower()

food_conformity_req = scoped(
    TenderRequirement(
        category="DQ",
        headline="Food Conformity Certificate",
        source_filename="qualification.pdf",
        source_page=6,
        exact_quote="Bidder shall submit a food conformity certificate with the bid",
    ),
    scope=RequirementScope.ELIGIBILITY,
    affects_bid_eligibility=True,
)
food_profile = SimpleNamespace(
    id="profile-4",
    certifications=[
        SimpleNamespace(
            id="cert-food-conf",
            cert_type="Food product conformity certificate",
            expiry_date=date.today() + timedelta(days=60),
        )
    ],
    licenses=[],
)
food_result = evaluate_tender_compliance([food_conformity_req], food_profile)
assert food_result.is_eligible is True
assert food_result.satisfied_count == 1
assert food_result.satisfied_requirements[0].vault_match_type == "certification"

license_req = scoped(
    TenderRequirement(
        category="DQ",
        headline="Construction License",
        source_filename="qualification.pdf",
        source_page=8,
        exact_quote="Bidder must submit a valid construction license with the bid",
    ),
    scope=RequirementScope.ELIGIBILITY,
    affects_bid_eligibility=True,
)
active_license_profile = SimpleNamespace(
    id="profile-5",
    certifications=[],
    licenses=[
        SimpleNamespace(
            id="license-cat-iii",
            license_name="Construction License Cat-III",
            is_active=True,
        )
    ],
)
active_license_result = evaluate_tender_compliance([license_req], active_license_profile)
assert active_license_result.is_eligible is True
assert active_license_result.satisfied_count == 1
assert active_license_result.satisfied_requirements[0].vault_match_type == "license"
assert active_license_result.satisfied_requirements[0].vault_evidence_id == "license-cat-iii"

inactive_license_profile = SimpleNamespace(
    id="profile-6",
    certifications=[],
    licenses=[
        SimpleNamespace(
            id="license-inactive",
            license_name="Construction License Cat-III",
            is_active=False,
        )
    ],
)
inactive_license_result = evaluate_tender_compliance([license_req], inactive_license_profile)
assert inactive_license_result.is_eligible is False
assert inactive_license_result.failed_count == 1
assert inactive_license_result.failed_dealbreakers[0].vault_match_type == "license"
assert "inactive" in inactive_license_result.failed_dealbreakers[0].vault_missing_reason.lower()

financial_req = scoped(
    TenderRequirement(
        category="DQ",
        headline="Working Capital",
        source_filename="qualification.pdf",
        source_page=9,
        exact_quote="Bidder must demonstrate three-month working capital",
    ),
    scope=RequirementScope.FINANCIAL_SUBMISSION,
    affects_bid_eligibility=True,
)
financial_profile = SimpleNamespace(
    id="profile-7",
    certifications=[],
    licenses=[],
    financial_history=[SimpleNamespace(year=2025, turnover_uzs=1_000_000_000)],
)
financial_result = evaluate_tender_compliance([financial_req], financial_profile)
assert financial_result.is_eligible is False
assert financial_result.failed_count == 1
assert financial_result.failed_dealbreakers[0].vault_match_type == "financial"
assert "not yet structured" in financial_result.failed_dealbreakers[0].vault_missing_reason

bid_security_req = scoped(
    TenderRequirement(
        category="DQ",
        headline="Proposal Security",
        source_filename="qualification.pdf",
        source_page=10,
        exact_quote="Bidder shall submit 1% proposal security with the bid",
    ),
    scope=RequirementScope.FINANCIAL_SUBMISSION,
    affects_bid_eligibility=True,
)
bid_security_result = evaluate_tender_compliance([bid_security_req], financial_profile)
assert bid_security_result.is_eligible is False
assert bid_security_result.failed_count == 1
assert bid_security_result.failed_dealbreakers[0].vault_match_type == "bid_security"
assert "not yet structured" in bid_security_result.failed_dealbreakers[0].vault_missing_reason

print("Forensic compliance category checks passed.")
