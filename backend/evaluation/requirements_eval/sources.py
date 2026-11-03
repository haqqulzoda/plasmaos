"""Build evaluation source texts from public tender notices.

Two public sources are supported:

* World Bank procurement notices (``search.worldbank.org/api/v2/procnotices``):
  the ``notice_text`` HTML is converted to plain text with paragraph breaks.
* UzEx e-tender lots (``apietender.uzex.uz/api/common/GetTrade/<id>/0``): the lot
  title, additional description, lot-specific fields (``js_fields``) and the
  qualification fields (``js_qualification_fields``) are joined with blank lines.
  Contact persons, phone numbers and customer addresses are not included.

Every built text has e-mail addresses and phone numbers replaced with
``[REDACTED]``. Named contact persons were also replaced when the set was built; the
names themselves are not stored in the repository (the manifest records only how many
were redacted). The text written to the dataset is the exact input that labels and
model outputs are scored against, and its SHA-256 is recorded in the manifest.
``matches_with_redactions`` checks a freshly rebuilt text against a stored one without
needing the redacted names.

This module performs network access only through ``fetch_*`` and only when the
operator runs ``scripts/eval_requirement_extraction.py build-sources``.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from html.parser import HTMLParser

WORLD_BANK_API = "https://search.worldbank.org/api/v2/procnotices"
WORLD_BANK_NOTICE_URL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"
UZEX_TRADE_API = "https://apietender.uzex.uz/api/common/GetTrade/{id}/0"
UZEX_LOT_URL = "https://etender.uzex.uz/lot/{id}"
USER_AGENT = "plasma-eval-source-builder/0 (public-notice evaluation set)"

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone/fax numbers: an international "+" number, or digits right after a phone/fax keyword.
# Dates, contract numbers and amounts are deliberately not matched.
_PHONE = re.compile(
    r"\+\s?\d[\d\s\-()]{6,}\d"
    r"|(?<=[:.\s])(?:\(\d{2,5}\)\s?)?\d{2,3}[\s\-]\d{2,3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)(?![.,]\d)"
    r"|(?<!\d)(?<!\d[.,])\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)(?![.,]\d)"
)
_PHONE_LABELLED = re.compile(
    r"(?i)(\b(?:tel|phone|telephone|fax|mobile|тел|телефон|факс|моб)\.?(?:\s*/\s*(?:fax|факс)\.?)?"
    r"[\s\-:.№]*(?:no\.?)?[\s\-:.]*)(\(?\+?\s?\d[\d\s\-()/.]{5,}\d)"
)
REDACTED = "[REDACTED]"
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(markup or ""))
    return tidy("".join(parser.parts))


def tidy(text: str) -> str:
    """Collapse runs of spaces, trim lines, and keep single blank lines between paragraphs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def redact(text: str, names: list[str] | tuple[str, ...] = ()) -> str:
    text = _EMAIL.sub(REDACTED, text)
    text = _PHONE_LABELLED.sub(lambda match: match.group(1) + REDACTED, text)
    text = _PHONE.sub(REDACTED, text)
    for name in names:
        text = text.replace(name, REDACTED)
    return text


def matches_with_redactions(stored: str, rebuilt: str, max_redacted_length: int = 120) -> bool:
    """True when ``rebuilt`` equals ``stored`` except where ``stored`` has ``[REDACTED]``.

    Each ``[REDACTED]`` may stand for any single-line text of up to ``max_redacted_length``
    characters, so a rebuilt text that still contains a name matches the stored text.
    """
    parts = stored.split(REDACTED)
    pattern = f"[^\\n]{{0,{max_redacted_length}}}?".join(re.escape(part) for part in parts)
    return re.fullmatch(pattern, rebuilt, flags=re.DOTALL) is not None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_json(url: str, timeout: int = 60) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public hosts
        return json.loads(response.read().decode("utf-8"))


def fetch_world_bank(notice_id: str) -> dict:
    fields = "id,notice_text,notice_lang_name,project_ctry_name,notice_type,bid_description,project_id,submission_date"
    payload = _get_json(f"{WORLD_BANK_API}?format=json&id={notice_id}&fl={fields}")
    rows = payload.get("procnotices") or []  # type: ignore[union-attr]
    if not rows:
        raise LookupError(f"World Bank notice {notice_id} not found")
    return rows[0]


def fetch_uzex(lot_id: str) -> dict:
    return _get_json(UZEX_TRADE_API.format(id=lot_id))  # type: ignore[return-value]


def world_bank_text(row: dict) -> str:
    return html_to_text(row.get("notice_text") or "")


def uzex_text(row: dict) -> str:
    """Lot title, additional description, lot fields and qualification fields; no contacts."""
    parts: list[str] = [str(row.get("name") or ""), str(row.get("addon_description") or "")]
    for field in row.get("js_fields") or []:
        parts += [str(field.get("label") or ""), str(field.get("description") or "")]
    for field in row.get("js_qualification_fields") or []:
        parts += [str(field.get("name") or ""), str(field.get("description") or "")]
    return tidy("\n\n".join(tidy(part) for part in parts if part and part.strip()))


def build_text(source: str, row: dict, names: list[str] | tuple[str, ...] = ()) -> str:
    if source == "world_bank":
        raw = world_bank_text(row)
    elif source == "uzex":
        raw = uzex_text(row)
    else:
        raise ValueError(f"unknown source {source!r}")
    return redact(raw, names)
