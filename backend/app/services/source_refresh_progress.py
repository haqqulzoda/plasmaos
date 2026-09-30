"""Committed-row bookkeeping for a source refresh execution (integration fix 3b).

A connector can commit tenders and then fail (for example a ConnectError on a later
fetch). The worker then only sees the exception; without this record it wrote the job
as failed with zero counts although the rows were saved. Here, ``persist_tender_batch``
stages its counts and the execution session's commit/rollback events promote or drop
them, so the worker knows exactly what is durable when an exception arrives.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event


@dataclass
class SourceRefreshProgress:
    """Counts staged by the current transaction and counts already committed."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    _pending: list[int] = field(default_factory=lambda: [0, 0, 0])

    def stage(self, created: int, updated: int, unchanged: int) -> None:
        self._pending[0] += int(created or 0)
        self._pending[1] += int(updated or 0)
        self._pending[2] += int(unchanged or 0)

    def _on_commit(self, _session: Any) -> None:
        self.created += self._pending[0]
        self.updated += self._pending[1]
        self.unchanged += self._pending[2]
        self._pending = [0, 0, 0]

    def _on_rollback(self, _session: Any) -> None:
        self._pending = [0, 0, 0]

    @property
    def committed_rows(self) -> int:
        return self.created + self.updated + self.unchanged


_CURRENT: ContextVar[SourceRefreshProgress | None] = ContextVar("source_refresh_progress", default=None)


@contextmanager
def track_source_refresh(session: Any, progress: SourceRefreshProgress) -> Iterator[SourceRefreshProgress]:
    """Record committed counts of ``persist_tender_batch`` calls made on ``session``.

    Sessions without SQLAlchemy events (test doubles) are tracked as committing nothing.
    """
    sync_session = getattr(session, "sync_session", None)
    listeners = (
        (("after_commit", progress._on_commit), ("after_rollback", progress._on_rollback))
        if sync_session is not None
        else ()
    )
    for name, listener in listeners:
        event.listen(sync_session, name, listener)
    token = _CURRENT.set(progress)
    try:
        yield progress
    finally:
        _CURRENT.reset(token)
        for name, listener in listeners:
            event.remove(sync_session, name, listener)


def record_persisted(created: int, updated: int, unchanged: int) -> None:
    """Called by persist_tender_batch; a no-op outside a tracked refresh execution."""
    progress = _CURRENT.get()
    if progress is not None:
        progress.stage(created, updated, unchanged)
