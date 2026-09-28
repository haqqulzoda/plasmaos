"""W8 proposal evidence workspace, pack, manifest, and artifact contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProposalEvidenceSealRequest(BaseModel):
    scenario_id: UUID
    revision_id: UUID
    approval_decision_id: UUID


class ProposalEvidenceExportRequest(BaseModel):
    artifact_type: str = Field(pattern=r"^(PDF|DOCX|JSON)$")
    historical_snapshot: bool = False


class ProposalEvidenceItemResponse(BaseModel):
    item_id: UUID
    ordinal: int
    category: str
    source_authority_type: str
    source_identity: str
    provenance: str
    review_state: str | None = None
    evidence_state: str | None = None
    purpose: str
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    gap_id: UUID | None = None
    source_sha256: str | None = None
    source_version: str | None = None
    payload: dict[str, Any]


class ProposalEvidenceArtifactResponse(BaseModel):
    artifact_id: UUID
    pack_id: UUID
    artifact_type: str
    historical_snapshot: bool
    content_sha256: str
    byte_size: int
    media_type: str
    generator_version: str
    created_by_membership_id: UUID
    created_at: datetime


class ProposalEvidencePackResponse(BaseModel):
    pack_id: UUID
    workspace_id: UUID
    organization_id: UUID
    pursuit_id: UUID
    pack_version: int
    scenario_id: UUID
    scenario_revision_id: UUID
    approval_decision_id: UUID
    analysis_run_id: UUID
    analysis_pack_id: UUID
    schema_version: str
    manifest_sha256: str
    pack_state: str
    scenario_title: str
    pursuit_title: str
    item_count: int
    matrix_row_count: int
    participant_count: int
    later_stage_count: int
    checklist_count: int
    pack_current: bool
    stale_reasons: list[str] = Field(default_factory=list)
    items: list[ProposalEvidenceItemResponse] = Field(default_factory=list)
    artifacts: list[ProposalEvidenceArtifactResponse] = Field(default_factory=list)
    sealed_by_membership_id: UUID
    created_at: datetime


class PursuitProposalWorkspaceResponse(BaseModel):
    workspace_id: UUID | None = None
    organization_id: UUID
    pursuit_id: UUID
    created_by_membership_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    legacy_proposal_id: UUID | None = None
    packs: list[ProposalEvidencePackResponse] = Field(default_factory=list)

