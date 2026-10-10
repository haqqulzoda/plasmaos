"""Sprint 1: deterministic parser for World Bank "Contract Award" notice text.

The notice text is the HTML the procurement API returns in ``notice_text``. It is
flattened into lines (with a bold flag) and read by a small state machine:

* a bold section header opens a status: ``Awarded``/``Evaluated``/``Rejected``/
  ``Not evaluated`` ``Firm(s)``/``Bidder(s)``/``Consultant(s)``;
* a bold ``NAME (supplier id)`` line (or ``Individual Consultant``) is a bidder. Bidders
  listed one after another before any score, price or reason belong to one bid (a joint
  venture or association); the first field closes the bid, so the next name opens a new one;
* ``Beneficial Ownership Details`` blocks repeat firm names and carry a "Summary of Reason"
  that is a declaration, not a rejection reason: the whole block is skipped, and the
  ownership tables (personal data) are never read;
* prices, scores and the rejection reason are copied verbatim; amounts are parsed only when
  the text is exactly ``CUR amount``.

No model, no heuristics on wording: anything the state machine does not recognise is ignored,
and the raw notice text is kept beside the parsed rows.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

PARSER_VERSION = "wb-award-v1"

STATUS_AWARDED = "AWARDED"
STATUS_EVALUATED = "EVALUATED"
STATUS_REJECTED = "REJECTED"
STATUS_NOT_EVALUATED = "NOT_EVALUATED"
STATUSES = (STATUS_AWARDED, STATUS_EVALUATED, STATUS_REJECTED, STATUS_NOT_EVALUATED)

KIND_FIRM = "FIRM"
KIND_INDIVIDUAL = "INDIVIDUAL"

_SECTION = re.compile(
    r"^(awarded|evaluated|rejected|not[\s-]+evaluated|non[\s-]*evaluated)\s+"
    r"(?:firm|bidder|consultant|applicant|supplier|contractor)s?(?:\(s\))?\s*:?$",
    re.IGNORECASE,
)
_SECTION_STATUS = {
    "awarded": STATUS_AWARDED,
    "evaluated": STATUS_EVALUATED,
    "rejected": STATUS_REJECTED,
}
_BIDDER = re.compile(r"^(?P<name>.+?)[\s,]*\((?P<id>\d{3,})\)\s*$")
_INDIVIDUAL = re.compile(r"^individual\s+consultant$", re.IGNORECASE)
_COUNTRY = re.compile(r"^country\s*:\s*(?P<country>.+)$", re.IGNORECASE)
_MONEY = re.compile(r"^(?P<currency>[A-Z]{3})\s*(?P<amount>-?[\d,]+(?:\.\d+)?)?$")
_SCORE_KEY = re.compile(r"^(?P<key>[A-Za-z][A-Za-z /&-]{1,60}):$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")

# Labels (case-insensitive, without a trailing colon) and the field each one fills.
_VALUE_LABELS = {
    "final evaluation price": "evaluated_price",
    "evaluated bid price": "evaluated_price",
    "signed contract price": "signed_contract_price",
    "bid price at opening": "bid_price_at_opening",
}
_REASON_LABELS = {"reason for rejection"}
_SCORE_LABELS = {"scores"}
_BO_LABEL = "beneficial ownership details"
_BO_REASON_LABEL = "summary of reason"
# Fields that close a bid: once one is seen, the next bidder name starts a new bid.
_IGNORED_LABELS = {"price", "evaluation scores", "currency", "amount"}

_HEADER_DATE_LABEL = "date notification of award issued"
_HEADER_DURATION_LABEL = "duration of contract"
_HEADER_MIN_SCORE_LABEL = "minimum qualifying score"


@dataclass
class ParsedMember:
    name: str
    source_id: str | None
    country: str | None
    kind: str


@dataclass
class ParsedBid:
    status: str
    members: list[ParsedMember] = field(default_factory=list)
    evaluated_price: str | None = None
    signed_contract_price: str | None = None
    bid_price_at_opening: str | None = None
    rejection_reason: str | None = None
    scores: dict[str, str] = field(default_factory=dict)
    has_fields: bool = False


@dataclass
class ParsedAwardNotice:
    award_date: date | None = None
    contract_duration: str | None = None
    minimum_qualifying_score: str | None = None
    notice_version: str | None = None
    bids: list[ParsedBid] = field(default_factory=list)


class _Lines(HTMLParser):
    """Flatten notice HTML into (text, bold) lines; ownership tables are dropped."""

    _BREAKS = {"br", "div", "p", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "li", "ul", "span"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, bool]] = []
        self._parts: list[tuple[str, bool]] = []
        self._bold = 0
        self._skip = 0  # script/style and ownership tables
        self._table_skip: list[bool] = []

    def _flush(self) -> None:
        text = " ".join(part for part, _ in self._parts)
        text = _clean(text)
        if text:
            bold = all(is_bold for part, is_bold in self._parts if part.strip())
            self.lines.append((text, bold))
        self._parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style"}:
            self._skip += 1
            return
        if tag == "table":
            classes = (dict(attrs).get("class") or "").casefold()
            ownership = "table-info" in classes
            self._table_skip.append(ownership)
            if ownership:
                self._skip += 1
        if tag in {"b", "strong"}:
            self._bold += 1
            return
        if tag in self._BREAKS and tag != "span":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
            return
        if tag in {"b", "strong"}:
            self._bold = max(0, self._bold - 1)
            return
        if tag == "table":
            self._flush()
            if self._table_skip and self._table_skip.pop():
                self._skip = max(0, self._skip - 1)
            return
        if tag in self._BREAKS and tag != "span":
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "br":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if data.strip():
            self._parts.append((data, self._bold > 0))

    def close(self) -> None:
        super().close()
        self._flush()


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def notice_lines(notice_html: str | None) -> list[tuple[str, bool]]:
    parser = _Lines()
    parser.feed(str(notice_html or ""))
    parser.close()
    return parser.lines


def _label(text: str) -> str:
    return text.rstrip(":").strip().casefold()


def _section_status(text: str) -> str | None:
    match = _SECTION.match(text)
    if not match:
        return None
    word = re.sub(r"[\s-]+", " ", match.group(1).casefold())
    if word in {"not evaluated", "non evaluated", "nonevaluated"}:
        return STATUS_NOT_EVALUATED
    return _SECTION_STATUS.get(word)


def _bidder(text: str, bold: bool) -> ParsedMember | None:
    if not bold:
        return None
    if _INDIVIDUAL.match(text):
        return ParsedMember(name="Individual Consultant", source_id=None, country=None, kind=KIND_INDIVIDUAL)
    match = _BIDDER.match(text)
    if not match:
        return None
    name = match.group("name").strip().rstrip(",").strip()
    if not name:
        return None
    return ParsedMember(name=name, source_id=match.group("id"), country=None, kind=KIND_FIRM)


def _is_known_label(text: str) -> bool:
    label = _label(text)
    return (
        label in _VALUE_LABELS or label in _REASON_LABELS or label in _SCORE_LABELS
        or label in _IGNORED_LABELS or label in {_BO_LABEL, _BO_REASON_LABEL}
        or label in {_HEADER_DATE_LABEL, _HEADER_DURATION_LABEL, _HEADER_MIN_SCORE_LABEL}
    )


def _parse_award_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_world_bank_award_notice(notice_html: str | None) -> ParsedAwardNotice:
    lines = notice_lines(notice_html)
    result = ParsedAwardNotice()
    plain = " ".join(text for text, _ in lines)
    version = re.search(r"Notice Version No:\s*([0-9A-Za-z.]+)", plain)
    result.notice_version = version.group(1) if version else None

    status: str | None = None
    bid: ParsedBid | None = None
    pending: str | None = None  # field awaiting its value line
    header_pending: str | None = None
    reason_parts: list[str] | None = None
    in_scores = False
    score_key: str | None = None
    in_ownership = False
    ownership_form_seen = False

    def close_reason() -> None:
        nonlocal reason_parts
        if bid is not None and reason_parts is not None:
            text = _clean(" ".join(reason_parts))
            bid.rejection_reason = text or bid.rejection_reason
        reason_parts = None

    for text, bold in lines:
        section = _section_status(text) if bold else None
        if section is not None:
            close_reason()
            status, bid, pending, in_scores, score_key = section, None, None, False, None
            in_ownership = False
            continue

        if status is None:
            # Header: award date, duration, minimum score.
            label = _label(text)
            if label in {_HEADER_DATE_LABEL, _HEADER_DURATION_LABEL, _HEADER_MIN_SCORE_LABEL}:
                header_pending = label
                continue
            if header_pending is not None:
                if text.startswith("(") and text.endswith(")"):
                    continue  # "(YYYY/MM/DD)" format hint
                if header_pending == _HEADER_DATE_LABEL:
                    result.award_date = _parse_award_date(text)
                elif header_pending == _HEADER_DURATION_LABEL:
                    result.contract_duration = text[:60]
                else:
                    result.minimum_qualifying_score = text[:20]
                header_pending = None
            continue

        label = _label(text)
        member = _bidder(text, bold)

        if in_ownership:
            # Ownership blocks: a repeated firm name before "Form Date", the form date, the
            # (dropped) table and an optional "Summary of Reason" declaration. The block ends at
            # the next bidder after the form date or at the next score/price/reason label.
            if text.casefold().startswith("form date"):
                ownership_form_seen = True
                continue
            if member is not None and ownership_form_seen:
                in_ownership = False
            elif label in _VALUE_LABELS or label in _REASON_LABELS or label in _SCORE_LABELS or label == "evaluation scores":
                in_ownership = False
            else:
                continue

        if label == _BO_LABEL:
            close_reason()
            in_ownership, ownership_form_seen = True, False
            pending, in_scores, score_key = None, False, None
            continue

        if member is not None:
            close_reason()
            pending, in_scores, score_key = None, False, None
            if bid is None or bid.has_fields:
                bid = ParsedBid(status=status)
                result.bids.append(bid)
            bid.members.append(member)
            continue

        if bid is None:
            continue

        country = _COUNTRY.match(text)
        if country and bid.members and not bid.has_fields:
            bid.members[-1].country = _clean(country.group("country"))[:120] or None
            continue

        if label in _VALUE_LABELS:
            close_reason()
            in_scores, score_key = False, None
            bid.has_fields = True
            pending = _VALUE_LABELS[label]
            continue
        if label in _REASON_LABELS:
            close_reason()
            in_scores, score_key, pending = False, None, None
            bid.has_fields = True
            reason_parts = []
            continue
        if label in _SCORE_LABELS:
            close_reason()
            pending = None
            bid.has_fields = True
            in_scores, score_key = True, None
            continue
        if label in _IGNORED_LABELS:
            close_reason()
            bid.has_fields = True
            pending, in_scores, score_key = None, False, None
            continue

        if reason_parts is not None:
            reason_parts.append(text)
            continue
        if in_scores:
            key = _SCORE_KEY.match(text)
            if key:
                score_key = key.group("key").strip()
                continue
            if score_key and _NUMBER.match(text):
                bid.scores[score_key] = text
                score_key = None
            continue
        if pending is not None:
            if not _is_known_label(text):
                if getattr(bid, pending) is None:
                    setattr(bid, pending, text[:200])
            pending = None
            continue
    close_reason()
    return result


def parse_money(text: str | None) -> tuple[str | None, Decimal | None]:
    """``"USD 2236567.27"`` -> ("USD", 2236567.27); ``"UZS"`` -> ("UZS", None); several -> (None, None)."""
    if not text:
        return None, None
    value = text.strip()
    if ";" in value:
        return None, None
    match = _MONEY.match(value)
    if not match:
        return None, None
    amount = match.group("amount")
    if amount is None:
        return match.group("currency"), None
    try:
        return match.group("currency"), Decimal(amount.replace(",", ""))
    except InvalidOperation:
        return match.group("currency"), None


_LEGAL_FORMS = {
    "LLC", "LLP", "LTD", "LIMITED", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
    "JSC", "OJSC", "CJSC", "PJSC", "OOO", "OAO", "ZAO", "AO", "TOO", "MCHJ", "XK", "QK", "FE", "JV",
    "GMBH", "AG", "SA", "SAU", "SAS", "SARL", "SRL", "SPA", "BV", "NV", "AS", "AB", "OY", "PLC", "PVT",
    "PTE", "KG", "OG", "ZT", "SL", "SLU", "LTDA", "KFT", "DOO", "SP", "ZOO", "SIRKETI", "ANONIM", "TI",
    "VE", "AND", "THE", "LTEE", "PE", "UE", "IP",
}


def normalize_firm_name(name: str | None) -> str:
    """Upper-case ASCII, punctuation out, legal forms out: for grouping, never for display."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).upper()
    text = re.sub(r"\([^)]*\)", " ", text)
    # Dotted abbreviations are one word: "S.L." -> SL, "A.R.S" -> ARS, "L.L.C." -> LLC.
    text = re.sub(r"\b(?:[A-Z]\.\s?)+[A-Z]\b\.?", lambda match: re.sub(r"[.\s]", "", match.group(0)), text)
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    words = [word for word in text.split() if word not in _LEGAL_FORMS]
    return " ".join(words) or re.sub(r"\s+", " ", text).strip()
