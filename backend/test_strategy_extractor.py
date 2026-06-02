"""
Validation script for the Strategy Intelligence Extractor Agent.

Verifies:
- TenderStrategyIntelligence schema structure and defaults
- Strategy response schema completeness
- System prompt structure (7 sections + scope boundary)
- Import compatibility with tenders.py endpoint
- SECTION 2 lockdown in requirement_extractor.py (regression guard)
"""
from app.core.agents.strategy_extractor import (
    TenderStrategyIntelligence,
    SYSTEM_PROMPT,
    STRATEGY_RESPONSE_SCHEMA,
    MODEL_NAME,
    MAX_PAYLOAD_CHARS,
)

print(f"✅ Model: {MODEL_NAME}")
assert MODEL_NAME == "gemini-2.5-flash", f"Expected gemini-2.5-flash, got {MODEL_NAME}"

print(f"✅ Max payload chars: {MAX_PAYLOAD_CHARS}")
assert MAX_PAYLOAD_CHARS == 60_000, f"Expected 60000, got {MAX_PAYLOAD_CHARS}"

# ---------------------------------------------------------------------------
# Test 1: Schema has all 6 fields
# ---------------------------------------------------------------------------
schema_fields = list(STRATEGY_RESPONSE_SCHEMA["properties"].keys())
print(f"✅ Test 1 — Schema fields: {schema_fields}")
expected_fields = [
    "evaluation_criteria",
    "bidding_mechanics",
    "contract_and_legal_framework",
    "pricing_strategy_hints",
    "timeline_and_milestones",
    "submission_format",
]
for field in expected_fields:
    assert field in schema_fields, f"Missing field in schema: {field}"
assert len(schema_fields) == 6, f"Expected 6 fields, got {len(schema_fields)}"

schema_required = STRATEGY_RESPONSE_SCHEMA["required"]
for field in expected_fields:
    assert field in schema_required, f"Field not in required: {field}"
print(f"✅ Test 1 — All 6 fields present and required")

# ---------------------------------------------------------------------------
# Test 2: Default factory — empty model is valid
# ---------------------------------------------------------------------------
empty = TenderStrategyIntelligence()
assert empty.evaluation_criteria == []
assert empty.bidding_mechanics == []
assert empty.contract_and_legal_framework == []
assert empty.pricing_strategy_hints == []
assert empty.timeline_and_milestones == []
assert empty.submission_format == []
print("✅ Test 2 — Empty model produces all-empty-list defaults")

# ---------------------------------------------------------------------------
# Test 3: Populated model validates correctly
# ---------------------------------------------------------------------------
populated = TenderStrategyIntelligence(
    evaluation_criteria=[
        "Lowest price = Highest score",
        "Technical proposal scored on 100-point scale",
    ],
    bidding_mechanics=[
        "Submit via e-tender portal",
        "Two-envelope system (technical + financial)",
    ],
    contract_and_legal_framework=[
        "Governed by Public Procurement Law No. 684",
        "Disputes resolved in Tashkent Arbitration Court",
    ],
    pricing_strategy_hints=[
        "Starting price: 500,000,000 UZS",
        "15% advance payment upon contract signing",
    ],
    timeline_and_milestones=[
        "Submission deadline: 2026-06-15 18:00 Tashkent time",
        "Contract signing within 30 days of award",
    ],
    submission_format=[
        "Technical and financial envelopes must be separate PDFs",
        "All documents in Uzbek or Russian",
    ],
)
assert len(populated.evaluation_criteria) == 2
assert len(populated.bidding_mechanics) == 2
assert len(populated.contract_and_legal_framework) == 2
assert len(populated.pricing_strategy_hints) == 2
assert len(populated.timeline_and_milestones) == 2
assert len(populated.submission_format) == 2
print("✅ Test 3 — Populated model validates with all 6 fields")

# ---------------------------------------------------------------------------
# Test 4: Whitespace stripping (str_strip_whitespace=True)
# ---------------------------------------------------------------------------
trimmed = TenderStrategyIntelligence(
    evaluation_criteria=["  Lowest price wins  "],
    bidding_mechanics=["  Upload via portal  "],
)
assert trimmed.evaluation_criteria[0] == "Lowest price wins"
assert trimmed.bidding_mechanics[0] == "Upload via portal"
print("✅ Test 4 — Whitespace stripping works on list items")

# ---------------------------------------------------------------------------
# Test 5: Extra fields are forbidden
# ---------------------------------------------------------------------------
from pydantic import ValidationError

try:
    TenderStrategyIntelligence(rogue_field="should fail")
    assert False, "Should have raised ValidationError for extra field"
except ValidationError:
    pass
print("✅ Test 5 — Extra fields correctly rejected (extra='forbid')")

# ---------------------------------------------------------------------------
# Test 6: System prompt structure
# ---------------------------------------------------------------------------
assert "CRITICAL SCOPE BOUNDARY" in SYSTEM_PROMPT
assert "SECTION 1: EVALUATION CRITERIA" in SYSTEM_PROMPT
assert "SECTION 2: BIDDING MECHANICS" in SYSTEM_PROMPT
assert "SECTION 3: CONTRACT & LEGAL FRAMEWORK" in SYSTEM_PROMPT
assert "SECTION 4: PRICING STRATEGY HINTS" in SYSTEM_PROMPT
assert "SECTION 5: TIMELINE & MILESTONES" in SYSTEM_PROMPT
assert "SECTION 6: SUBMISSION FORMAT" in SYSTEM_PROMPT
assert "MULTILINGUAL EXTRACTION" in SYSTEM_PROMPT
# Verify the scope boundary explicitly excludes compliance
assert "NOT looking for bidder obligations" in SYSTEM_PROMPT
assert "SEPARATE compliance engine" in SYSTEM_PROMPT
print("✅ Test 6 — System prompt has all 6 sections + scope boundary + multilingual directive")

# ---------------------------------------------------------------------------
# Test 7: Import compatibility with tenders.py
# ---------------------------------------------------------------------------
from app.core.agents.strategy_extractor import extract_strategy_intelligence
print("✅ Test 7 — extract_strategy_intelligence imports successfully")

# ---------------------------------------------------------------------------
# Test 8: Verify forensic lockdown in requirement_extractor.py
# ---------------------------------------------------------------------------
from app.core.agents.requirement_extractor import SYSTEM_PROMPT as COMPLIANCE_PROMPT
assert "You are a forensic legal auditor for B2G procurement" in COMPLIANCE_PROMPT
assert "[[FILE: filename.ext]]" in COMPLIANCE_PROMPT
assert "[[PAGE N]]" in COMPLIANCE_PROMPT
assert "reserved EXCLUSIVELY" in COMPLIANCE_PROMPT
assert "MUST be categorized as `NICE_TO_HAVE`" in COMPLIANCE_PROMPT
assert "COMPLIANT means verified non-risk evidence" in COMPLIANCE_PROMPT
print("✅ Test 8 — Forensic compliance prompt verified: source markers + category boundaries")

# ---------------------------------------------------------------------------
# Test 9: Verify AnalyzeTenderResponse includes strategy_intelligence
# ---------------------------------------------------------------------------
from app.api.endpoints.tenders import AnalyzeTenderResponse
response_fields = set(AnalyzeTenderResponse.model_fields.keys())
assert "strategy_intelligence" in response_fields, (
    f"strategy_intelligence not in AnalyzeTenderResponse fields: {response_fields}"
)
# Verify it's optional (None default)
field_info = AnalyzeTenderResponse.model_fields["strategy_intelligence"]
assert field_info.default is None, "strategy_intelligence should default to None"
print("✅ Test 9 — AnalyzeTenderResponse includes optional strategy_intelligence field")

# ---------------------------------------------------------------------------
# Test 10: JSON round-trip (serialize → deserialize)
# ---------------------------------------------------------------------------
import json

original = TenderStrategyIntelligence(
    evaluation_criteria=["Price 60%, Technical 40%"],
    pricing_strategy_hints=["Budget ceiling: 1,000,000,000 UZS"],
)
serialized = original.model_dump(mode="json")
json_str = json.dumps(serialized)
deserialized = TenderStrategyIntelligence.model_validate_json(json_str)
assert deserialized.evaluation_criteria == original.evaluation_criteria
assert deserialized.pricing_strategy_hints == original.pricing_strategy_hints
assert deserialized.bidding_mechanics == []  # Unset fields default to empty list
print("✅ Test 10 — JSON round-trip (serialize → deserialize) preserves data")

print("\n🎯 ALL 10 TESTS PASSED — Strategy Intelligence Agent validated.")
