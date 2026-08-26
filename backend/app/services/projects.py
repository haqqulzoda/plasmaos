"""Narrow deterministic Project identity and TenderProject linkage helpers."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Project, Tender, TenderProject
from app.services.tender_sources.keys import normalize_source_system


SOURCE_PROJECT_ID = "SOURCE_PROJECT_ID"
SOURCE_NATIVE_LINK = "SOURCE_NATIVE_LINK"
DETERMINISTIC_LINKAGE_METHODS = frozenset({SOURCE_PROJECT_ID, SOURCE_NATIVE_LINK})
WORLD_BANK_PROJECT_ID_PATTERN = re.compile(r"^P\d{6}$")


class ProjectIdClassification(str, enum.Enum):
    VALID = "VALID"
    EMPTY = "EMPTY"
    MALFORMED = "MALFORMED"
    SUSPICIOUS = "SUSPICIOUS"


@dataclass(frozen=True)
class NormalizedProjectIdentifier:
    raw_value: str | None
    normalized_value: str | None
    classification: ProjectIdClassification

    @property
    def is_valid(self) -> bool:
        return self.classification is ProjectIdClassification.VALID


@dataclass(frozen=True)
class ProjectLinkResult:
    identifier: NormalizedProjectIdentifier
    project: Project | None = None
    link: TenderProject | None = None
    project_created: bool = False
    link_created: bool = False


def normalize_project_identifier(
    source_system: str,
    external_project_id: object,
) -> NormalizedProjectIdentifier:
    """Conservatively normalize and classify a source-native project ID."""
    source = normalize_source_system(source_system)
    if external_project_id is None:
        return NormalizedProjectIdentifier(
            raw_value=None,
            normalized_value=None,
            classification=ProjectIdClassification.EMPTY,
        )

    raw_value = str(external_project_id)
    normalized_value = raw_value.strip()
    if not normalized_value:
        return NormalizedProjectIdentifier(
            raw_value=raw_value,
            normalized_value=None,
            classification=ProjectIdClassification.EMPTY,
        )
    if len(raw_value) > 100 or any(
        ord(character) < 32 for character in normalized_value
    ):
        return NormalizedProjectIdentifier(
            raw_value=raw_value,
            normalized_value=normalized_value,
            classification=ProjectIdClassification.MALFORMED,
        )
    if source == "world_bank" and not WORLD_BANK_PROJECT_ID_PATTERN.fullmatch(
        normalized_value
    ):
        return NormalizedProjectIdentifier(
            raw_value=raw_value,
            normalized_value=normalized_value,
            classification=ProjectIdClassification.SUSPICIOUS,
        )
    return NormalizedProjectIdentifier(
        raw_value=raw_value,
        normalized_value=normalized_value,
        classification=ProjectIdClassification.VALID,
    )


def _clean_metadata_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


async def resolve_or_create_project(
    db: AsyncSession,
    *,
    source_system: str,
    external_project_id: object,
    authoritative_metadata: Mapping[str, Any] | None = None,
) -> tuple[Project, bool]:
    """Resolve a source-scoped Project using a race-safe unique-key insert."""
    source = normalize_source_system(source_system)
    identifier = normalize_project_identifier(source, external_project_id)
    if not identifier.is_valid or identifier.normalized_value is None:
        raise ValueError(
            "project identifier is not valid deterministic source evidence: "
            f"{identifier.classification.value}"
        )

    metadata = authoritative_metadata or {}
    project_id = uuid4()
    statement = (
        insert(Project)
        .values(
            id=project_id,
            source_system=source,
            external_project_id=identifier.normalized_value,
            name=_clean_metadata_text(metadata.get("name"), max_length=500),
            country=_clean_metadata_text(metadata.get("country"), max_length=100),
            source_url=_clean_metadata_text(metadata.get("source_url"), max_length=500),
            raw_provenance=(
                dict(metadata["raw_provenance"])
                if isinstance(metadata.get("raw_provenance"), Mapping)
                else None
            ),
        )
        .on_conflict_do_nothing(
            constraint="uq_projects_source_external_project_id"
        )
        .returning(Project.id)
    )
    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    created = inserted_id is not None

    result = await db.execute(
        select(Project)
        .where(
            Project.source_system == source,
            Project.external_project_id == identifier.normalized_value,
        )
        .with_for_update()
    )
    project = result.scalar_one()

    # Only enrich absent fields; a sparse refresh cannot erase better metadata.
    for field_name, max_length in (
        ("name", 500),
        ("country", 100),
        ("source_url", 500),
    ):
        candidate = _clean_metadata_text(metadata.get(field_name), max_length=max_length)
        if getattr(project, field_name) is None and candidate is not None:
            setattr(project, field_name, candidate)
    if project.raw_provenance is None and isinstance(
        metadata.get("raw_provenance"), Mapping
    ):
        project.raw_provenance = dict(metadata["raw_provenance"])
    return project, created


def _observed_at(value: datetime | None) -> str:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc).isoformat()


async def link_tender_to_project(
    db: AsyncSession,
    *,
    tender: Tender,
    external_project_id: object,
    linkage_method: str = SOURCE_PROJECT_ID,
    source_field: str = "project_id",
    source_url: str | None = None,
    observed_at: datetime | None = None,
    authoritative_metadata: Mapping[str, Any] | None = None,
) -> ProjectLinkResult:
    """Idempotently apply deterministic source evidence to one tender."""
    source = normalize_source_system(tender.source_system)
    identifier = normalize_project_identifier(source, external_project_id)
    if not identifier.is_valid or identifier.normalized_value is None:
        return ProjectLinkResult(identifier=identifier)
    if linkage_method not in DETERMINISTIC_LINKAGE_METHODS:
        raise ValueError(f"unsupported non-deterministic linkage_method: {linkage_method!r}")

    await db.flush()
    if tender.id is None:
        raise ValueError("tender must have an identity before project linkage")

    raw_source_value = identifier.raw_value or identifier.normalized_value
    observed_at_value = _observed_at(observed_at)
    evidence = {
        "source_system": source,
        "source_field": source_field,
        "source_value": raw_source_value,
        "normalized_value": identifier.normalized_value,
        "source_url": source_url,
        "observed_at": observed_at_value,
    }
    metadata = dict(authoritative_metadata or {})
    metadata.setdefault("raw_provenance", evidence)
    project, project_created = await resolve_or_create_project(
        db,
        source_system=source,
        external_project_id=identifier.normalized_value,
        authoritative_metadata=metadata,
    )

    new_link_id = uuid4()
    statement = (
        insert(TenderProject)
        .values(
            id=new_link_id,
            tender_id=tender.id,
            project_id=project.id,
            linkage_method=linkage_method,
            source_value=raw_source_value,
            provenance=evidence,
        )
        .on_conflict_do_nothing(constraint="uq_tender_projects_tender_id")
        .returning(TenderProject.id)
    )
    inserted_link_id: UUID | None = (await db.execute(statement)).scalar_one_or_none()
    link_created = inserted_link_id is not None
    result = await db.execute(
        select(TenderProject)
        .where(TenderProject.tender_id == tender.id)
        .with_for_update()
    )
    link = result.scalar_one()
    if not link_created and (
        link.project_id != project.id
        or link.linkage_method != linkage_method
        or link.source_value != raw_source_value
        or link.provenance != evidence
    ):
        link.project_id = project.id
        link.linkage_method = linkage_method
        link.source_value = raw_source_value
        link.provenance = evidence

    return ProjectLinkResult(
        identifier=identifier,
        project=project,
        link=link,
        project_created=project_created,
        link_created=link_created,
    )
