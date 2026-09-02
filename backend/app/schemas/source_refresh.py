"""Explicit customer-safe source catalog, status, and activity schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SourceCatalogItem(BaseModel):
    source_system: str = Field(description="Canonical registry source key.")
    display_name: str = Field(description="Customer display label from the source registry.")
    refresh_enabled: bool
    can_refresh: bool


class SourceRefreshActiveJob(BaseModel):
    job_id: UUID
    status: str
    queued_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None


class SourceRefreshTerminalSummary(BaseModel):
    job_id: UUID
    status: str
    completed_at: datetime
    fetched_count: int = 0
    created_count: int = Field(default=0, description="Tenders first durably inserted during this refresh when counts_authoritative is true.")
    updated_count: int = Field(default=0, description="Existing Tenders with a semantic source-owned change.")
    unchanged_count: int = Field(default=0, description="Accepted Tenders whose source-owned snapshot was unchanged.")
    skipped_count: int = 0
    failed_count: int = 0
    documents_discovered_count: int = 0
    documents_queued_count: int = 0
    counts_authoritative: bool = Field(description="False for lifecycle history predating the SR-2.2 semantic counter boundary.")
    fallback_used: bool = False
    degraded: bool = False
    terminal_reason: str


class SourceRefreshStatusItem(BaseModel):
    source_system: str
    display_name: str
    refresh_enabled: bool
    can_refresh: bool
    active_job: SourceRefreshActiveJob | None = None
    latest_terminal: SourceRefreshTerminalSummary | None = None
    last_clean_completed: SourceRefreshTerminalSummary | None = None
    last_partial: SourceRefreshTerminalSummary | None = None
    last_failure: SourceRefreshTerminalSummary | None = None
    activity_cursor: str


class SourceRefreshActivityEvent(SourceRefreshTerminalSummary):
    source_system: str
    source_display_name: str


class SourceRefreshActivityResponse(BaseModel):
    events: list[SourceRefreshActivityEvent] = Field(default_factory=list)
    next_cursor: str = Field(description="Opaque exclusive cursor for the next activity poll.")
    has_more: bool
