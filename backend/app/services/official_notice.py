"""System-generated OFFICIAL_NOTICE source documents (D1-03).

One shared-source ``TenderDocument`` per Tender holds the source's own notice
text, so a SOURCE pursuit can be analysed without a private upload.

Invariants kept by this module:

* The row is written only by source refresh (``persist_tender_batch``) or the
  operator backfill script. No customer action, pursuit command, GET or private
  upload reaches :func:`sync_official_notices`.
* The text is deterministic: HTML-to-text normalization of the Tender's stored
  notice plus a delimited header of Tender source fields. No AI, no paraphrase,
  no timestamps of our own, and absent fields are omitted rather than guessed.
* Rows are never deleted: sealed analysis packs reference them with
  ``ON DELETE RESTRICT`` and pack items keep their own copy of the text.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import html
import logging
import re
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender, TenderDocument

logger = logging.getLogger(__name__)

OFFICIAL_NOTICE_DOCUMENT_TYPE = "OFFICIAL_NOTICE"
OFFICIAL_NOTICE_MIN_CHARS = 300
OFFICIAL_NOTICE_FILE_TYPE = "text/plain"
OFFICIAL_NOTICE_MIME_TYPE = "text/plain"
OFFICIAL_NOTICE_DISPLAY_NAME = "Official notice text"
OFFICIAL_NOTICE_STATUS = "processed"
OFFICIAL_NOTICE_URI_SCHEME = "official-notice"
OFFICIAL_NOTICE_BATCH_SIZE = 500
OFFICIAL_NOTICE_UNIQUE_INDEX = "uq_tender_documents_official_notice"
# Must stay a literal: ON CONFLICT index inference cannot match a bound parameter.
OFFICIAL_NOTICE_INDEX_PREDICATE = "source_document_type = 'OFFICIAL_NOTICE'"

HEADER_OPEN = "=== OFFICIAL NOTICE: SOURCE FIELDS ==="
BODY_OPEN = "=== OFFICIAL NOTICE: NOTICE TEXT ==="

# Sources whose connector keeps the notice's original HTML in the raw payload
# stored as ``Tender.source_metadata_json``. The stored ``description`` of these
# tenders is that HTML collapsed to one line, which loses paragraphs and lists.
# The structured form is used only when it is provably the same content.
RAW_NOTICE_HTML_METADATA_KEYS = {"world_bank": "notice_text"}

_DATE_ONLY_TIMES = (
    (0, 0, 0, 0),
    (23, 59, 59, 999999),
)
_TAG_RE = re.compile(r"<[A-Za-z/!][^>]*>")
_DANGLING_MARKER_RE = re.compile(r"(?m)^(-|[0-9]+\.)\n+(?=\S)")
_ENTITY_RE = re.compile(r"&(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_SPACE_RE = re.compile(r"[ \t\f\v]+")
_ANY_SPACE_RE = re.compile(r"\s+")
_SPACE_MAP = {
    ord(" "): " ",
    ord(" "): " ",
    ord(" "): " ",
    ord("​"): None,
    ord("‌"): None,
    ord("‍"): None,
    ord("﻿"): None,
}
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "dd", "details", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "p", "pre",
        "section", "summary", "table", "tbody", "tfoot", "thead",
    }
)
_SKIP_TAGS = frozenset({"script", "style"})


class _NoticeTextParser(HTMLParser):
    """Structure-preserving, dependency-free HTML to plain text."""

    def __init__(self, *, markers: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        # ``markers=False`` renders the same words without the list bullets and
        # table separators this parser adds, to compare content with the source.
        self._markers = markers
        self.parts: list[str] = []
        self._skip = 0
        self._lists: list[list[Any]] = []
        self._cell_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif self._skip:
            return
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            self._lists.append([tag, 0])
        elif tag == "li":
            self.parts.append("\n")
            if self._lists and self._lists[-1][0] == "ol":
                self._lists[-1][1] += 1
                if self._markers:
                    self.parts.append(f"{self._lists[-1][1]}. ")
            elif self._markers:
                self.parts.append("- ")
        elif tag == "tr":
            self.parts.append("\n")
            self._cell_index = 0
        elif tag in ("td", "th"):
            if self._cell_index:
                self.parts.append(" | " if self._markers else " ")
            self._cell_index += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in _SKIP_TAGS:
            if self._skip:
                self._skip -= 1
        elif self._skip:
            return
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self.parts.append("\n")
        elif tag in ("li", "tr"):
            # The next ``<li>``/``<tr>`` starts its own line; adding one here
            # would put a blank line between every item or row.
            return
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip or not data:
            return
        # Newlines inside an HTML text node are source formatting, not structure.
        self.parts.append(_ANY_SPACE_RE.sub(" ", data.translate(_SPACE_MAP)))


def _finalize_lines(text: str) -> str:
    text = _CONTROL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines: list[str] = []
    blank_pending = False
    for raw_line in text.split("\n"):
        line = _INLINE_SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            blank_pending = bool(lines)
            continue
        if blank_pending:
            lines.append("")
            blank_pending = False
        lines.append(line)
    # ``<li><p>text</p></li>`` leaves the marker alone on its line.
    return _DANGLING_MARKER_RE.sub(r"\1 ", "\n".join(lines))


def notice_text_from_html(value: str | None, *, markers: bool = True) -> str:
    """Deterministically normalize an HTML or plain-text notice to plain text.

    Text without any tag keeps its own line structure; entities are decoded
    only when they are terminated (``&amp;``), so ``AT&T`` and ``R&D`` survive.
    """
    if not value:
        return ""
    source = str(value)
    if _TAG_RE.search(source):
        parser = _NoticeTextParser(markers=markers)
        parser.feed(source)
        parser.close()
        return _finalize_lines("".join(parser.parts))
    decoded = _ENTITY_RE.sub(lambda match: html.unescape(match.group(0)), source)
    return _finalize_lines(decoded.translate(_SPACE_MAP))


def _comparable(value: str) -> str:
    return _ANY_SPACE_RE.sub("", value.translate(_SPACE_MAP))


def _single_line(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _ANY_SPACE_RE.sub(" ", _CONTROL_RE.sub("", str(value)).translate(_SPACE_MAP)).strip()
    return cleaned or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_publication(value: datetime | None) -> str | None:
    return _as_utc(value).strftime("%Y-%m-%d") if value else None


def _format_deadline(value: datetime | None) -> str | None:
    """UTC date, plus a time only when the stored instant carries a real one.

    Connectors store midnight (date-only source) or 23:59:59.999999 (end of the
    stated day) when a source gave no time; printing those would invent a time.
    """
    if value is None:
        return None
    instant = _as_utc(value)
    clock = (instant.hour, instant.minute, instant.second, instant.microsecond)
    if clock in _DATE_ONLY_TIMES:
        return f"{instant:%Y-%m-%d} (UTC date; no time stated)"
    return f"{instant:%Y-%m-%d %H:%M} UTC"


def notice_body_text(
    *,
    source_system: str | None,
    description: str | None,
    source_metadata: Any = None,
) -> tuple[str, str]:
    """Return ``(eligibility_text, body_text)`` for one tender.

    ``eligibility_text`` is the normalized stored description (the threshold is
    measured on it). ``body_text`` is the same content with the source's
    paragraphs and lists restored when the raw HTML is available and equal to
    the description apart from whitespace; otherwise it is the description.
    """
    stored = notice_text_from_html(description)
    key = RAW_NOTICE_HTML_METADATA_KEYS.get((source_system or "").strip().casefold())
    if key and stored and isinstance(source_metadata, dict):
        raw = source_metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            structured = notice_text_from_html(raw)
            # Same words as the stored description, ignoring whitespace and the
            # bullets/separators that only the structured rendering adds.
            if structured and _comparable(
                notice_text_from_html(raw, markers=False)
            ) == _comparable(stored):
                return stored, structured
    return stored, stored


def compose_notice_text(
    *,
    title: str | None,
    reference: str | None,
    notice_type: str | None,
    buyer: str | None,
    country: str | None,
    publication_date: datetime | None,
    deadline: datetime | None,
    source_url: str | None,
    body: str,
) -> str:
    fields = (
        ("Title", _single_line(title)),
        ("Reference", _single_line(reference)),
        ("Notice type", _single_line(notice_type)),
        ("Borrower/client", _single_line(buyer)),
        ("Country", _single_line(country)),
        ("Publication date", _format_publication(publication_date)),
        ("Deadline", _format_deadline(deadline)),
        ("Source URL", _single_line(source_url)),
    )
    header = [HEADER_OPEN, *(f"{label}: {value}" for label, value in fields if value)]
    return "\n".join([*header, "", BODY_OPEN, body])


def build_official_notice_text(tender: Tender) -> str | None:
    """Notice text for a persisted Tender, or ``None`` when it has no substantive notice."""
    stored, body = notice_body_text(
        source_system=tender.source_system,
        description=tender.description,
        source_metadata=tender.source_metadata_json,
    )
    if len(stored) < OFFICIAL_NOTICE_MIN_CHARS:
        return None
    return compose_notice_text(
        title=tender.title,
        reference=tender.external_id,
        notice_type=tender.notice_type,
        buyer=tender.buyer,
        country=tender.country,
        publication_date=tender.publication_date,
        deadline=tender.deadline,
        source_url=tender.source_url,
        body=body,
    )


def official_notice_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def official_notice_file_url(source_system: str, external_id: str) -> str:
    """Stable, non-downloadable identifier; never a fetchable URL."""
    identifier = (
        f"{OFFICIAL_NOTICE_URI_SCHEME}://"
        f"{quote(str(source_system), safe='')}/{quote(str(external_id), safe='')}"
    )
    if len(identifier) <= 500:
        return identifier
    digest = hashlib.sha256(f"{source_system}:{external_id}".encode()).hexdigest()
    return f"{OFFICIAL_NOTICE_URI_SCHEME}://{quote(str(source_system), safe='')}/sha256-{digest}"


def is_official_notice(document: Any) -> bool:
    return getattr(document, "source_document_type", None) == OFFICIAL_NOTICE_DOCUMENT_TYPE


def not_official_notice():
    """SQL clause: the row is an ordinary source attachment (NULL types included)."""
    return or_(
        TenderDocument.source_document_type.is_(None),
        TenderDocument.source_document_type != OFFICIAL_NOTICE_DOCUMENT_TYPE,
    )


def only_official_notice():
    return TenderDocument.source_document_type == OFFICIAL_NOTICE_DOCUMENT_TYPE


@dataclass(frozen=True)
class OfficialNoticeSyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0

    def __add__(self, other: "OfficialNoticeSyncResult") -> "OfficialNoticeSyncResult":
        return OfficialNoticeSyncResult(
            created=self.created + other.created,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
        )


async def sync_official_notices(
    db: AsyncSession,
    tenders: Iterable[Tender],
    *,
    dry_run: bool = False,
    batch_size: int = OFFICIAL_NOTICE_BATCH_SIZE,
) -> OfficialNoticeSyncResult:
    """Create or update OFFICIAL_NOTICE rows set-wise; the caller owns the transaction.

    One lookup of the existing notice hashes and at most one conflict-safe
    upsert per batch. Unchanged text issues no write. A tender whose notice is
    (now) too short keeps its existing row untouched: rows are never deleted
    because sealed packs restrict deletion of what they were built from.
    """
    unique: dict[UUID, Tender] = {}
    for tender in tenders:
        if tender is not None and tender.id is not None:
            unique.setdefault(tender.id, tender)
    ordered = sorted(unique.values(), key=lambda item: str(item.id))
    total = OfficialNoticeSyncResult()
    for start in range(0, len(ordered), batch_size):
        total = total + await _sync_batch(db, ordered[start : start + batch_size], dry_run=dry_run)
    if total.created or total.updated or total.failed:
        logger.info(
            "official_notice_sync created=%s updated=%s unchanged=%s skipped=%s failed=%s dry_run=%s",
            total.created, total.updated, total.unchanged, total.skipped, total.failed, dry_run,
        )
    return total


async def _sync_batch(
    db: AsyncSession,
    batch: list[Tender],
    *,
    dry_run: bool,
) -> OfficialNoticeSyncResult:
    desired: dict[UUID, tuple[Tender, str]] = {}
    skipped = failed = 0
    for tender in batch:
        try:
            text = build_official_notice_text(tender)
        except Exception as exc:  # A pathological notice must not fail source refresh.
            failed += 1
            logger.error(
                "official_notice_build_failed canonical_source_key=%s error_type=%s",
                tender.canonical_source_key, type(exc).__name__,
            )
            continue
        if text is None:
            skipped += 1
            continue
        desired[tender.id] = (tender, text)
    if not desired:
        return OfficialNoticeSyncResult(skipped=skipped, failed=failed)

    existing = {
        row.tender_id: row.sha256
        for row in (
            await db.execute(
                select(TenderDocument.tender_id, TenderDocument.sha256).where(
                    TenderDocument.tender_id.in_(list(desired)),
                    only_official_notice(),
                )
            )
        ).all()
    }
    rows: list[dict[str, Any]] = []
    created = updated = unchanged = 0
    for tender_id, (tender, text) in desired.items():
        digest = official_notice_sha256(text)
        if tender_id in existing:
            if existing[tender_id] == digest:
                unchanged += 1
                continue
            updated += 1
        else:
            created += 1
        rows.append(
            {
                "id": uuid4(),
                "tender_id": tender_id,
                "file_url": official_notice_file_url(tender.source_system, tender.external_id),
                "file_type": OFFICIAL_NOTICE_FILE_TYPE,
                "source_document_url": tender.source_url[:1000] if tender.source_url else None,
                "source_document_type": OFFICIAL_NOTICE_DOCUMENT_TYPE,
                "download_status": OFFICIAL_NOTICE_STATUS,
                "download_error": None,
                "external_file_id": None,
                "storage_path": None,
                "file_size": len(text.encode()),
                "mime_type": OFFICIAL_NOTICE_MIME_TYPE,
                "sha256": digest,
                "parsed_text": text,
            }
        )
    if rows and not dry_run:
        statement = postgresql_insert(TenderDocument).values(rows)
        excluded = statement.excluded
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[TenderDocument.tender_id],
                index_where=sql_text(OFFICIAL_NOTICE_INDEX_PREDICATE),
                set_={
                    "file_url": excluded.file_url,
                    "source_document_url": excluded.source_document_url,
                    "download_status": excluded.download_status,
                    "download_error": None,
                    "file_size": excluded.file_size,
                    "sha256": excluded.sha256,
                    "parsed_text": excluded.parsed_text,
                },
                # A concurrent writer that stored the same text is not rewritten.
                where=TenderDocument.sha256.is_distinct_from(excluded.sha256),
            )
        )
    return OfficialNoticeSyncResult(
        created=created, updated=updated, unchanged=unchanged, skipped=skipped, failed=failed
    )
