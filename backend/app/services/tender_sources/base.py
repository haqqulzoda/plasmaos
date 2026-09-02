"""Shared contracts and upsert helpers for tender source ingestion."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, TypeVar

from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender, TenderDocument, TenderStatus
from app.services.tender_sources.keys import (
    canonical_source_key,
    normalize_source_system,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class NormalizedAttachment:
    """Internal attachment metadata discovered from a source system."""

    source_document_url: str
    source_document_type: str | None = None
    external_file_id: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    sha256: str | None = None
    source_metadata_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class CanonicalContact:
    """Source-neutral contact details discovered by a connector."""

    source_system: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_source_system(self) -> str:
        return normalize_source_system(self.source_system)


@dataclass(frozen=True)
class CanonicalDocument:
    """Source-neutral document metadata consumed by shared persistence."""

    source_system: str
    source_document_url: str
    file_type: str = "unknown"
    title: str | None = None
    source_document_type: str | None = None
    external_file_id: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    sha256: str | None = None
    download_status: str | None = None
    source_metadata_json: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_source_system(self) -> str:
        return normalize_source_system(self.source_system)

    @property
    def file_url(self) -> str:
        return self.source_document_url

    @classmethod
    def from_attachment(
        cls,
        *,
        source_system: str,
        attachment: NormalizedAttachment,
        download_status: str | None = None,
    ) -> "CanonicalDocument":
        file_type = (
            attachment.source_document_type
            or attachment.mime_type
            or "unknown"
        )
        return cls(
            source_system=source_system,
            source_document_url=attachment.source_document_url,
            file_type=str(file_type).strip().lower() or "unknown",
            source_document_type=attachment.source_document_type,
            external_file_id=attachment.external_file_id,
            file_size=attachment.file_size,
            mime_type=attachment.mime_type,
            sha256=attachment.sha256,
            download_status=download_status,
            source_metadata_json=attachment.source_metadata_json or {},
        )


@dataclass(frozen=True)
class NormalizedTender:
    """Source-neutral tender payload used by connector upserts."""

    source_system: str
    external_id: str
    source_url: str
    title: str
    description: str | None = None
    budget: float = 0.0
    currency: str = "UZS"
    country: str | None = None
    region: str | None = None
    sector: str | None = None
    buyer: str | None = None
    procurement_category: str | None = None
    procurement_method: str | None = None
    notice_type: str | None = None
    project_id: str | None = None
    publication_date: datetime | None = None
    deadline: datetime | None = None
    status: TenderStatus = TenderStatus.OPEN
    category: str = "Other"
    source_metadata_json: dict[str, Any] | None = None
    scrape_status: str | None = "success"
    last_synced_at: datetime | None = None
    attachments: tuple[NormalizedAttachment, ...] = field(default_factory=tuple)
    # Keys enriched outside metadata refresh that an authoritative lightweight
    # snapshot did not observe. Connectors must opt in explicitly.
    preserve_source_metadata_keys: tuple[str, ...] = field(default_factory=tuple)

    @property
    def normalized_source_system(self) -> str:
        return normalize_source_system(self.source_system)

    @property
    def canonical_source_key(self) -> str:
        return canonical_source_key(self.source_system, self.external_id)


CanonicalTender = NormalizedTender


class TenderPersistenceOutcome(str, Enum):
    """Semantic result of applying one canonical source-owned snapshot."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class TenderPersistenceItem:
    """Persisted Tender identity and its mutually-exclusive semantic outcome."""

    canonical_source_key: str
    tender: Tender
    outcome: TenderPersistenceOutcome


@dataclass(frozen=True)
class TenderBatchPersistenceResult:
    """Deterministic result for one de-duplicated semantic persistence batch."""

    items: tuple[TenderPersistenceItem, ...]
    duplicate_count: int = 0

    @property
    def by_canonical_source_key(self) -> dict[str, TenderPersistenceItem]:
        return {item.canonical_source_key: item for item in self.items}

    def count(self, outcome: TenderPersistenceOutcome) -> int:
        return sum(item.outcome is outcome for item in self.items)

    @property
    def created_count(self) -> int:
        return self.count(TenderPersistenceOutcome.CREATED)

    @property
    def updated_count(self) -> int:
        return self.count(TenderPersistenceOutcome.UPDATED)

    @property
    def unchanged_count(self) -> int:
        return self.count(TenderPersistenceOutcome.UNCHANGED)


DEFAULT_TENDER_PERSISTENCE_BATCH_SIZE = 500

# These are exactly the Tender columns owned by source normalization. Observation
# timestamps and all customer/downstream domains are intentionally absent.
SOURCE_OWNED_TENDER_FIELDS = (
    "source_system",
    "external_id",
    "canonical_source_key",
    "source_url",
    "title",
    "description",
    "budget",
    "currency",
    "deadline",
    "publication_date",
    "country",
    "region",
    "sector",
    "buyer",
    "procurement_category",
    "procurement_method",
    "notice_type",
    "project_id",
    "source_metadata_json",
    "scrape_status",
    "status",
    "category",
)


class TenderSourceConnector(Protocol):
    """Lightweight connector contract for source-specific tender ingestion."""

    source_system: str

    async def list_opportunities(self) -> list[Any]:
        """Return raw opportunity payloads from the source."""
        ...

    async def fetch_detail(self, external_id: str) -> Any:
        """Fetch raw detail payload for one source tender."""
        ...

    async def discover_attachments(
        self,
        normalized_tender: CanonicalTender,
    ) -> list[NormalizedAttachment]:
        """Discover source document metadata for one normalized tender."""
        ...

    async def discover_documents(
        self,
        normalized_tender: CanonicalTender,
    ) -> list[CanonicalDocument]:
        """Discover source document metadata as canonical documents."""
        ...

    def normalize(self, raw: Any) -> NormalizedTender:
        """Convert a raw source payload into a NormalizedTender."""
        ...

    async def upsert(
        self,
        db: AsyncSession,
        normalized_tender: NormalizedTender,
    ) -> tuple[Tender, bool]:
        """Persist a normalized tender and return (tender, created)."""
        ...

    async def upsert_documents(
        self,
        db: AsyncSession,
        *,
        tender: Tender,
        documents: list[CanonicalDocument],
    ) -> tuple[int, int]:
        """Persist canonical documents for a source-scoped tender."""
        ...


class SourceDocumentAdapter(Protocol):
    """Source-specific document acquisition boundary."""

    source_system: str

    async def discover_documents(
        self,
        tender: Tender,
    ) -> list[CanonicalDocument]:
        """Discover documents without persisting source-specific state."""
        ...


def assert_source_scope(source_system: str, tender: Any) -> None:
    """Ensure a source adapter can only mutate rows belonging to its source."""
    expected = normalize_source_system(source_system)
    actual = normalize_source_system(getattr(tender, "source_system", ""))
    canonical_key = (getattr(tender, "canonical_source_key", "") or "").strip()
    if actual != expected:
        raise ValueError(
            f"{expected} adapter cannot mutate {actual} tender rows"
        )
    if canonical_key and not canonical_key.startswith(f"{expected}:"):
        raise ValueError(
            f"{expected} adapter cannot mutate tender key {canonical_key!r}"
        )


def canonical_documents_from_attachments(
    *,
    source_system: str,
    attachments: list[NormalizedAttachment],
    download_status: str | None = None,
) -> list[CanonicalDocument]:
    """Convert adapter-owned attachment metadata to persistence-safe documents."""
    return [
        CanonicalDocument.from_attachment(
            source_system=source_system,
            attachment=attachment,
            download_status=download_status,
        )
        for attachment in attachments
    ]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_semantic_value(value: Any) -> Any:
    """Return a deterministic, hashable representation for semantic equality."""
    if isinstance(value, datetime):
        normalized = _utc_datetime(value)
        return normalized.isoformat(timespec="microseconds") if normalized else None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _canonical_semantic_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        # Source metadata collections are descriptive sets (attachments, methods,
        # regions, tags), so source ordering is not a semantic Tender change.
        canonical_items = [_canonical_semantic_value(item) for item in value]
        return tuple(sorted(canonical_items, key=repr))
    return value


def _normalized_source_values(normalized_tender: NormalizedTender) -> dict[str, Any]:
    source_system = normalized_tender.normalized_source_system
    external_id = str(normalized_tender.external_id).strip()
    return {
        "source_system": source_system,
        "external_id": external_id,
        "canonical_source_key": canonical_source_key(source_system, external_id),
        "source_url": normalized_tender.source_url,
        "title": normalized_tender.title,
        "description": normalized_tender.description,
        "budget": float(normalized_tender.budget),
        "currency": normalized_tender.currency,
        "deadline": _utc_datetime(normalized_tender.deadline),
        "publication_date": _utc_datetime(normalized_tender.publication_date),
        "country": _clean_optional(normalized_tender.country),
        "region": _clean_optional(normalized_tender.region),
        "sector": _clean_optional(normalized_tender.sector),
        "buyer": _clean_optional(normalized_tender.buyer),
        "procurement_category": _clean_optional(
            normalized_tender.procurement_category
        ),
        "procurement_method": _clean_optional(normalized_tender.procurement_method),
        "notice_type": _clean_optional(normalized_tender.notice_type),
        "project_id": _clean_optional(normalized_tender.project_id),
        "source_metadata_json": (
            dict(normalized_tender.source_metadata_json)
            if normalized_tender.source_metadata_json is not None
            else None
        ),
        "scrape_status": _clean_optional(normalized_tender.scrape_status) or "success",
        "status": normalized_tender.status,
        "category": normalized_tender.category,
    }


def _source_values_for_existing(
    tender: Tender,
    normalized_tender: NormalizedTender,
) -> dict[str, Any]:
    values = _normalized_source_values(normalized_tender)
    preserved = normalized_tender.preserve_source_metadata_keys
    if preserved:
        incoming = dict(values.get("source_metadata_json") or {})
        existing = dict(tender.source_metadata_json or {})
        for key in preserved:
            if key not in incoming and key in existing:
                incoming[key] = existing[key]
        values["source_metadata_json"] = incoming
    return values


def source_owned_tender_snapshot(value: NormalizedTender | Tender) -> tuple[Any, ...]:
    """Canonical snapshot of only source-owned Tender metadata."""
    values = (
        _normalized_source_values(value)
        if isinstance(value, NormalizedTender)
        else {
            field_name: getattr(value, field_name)
            for field_name in SOURCE_OWNED_TENDER_FIELDS
        }
    )
    return tuple(
        _canonical_semantic_value(values[field_name])
        for field_name in SOURCE_OWNED_TENDER_FIELDS
    )


def _changed_source_fields(
    tender: Tender,
    source_values: Mapping[str, Any],
) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in SOURCE_OWNED_TENDER_FIELDS
        if _canonical_semantic_value(getattr(tender, field_name))
        != _canonical_semantic_value(source_values[field_name])
    )


def _chunks(values: list[T], size: int) -> Iterable[list[T]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class TenderIdentityConflictError(RuntimeError):
    """Database rows violate the two equivalent canonical identity contracts."""


def _resolve_identity_rows(
    normalized_tenders: Iterable[NormalizedTender],
    rows: Iterable[Tender],
) -> dict[str, Tender]:
    rows_by_key = {row.canonical_source_key: row for row in rows}
    rows_by_pair = {
        (normalize_source_system(row.source_system), str(row.external_id).strip()): row
        for row in rows
    }
    resolved: dict[str, Tender] = {}
    for normalized in normalized_tenders:
        source = normalized.normalized_source_system
        external_id = str(normalized.external_id).strip()
        key = normalized.canonical_source_key
        by_key = rows_by_key.get(key)
        by_pair = rows_by_pair.get((source, external_id))
        if by_key is not None and (
            normalize_source_system(by_key.source_system),
            str(by_key.external_id).strip(),
        ) != (source, external_id):
            raise TenderIdentityConflictError(
                f"canonical key {key!r} belongs to a different source identity"
            )
        if by_key is not None and by_pair is not None and by_key.id != by_pair.id:
            raise TenderIdentityConflictError(
                f"canonical key and source/external pair resolve to different rows: {key!r}"
            )
        match = by_key or by_pair
        if match is not None:
            resolved[key] = match
    return resolved


async def _lookup_tenders(
    db: AsyncSession,
    normalized_tenders: list[NormalizedTender],
) -> dict[str, Tender]:
    if not normalized_tenders:
        return {}
    keys = [item.canonical_source_key for item in normalized_tenders]
    pairs = [
        (item.normalized_source_system, str(item.external_id).strip())
        for item in normalized_tenders
    ]
    result = await db.execute(
        select(Tender).where(
            or_(
                Tender.canonical_source_key.in_(keys),
                tuple_(Tender.source_system, Tender.external_id).in_(pairs),
            )
        )
    )
    return _resolve_identity_rows(normalized_tenders, result.scalars().all())


async def persist_tender_batch(
    db: AsyncSession,
    normalized_tenders: Iterable[NormalizedTender],
    *,
    batch_size: int = DEFAULT_TENDER_PERSISTENCE_BATCH_SIZE,
) -> TenderBatchPersistenceResult:
    """Persist source snapshots with bounded lookup and conflict-safe inserts.

    Duplicate identities use a deterministic last-payload-wins rule while
    retaining first-seen identity order in the returned mapping.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    deduplicated: dict[str, NormalizedTender] = {}
    input_count = 0
    for normalized in normalized_tenders:
        input_count += 1
        deduplicated[normalized.canonical_source_key] = normalized
    ordered = list(deduplicated.values())
    duplicate_count = input_count - len(ordered)
    if not ordered:
        return TenderBatchPersistenceResult(items=(), duplicate_count=duplicate_count)

    items: list[TenderPersistenceItem] = []
    for chunk in _chunks(ordered, batch_size):
        existing = await _lookup_tenders(db, chunk)
        absent = [
            item for item in chunk if item.canonical_source_key not in existing
        ]
        created: dict[str, Tender] = {}
        now = datetime.now(timezone.utc)
        payloads = []
        for normalized in absent:
            payload = _normalized_source_values(normalized)
            payload["last_synced_at"] = _utc_datetime(
                normalized.last_synced_at
            ) or now
            payloads.append(payload)
        if payloads:
            statement = (
                postgresql_insert(Tender)
                .values(payloads)
                .on_conflict_do_nothing()
                .returning(Tender)
            )
            result = await db.execute(statement)
            for tender in result.scalars().all():
                created[tender.canonical_source_key] = tender

        losers = [
            item for item in absent if item.canonical_source_key not in created
        ]
        if losers:
            resolved_losers = await _lookup_tenders(db, losers)
            unresolved = [
                item.canonical_source_key
                for item in losers
                if item.canonical_source_key not in resolved_losers
            ]
            if unresolved:
                raise RuntimeError(
                    "conflict-safe Tender insert lost without a resolvable winner: "
                    + ", ".join(unresolved[:5])
                )
            existing.update(resolved_losers)

        has_updates = False
        for normalized in chunk:
            key = normalized.canonical_source_key
            if key in created:
                items.append(
                    TenderPersistenceItem(
                        canonical_source_key=key,
                        tender=created[key],
                        outcome=TenderPersistenceOutcome.CREATED,
                    )
                )
                continue

            tender = existing[key]
            source_values = _source_values_for_existing(tender, normalized)
            changed_fields = _changed_source_fields(tender, source_values)
            if not changed_fields:
                items.append(
                    TenderPersistenceItem(
                        canonical_source_key=key,
                        tender=tender,
                        outcome=TenderPersistenceOutcome.UNCHANGED,
                    )
                )
                continue

            for field_name in changed_fields:
                setattr(tender, field_name, source_values[field_name])
            tender.last_synced_at = _utc_datetime(
                normalized.last_synced_at
            ) or datetime.now(timezone.utc)
            has_updates = True
            items.append(
                TenderPersistenceItem(
                    canonical_source_key=key,
                    tender=tender,
                    outcome=TenderPersistenceOutcome.UPDATED,
                )
            )

        if has_updates:
            # ORM unit-of-work emits safe parameterized executemany updates where
            # changed column shapes match. UNCHANGED objects are never mutated.
            await db.flush()

    logger.info(
        "tender_source_batch persisted=%s created=%s updated=%s unchanged=%s duplicates=%s",
        len(items),
        sum(item.outcome is TenderPersistenceOutcome.CREATED for item in items),
        sum(item.outcome is TenderPersistenceOutcome.UPDATED for item in items),
        sum(item.outcome is TenderPersistenceOutcome.UNCHANGED for item in items),
        duplicate_count,
    )
    return TenderBatchPersistenceResult(
        items=tuple(items),
        duplicate_count=duplicate_count,
    )


class DocumentPersistenceOutcome(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class DocumentPersistenceItem:
    document: TenderDocument
    outcome: DocumentPersistenceOutcome


@dataclass(frozen=True)
class DocumentBatchPersistenceResult:
    items: tuple[DocumentPersistenceItem, ...]
    duplicate_count: int = 0

    def count(self, outcome: DocumentPersistenceOutcome) -> int:
        return sum(item.outcome is outcome for item in self.items)

    @property
    def created_count(self) -> int:
        return self.count(DocumentPersistenceOutcome.CREATED)

    @property
    def updated_count(self) -> int:
        return self.count(DocumentPersistenceOutcome.UPDATED)

    @property
    def unchanged_count(self) -> int:
        return self.count(DocumentPersistenceOutcome.UNCHANGED)


_DOCUMENT_STATUS_RANK = {
    "failed": 5,
    "metadata_only": 10,
    "access_required": 10,
    "queued": 20,
    "processing": 30,
    "downloaded": 40,
    "processed": 50,
    "parsed": 60,
    "usable": 70,
}


def _monotonic_document_status(current: str | None, proposed: str | None) -> str | None:
    if not proposed:
        return current
    if not current:
        return proposed
    if _DOCUMENT_STATUS_RANK.get(proposed, 0) > _DOCUMENT_STATUS_RANK.get(current, 0):
        return proposed
    return current


async def persist_document_descriptors(
    db: AsyncSession,
    *,
    source_system: str,
    tender: Tender,
    documents: Iterable[CanonicalDocument],
    url_validator: Callable[[str], bool] | None = None,
    default_status: str = "metadata_only",
) -> DocumentBatchPersistenceResult:
    """Batch lookup and semantically persist deterministic document descriptors."""
    assert_source_scope(source_system, tender)
    deduplicated: dict[tuple[str, str], CanonicalDocument] = {}
    input_count = 0
    for descriptor in documents:
        input_count += 1
        url = str(descriptor.source_document_url or "").strip()
        external_id = str(descriptor.external_file_id or "").strip()
        if not url or (url_validator is not None and not url_validator(url)):
            continue
        identity = (external_id, url) if external_id else ("", url)
        deduplicated[identity] = descriptor
    descriptors = list(deduplicated.values())
    if not descriptors:
        return DocumentBatchPersistenceResult((), input_count)

    # Compatibility for historical lightweight test sessions. Production
    # AsyncSession always uses the single bounded lookup below.
    if not isinstance(db, AsyncSession):
        items: list[DocumentPersistenceItem] = []
        for descriptor in descriptors:
            url = str(descriptor.source_document_url).strip()
            external_id = str(descriptor.external_file_id or "").strip()
            predicates = [TenderDocument.source_document_url == url]
            if external_id:
                predicates.append(TenderDocument.external_file_id == external_id)
            result = await db.execute(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender.id,
                    or_(*predicates),
                )
            )
            existing = result.scalar_one_or_none()
            file_type = descriptor.source_document_type or descriptor.file_type or "document"
            proposed_status = descriptor.download_status or default_status
            if existing is None:
                existing = TenderDocument(
                    tender_id=tender.id, file_url=url[:500], file_type=file_type,
                    source_document_url=url, source_document_type=file_type,
                    download_status=proposed_status,
                    external_file_id=external_id or None, file_size=descriptor.file_size,
                    mime_type=descriptor.mime_type, sha256=descriptor.sha256,
                )
                db.add(existing)
                items.append(DocumentPersistenceItem(existing, DocumentPersistenceOutcome.CREATED))
                continue
            desired = {
                "file_url": url[:500], "file_type": file_type,
                "source_document_url": url, "source_document_type": file_type,
                "download_status": _monotonic_document_status(existing.download_status, proposed_status),
                "external_file_id": external_id or existing.external_file_id,
                "file_size": descriptor.file_size if descriptor.file_size is not None else existing.file_size,
                "mime_type": descriptor.mime_type or existing.mime_type,
                "sha256": descriptor.sha256 or existing.sha256,
            }
            changed = [name for name, value in desired.items() if getattr(existing, name) != value]
            for name in changed:
                setattr(existing, name, desired[name])
            items.append(DocumentPersistenceItem(
                existing,
                DocumentPersistenceOutcome.UPDATED if changed else DocumentPersistenceOutcome.UNCHANGED,
            ))
        return DocumentBatchPersistenceResult(tuple(items), input_count - len(descriptors))

    urls = [str(item.source_document_url).strip() for item in descriptors]
    external_ids = [str(item.external_file_id).strip() for item in descriptors if item.external_file_id]
    predicates = [TenderDocument.source_document_url.in_(urls)]
    if external_ids:
        predicates.append(TenderDocument.external_file_id.in_(external_ids))
    rows = (
        await db.execute(
            select(TenderDocument).where(
                TenderDocument.tender_id == tender.id,
                or_(*predicates),
            )
        )
    ).scalars().all()
    by_url = {str(row.source_document_url or row.file_url): row for row in rows}
    by_external = {str(row.external_file_id): row for row in rows if row.external_file_id}
    items: list[DocumentPersistenceItem] = []
    for descriptor in descriptors:
        url = str(descriptor.source_document_url).strip()
        external_id = str(descriptor.external_file_id or "").strip()
        existing = by_external.get(external_id) if external_id else None
        existing = existing or by_url.get(url)
        file_type = descriptor.source_document_type or descriptor.file_type or "document"
        proposed_status = descriptor.download_status or default_status
        if existing is None:
            existing = TenderDocument(
                tender_id=tender.id,
                file_url=url[:500],
                file_type=file_type,
                source_document_url=url,
                source_document_type=file_type,
                download_status=proposed_status,
                external_file_id=external_id or None,
                file_size=descriptor.file_size,
                mime_type=descriptor.mime_type,
                sha256=descriptor.sha256,
            )
            db.add(existing)
            by_url[url] = existing
            if external_id:
                by_external[external_id] = existing
            items.append(DocumentPersistenceItem(existing, DocumentPersistenceOutcome.CREATED))
            continue
        retain_resolved_url = (
            external_id
            and external_id == str(existing.external_file_id or "")
            and _DOCUMENT_STATUS_RANK.get(existing.download_status or "", 0)
            > _DOCUMENT_STATUS_RANK.get(proposed_status, 0)
        )
        effective_url = str(existing.source_document_url or existing.file_url) if retain_resolved_url else url
        desired = {
            "file_url": effective_url[:500],
            "source_document_url": effective_url,
            "file_type": file_type,
            "source_document_type": file_type,
            "download_status": _monotonic_document_status(existing.download_status, proposed_status),
            "external_file_id": external_id or existing.external_file_id,
            "file_size": descriptor.file_size if descriptor.file_size is not None else existing.file_size,
            "mime_type": descriptor.mime_type or existing.mime_type,
            "sha256": descriptor.sha256 or existing.sha256,
        }
        changed = [name for name, value in desired.items() if getattr(existing, name) != value]
        for name in changed:
            setattr(existing, name, desired[name])
        items.append(
            DocumentPersistenceItem(
                existing,
                DocumentPersistenceOutcome.UPDATED if changed else DocumentPersistenceOutcome.UNCHANGED,
            )
        )
    await db.flush()
    return DocumentBatchPersistenceResult(
        tuple(items),
        input_count - len(descriptors),
    )


async def upsert_tender(
    db: AsyncSession,
    normalized_tender: NormalizedTender,
) -> tuple[Tender, bool]:
    """Compatibility wrapper for proven single-row callers and legacy tests.

    Normal runtime ingestion uses :func:`persist_tender_batch` directly. The
    boolean intentionally translates only CREATED for the old public contract.
    """
    if isinstance(db, AsyncSession):
        result = await persist_tender_batch(db, [normalized_tender], batch_size=1)
        item = result.items[0]
        return item.tender, item.outcome is TenderPersistenceOutcome.CREATED

    # Lightweight historical test doubles do not implement PostgreSQL INSERT
    # .. ON CONFLICT or scalar collections. Keep their adapter isolated here;
    # no runtime AsyncSession can enter this path.
    source_system = normalized_tender.normalized_source_system
    external_id = str(normalized_tender.external_id).strip()
    key = normalized_tender.canonical_source_key
    synced_at = normalized_tender.last_synced_at or datetime.now(timezone.utc)

    result = await db.execute(
        select(Tender).where(Tender.canonical_source_key == key)
    )
    tender = result.scalar_one_or_none()
    if tender is None:
        result = await db.execute(
            select(Tender).where(
                Tender.source_system == source_system,
                Tender.external_id == external_id,
            )
        )
        tender = result.scalar_one_or_none()
    created = tender is None

    if tender is None:
        tender = Tender(
            source_system=source_system,
            external_id=external_id,
            canonical_source_key=key,
            source_url=normalized_tender.source_url,
            title=normalized_tender.title,
            description=normalized_tender.description,
            budget=normalized_tender.budget,
            currency=normalized_tender.currency,
            deadline=normalized_tender.deadline,
            publication_date=normalized_tender.publication_date,
            country=_clean_optional(normalized_tender.country),
            region=_clean_optional(normalized_tender.region),
            sector=_clean_optional(normalized_tender.sector),
            buyer=_clean_optional(normalized_tender.buyer),
            procurement_category=_clean_optional(
                normalized_tender.procurement_category
            ),
            procurement_method=_clean_optional(normalized_tender.procurement_method),
            notice_type=_clean_optional(normalized_tender.notice_type),
            project_id=_clean_optional(normalized_tender.project_id),
            source_metadata_json=normalized_tender.source_metadata_json,
            scrape_status=_clean_optional(normalized_tender.scrape_status) or "success",
            last_synced_at=synced_at,
            status=normalized_tender.status,
            category=normalized_tender.category,
        )
        db.add(tender)
    else:
        for field_name, value in _normalized_source_values(normalized_tender).items():
            setattr(tender, field_name, value)
        tender.last_synced_at = synced_at

    logger.info(
        "tender_source_upsert source_system=%s external_id=%s canonical_source_key=%s status=%s",
        source_system,
        external_id,
        key,
        "created" if created else "updated",
    )
    return tender, created


async def reconcile_past_deadline_open_tenders(
    db: AsyncSession,
    *,
    source_system: str,
    now: datetime | None = None,
) -> int:
    """Close source-scoped OPEN rows whose reliable UTC deadline has passed."""
    normalized_source = normalize_source_system(source_system)
    comparison_time = now or datetime.now(timezone.utc)
    if comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=timezone.utc)
    else:
        comparison_time = comparison_time.astimezone(timezone.utc)

    result = await db.execute(
        select(Tender).where(
            Tender.source_system == normalized_source,
            Tender.status == TenderStatus.OPEN,
            Tender.deadline.is_not(None),
            Tender.deadline < comparison_time,
        )
    )
    tenders = list(result.scalars().all())
    for tender in tenders:
        tender.status = TenderStatus.CLOSED
        tender.last_synced_at = comparison_time
    if tenders:
        logger.info(
            "tender_lifecycle_reconciled source_system=%s transitioned_to_closed=%s",
            normalized_source,
            len(tenders),
        )
    return len(tenders)
