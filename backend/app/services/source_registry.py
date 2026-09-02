"""Immutable connector capability registry and canonical refresh result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

class RefreshStrategy(str, Enum):
    BOUNDED_LATEST_WINDOW = "bounded_latest_window"
    BOUNDED_CURRENT_SET = "bounded_current_set"
    BOUNDED_SURFACES = "bounded_surfaces"
    BOUNDED_LISTING = "bounded_listing"


class DocumentPolicy(str, Enum):
    SEPARATE_TARGETED = "separate_targeted"
    METADATA_ONLY = "metadata_only"
    EXPLICIT_HYDRATION = "explicit_hydration"
    ASYNC_ENRICHMENT = "async_enrichment"
    ACCESS_REQUIRED = "access_required"


class OptionKind(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    CHOICE = "choice"


@dataclass(frozen=True)
class SourceOption:
    kind: OptionKind
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()

    def validate(self, name: str, value: Any) -> Any:
        if self.kind is OptionKind.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean")
            return value
        if self.kind is OptionKind.INTEGER:
            if isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
            parsed = int(value)
            if self.minimum is not None and parsed < self.minimum:
                raise ValueError(f"{name} must be between {self.minimum} and {self.maximum}")
            if self.maximum is not None and parsed > self.maximum:
                raise ValueError(f"{name} must be between {self.minimum} and {self.maximum}")
            return parsed
        parsed = str(value or "").strip()
        if parsed not in self.choices:
            raise ValueError(f"unsupported {name}: {parsed!r}")
        return parsed


@dataclass(frozen=True)
class SourceExecutionResult:
    source_system: str
    status: str
    message: str
    fetched_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    rejected_count: int = 0
    failed_count: int = 0
    documents_discovered_count: int = 0
    documents_queued_count: int = 0
    fallback_used: bool = False
    skip_reasons: Mapping[str, int] = field(default_factory=dict)
    failure_stage: str | None = None
    failure_class: str | None = None
    retryable: bool | None = None
    elapsed_ms: int | None = None
    fetch_elapsed_ms: int | None = None
    normalize_elapsed_ms: int | None = None
    persist_elapsed_ms: int | None = None
    document_dispatch_elapsed_ms: int | None = None
    http_request_count: int | None = None
    http_retry_count: int | None = None
    http_failure_count: int | None = None
    source_newest_published_at: Any = None
    source_oldest_published_at: Any = None
    execution_health: str | None = None
    freshness_health: str | None = None
    coverage_health: str | None = None
    checkpoint: str | None = None


Runner = Callable[[AsyncSession, Mapping[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    display_name: str
    runner: Runner
    refresh_strategy: RefreshStrategy
    document_policy: DocumentPolicy
    defaults: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, SourceOption] = field(default_factory=dict)
    refresh_enabled: bool = True
    customer_visible: bool = True
    operator_visible: bool = True
    supports_documents: bool = True
    supports_checkpoint: bool = False
    supports_force: bool = True
    fallback_supported: bool = False
    max_fetch_concurrency: int = 1
    max_document_concurrency: int = 1

    def validate_options(self, values: Mapping[str, Any] | None) -> dict[str, Any]:
        raw = dict(values or {})
        unknown = sorted(set(raw) - set(self.options))
        if unknown:
            raise ValueError(
                f"unsupported {self.key} refresh option(s): {', '.join(unknown)}"
            )
        validated = {
            name: self.options[name].validate(name, value)
            for name, value in raw.items()
        }
        if validated.get("download_documents"):
            raise ValueError(
                "download_documents is not part of metadata refresh; use the "
                "targeted document capability"
            )
        return validated


def _count(result: Any, *names: str) -> int:
    for name in names:
        value = getattr(result, name, None)
        if value is not None:
            return int(value or 0)
    return 0


def adapt_execution_result(source_system: str, result: Any) -> SourceExecutionResult:
    raw_status = str(getattr(result, "status", "failed")).casefold()
    status = {
        "success": "completed",
        "completed": "completed",
        "partial": "partial",
        "source_unavailable": "source_unavailable",
    }.get(raw_status, "failed")
    skipped = _count(result, "skipped_count", "skipped")
    failed = _count(result, "failed_count", "failed")
    return SourceExecutionResult(
        source_system=source_system,
        status=status,
        message=str(getattr(result, "message", "Source refresh finished.")),
        fetched_count=_count(result, "fetched_count", "fetched"),
        created_count=_count(result, "new_count", "created_count", "created"),
        updated_count=_count(result, "updated_count", "updated"),
        unchanged_count=_count(result, "unchanged_count", "unchanged"),
        skipped_count=skipped,
        rejected_count=(
            _count(result, "rejected_count")
            if hasattr(result, "rejected_count")
            else skipped + failed
        ),
        failed_count=failed,
        documents_discovered_count=_count(
            result, "documents_discovered_count", "attachment_count", "attachments_discovered"
        ),
        documents_queued_count=_count(result, "documents_queued_count"),
        fallback_used=bool(getattr(result, "fallback_used", False)),
        skip_reasons=MappingProxyType(dict(getattr(result, "skip_reasons", {}) or {})),
        failure_stage=getattr(result, "failure_stage", None),
        failure_class=getattr(result, "failure_class", None),
        retryable=getattr(result, "retryable", None),
        elapsed_ms=getattr(result, "elapsed_ms", None),
        fetch_elapsed_ms=getattr(result, "fetch_elapsed_ms", None),
        normalize_elapsed_ms=getattr(result, "normalize_elapsed_ms", None),
        persist_elapsed_ms=getattr(result, "persist_elapsed_ms", None),
        document_dispatch_elapsed_ms=getattr(result, "document_dispatch_elapsed_ms", None),
        http_request_count=getattr(result, "http_request_count", None),
        http_retry_count=getattr(result, "http_retry_count", None),
        http_failure_count=getattr(result, "http_failure_count", None),
        source_newest_published_at=getattr(result, "source_newest_published_at", None),
        source_oldest_published_at=getattr(result, "source_oldest_published_at", None),
        execution_health=getattr(result, "execution_health", None),
        freshness_health=getattr(result, "freshness_health", None),
        coverage_health=getattr(result, "coverage_health", None),
    )


async def _run_uzex(db: AsyncSession, options: Mapping[str, Any]) -> Any:
    from app.api.endpoints.tenders import _sync_uzex_tenders
    return await _sync_uzex_tenders(db=db)


async def _run_world_bank(db: AsyncSession, options: Mapping[str, Any]) -> Any:
    from app.api.endpoints.tenders import sync_world_bank_tenders
    return await sync_world_bank_tenders(**options, db=db)


async def _run_giz(db: AsyncSession, options: Mapping[str, Any]) -> Any:
    from app.api.endpoints.tenders import sync_giz_tenders
    return await sync_giz_tenders(**options, db=db)


async def _run_ebrd(db: AsyncSession, options: Mapping[str, Any]) -> Any:
    from app.api.endpoints.tenders import sync_ebrd_tenders
    return await sync_ebrd_tenders(**options, db=db)


async def _run_adb(db: AsyncSession, options: Mapping[str, Any]) -> Any:
    from app.api.endpoints.tenders import sync_adb_tenders
    return await sync_adb_tenders(**options, db=db)


BOOL = SourceOption(OptionKind.BOOLEAN)


def _integer(minimum: int, maximum: int) -> SourceOption:
    return SourceOption(OptionKind.INTEGER, minimum=minimum, maximum=maximum)


_DEFINITIONS = (
    SourceDefinition("uzex", "UzEx", _run_uzex, RefreshStrategy.BOUNDED_LATEST_WINDOW, DocumentPolicy.SEPARATE_TARGETED, supports_checkpoint=False),
    SourceDefinition("world_bank", "World Bank", _run_world_bank, RefreshStrategy.BOUNDED_CURRENT_SET, DocumentPolicy.METADATA_ONLY, MappingProxyType({"max_pages": 25, "rows": 100, "active_only": True, "dry_run": False}), MappingProxyType({"max_pages": _integer(1, 100), "rows": _integer(1, 100), "active_only": BOOL, "dry_run": BOOL})),
    SourceDefinition("giz", "GIZ", _run_giz, RefreshStrategy.BOUNDED_SURFACES, DocumentPolicy.EXPLICIT_HYDRATION, MappingProxyType({"max_pages": 6, "dry_run": False, "download_documents": False}), MappingProxyType({"max_pages": _integer(1, 12), "dry_run": BOOL, "download_documents": BOOL})),
    SourceDefinition("ebrd", "EBRD", _run_ebrd, RefreshStrategy.BOUNDED_LISTING, DocumentPolicy.ACCESS_REQUIRED, MappingProxyType({"max_items": 50, "detail_items": 25, "active_only": True, "dry_run": False}), MappingProxyType({"max_items": _integer(1, 200), "detail_items": _integer(0, 100), "active_only": BOOL, "dry_run": BOOL})),
    SourceDefinition("adb", "ADB", _run_adb, RefreshStrategy.BOUNDED_LISTING, DocumentPolicy.ASYNC_ENRICHMENT, MappingProxyType({"max_items": 500, "max_pages": 25, "feed_type": "invitation_for_bids", "dry_run": False, "download_documents": False}), MappingProxyType({"max_items": _integer(1, 2000), "max_pages": _integer(1, 100), "feed_type": SourceOption(OptionKind.CHOICE, choices=("invitation_for_bids",)), "dry_run": BOOL, "download_documents": BOOL}), fallback_supported=True),
)

SOURCE_REGISTRY: Mapping[str, SourceDefinition] = MappingProxyType(
    {definition.key: definition for definition in _DEFINITIONS}
)


def get_source_definition(source_system: str) -> SourceDefinition:
    raw_key = str(source_system or "").strip().casefold().replace("-", "_")
    try:
        return SOURCE_REGISTRY[raw_key]
    except KeyError as exc:
        raise KeyError(f"unknown tender source: {source_system!r}") from exc


def validate_source_refresh_options(source_system: str, options: Mapping[str, Any] | None) -> dict[str, Any]:
    return get_source_definition(source_system).validate_options(options)


async def execute_source_refresh(source_system: str, db: AsyncSession, options: Mapping[str, Any] | None = None) -> SourceExecutionResult:
    definition = get_source_definition(source_system)
    if not definition.refresh_enabled:
        raise RuntimeError(f"{definition.key} refresh is disabled")
    validated = definition.validate_options(options)
    effective = {**definition.defaults, **validated}
    return adapt_execution_result(definition.key, await definition.runner(db, effective))
