from __future__ import annotations

from pydantic import BaseModel, Field


class TaxNodeInfo(BaseModel):
    """Lightweight taxonomy node descriptor passed into the evaluator."""

    name: str
    impact_weight: int = 0
    is_fatal: bool = False


class MetRequirement(BaseModel):
    """A taxonomy requirement the user's credentials satisfy."""

    uuid: str
    name: str


class MissingRequirement(BaseModel):
    """A taxonomy requirement the user's credentials do NOT satisfy."""

    uuid: str
    name: str
    impact_weight: int = 0
    is_fatal: bool = False


class DynamicComplianceResult(BaseModel):
    """Result of the UUID-based set-intersection compliance evaluation."""

    is_compliant: bool
    met_requirements: list[MetRequirement] = Field(default_factory=list)
    missing_requirements: list[MissingRequirement] = Field(default_factory=list)
    unmapped_requirements: list[str] = Field(default_factory=list)
    status_message: str


# Keep the old name as an alias so existing cached-JSON deserialization
# attempts that reference ``ComplianceResult`` still import without error.
ComplianceResult = DynamicComplianceResult


def evaluate_compliance(
    *,
    mapped_requirement_uuids: list[str],
    unmapped_custom_requirements: list[str],
    credential_uuids: set[str],
    taxonomy_lookup: dict[str, TaxNodeInfo],
) -> DynamicComplianceResult:
    """Perform a mathematical set intersection between tender requirements
    and the user's held credentials.

    Parameters
    ----------
    mapped_requirement_uuids:
        UUIDs emitted by the AI for requirements that matched taxonomy nodes.
    unmapped_custom_requirements:
        Raw requirement strings the AI could not map to the taxonomy.
    credential_uuids:
        Set of taxonomy-node UUIDs the user currently holds via
        ``CompanyCredential``.
    taxonomy_lookup:
        Dict mapping ``taxonomy_node_id`` → ``TaxNodeInfo`` for all active
        taxonomy nodes (used to enrich missing items).
    """

    met: list[MetRequirement] = []
    missing: list[MissingRequirement] = []

    seen: set[str] = set()
    for req_uuid in mapped_requirement_uuids:
        if req_uuid in seen:
            continue
        seen.add(req_uuid)

        node_info = taxonomy_lookup.get(req_uuid)
        node_name = node_info.name if node_info else req_uuid

        if req_uuid in credential_uuids:
            met.append(MetRequirement(uuid=req_uuid, name=node_name))
        else:
            missing.append(
                MissingRequirement(
                    uuid=req_uuid,
                    name=node_name,
                    impact_weight=node_info.impact_weight if node_info else 0,
                    is_fatal=node_info.is_fatal if node_info else False,
                )
            )

    is_compliant = len(missing) == 0

    if is_compliant:
        status_message = (
            "Compliant: all mapped taxonomy requirements are satisfied."
        )
    else:
        fatal_names = [m.name for m in missing if m.is_fatal]
        non_fatal_names = [m.name for m in missing if not m.is_fatal]
        parts: list[str] = []
        if fatal_names:
            parts.append(f"Fatal gaps: {', '.join(fatal_names)}")
        if non_fatal_names:
            parts.append(f"Missing: {', '.join(non_fatal_names)}")
        status_message = "Non-compliant: " + "; ".join(parts)

    if unmapped_custom_requirements:
        status_message += (
            f" | {len(unmapped_custom_requirements)} unmapped rule(s) require manual review."
        )

    return DynamicComplianceResult(
        is_compliant=is_compliant,
        met_requirements=met,
        missing_requirements=missing,
        unmapped_requirements=list(unmapped_custom_requirements),
        status_message=status_message,
    )
