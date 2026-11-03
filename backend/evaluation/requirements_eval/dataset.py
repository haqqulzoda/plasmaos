"""Labelled evaluation set: loading and validation.

Layout of a dataset directory::

    manifest.json            dataset metadata and one entry per document
    sources/<doc_id>.txt     exact text the labels and outputs are scored against
    labels/<doc_id>.json     hand labels for that document

Every gold quote (and every alternative quote) must be locatable in the source
text after normalization (see ``text.py``); ``validate`` reports any that are not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .text import SourceIndex, Span, script_of

REQUIREMENT_TYPES = (
    "ELIGIBILITY", "QUALIFICATION", "FINANCIAL", "TECHNICAL", "DOCUMENT", "SUBMISSION", "EVALUATION",
)
OBLIGATIONS = ("MANDATORY", "SCORED", "PREFERRED", "INFORMATIONAL")
DRAFT_STATUS = "DRAFT_PENDING_PROCUREMENT_EXPERT_REVIEW"


@dataclass(frozen=True)
class GoldItem:
    item_id: str
    quote: str
    alt_quotes: tuple[str, ...]
    requirement_type: str
    obligation: str
    optional: bool
    language: str
    note: str | None
    spans: tuple[Span, ...]

    @property
    def script(self) -> str:
        return script_of(self.quote)


@dataclass
class Document:
    doc_id: str
    meta: dict
    text: str
    items: list[GoldItem] = field(default_factory=list)
    index: SourceIndex | None = None

    @property
    def language(self) -> str:
        return str(self.meta["language"])

    def attribute(self, name: str) -> str:
        value = self.meta.get(name)
        return "unknown" if value in (None, "") else str(value)


@dataclass
class Dataset:
    root: Path
    manifest: dict
    documents: list[Document]
    problems: list[str]

    @property
    def status(self) -> str:
        return str(self.manifest.get("status", ""))

    def by_id(self) -> dict[str, Document]:
        return {document.doc_id: document for document in self.documents}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(root: Path | str) -> Dataset:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    documents: list[Document] = []
    for meta in manifest.get("documents", []):
        doc_id = meta["doc_id"]
        text_path = root / meta["text_path"]
        text = text_path.read_text(encoding="utf-8")
        if sha256_text(text) != meta.get("text_sha256"):
            problems.append(f"{doc_id}: source text SHA-256 does not match the manifest")
        index = SourceIndex(text)
        document = Document(doc_id, meta, text, index=index)
        label_path = root / "labels" / f"{doc_id}.json"
        if not label_path.exists():
            problems.append(f"{doc_id}: no labels file")
            documents.append(document)
            continue
        labels = json.loads(label_path.read_text(encoding="utf-8"))
        seen: set[str] = set()
        for raw in labels.get("items", []):
            item_id = str(raw["id"])
            if item_id in seen:
                problems.append(f"{doc_id}/{item_id}: duplicate item id")
            seen.add(item_id)
            if raw["type"] not in REQUIREMENT_TYPES:
                problems.append(f"{doc_id}/{item_id}: unknown type {raw['type']!r}")
            if raw["obligation"] not in OBLIGATIONS:
                problems.append(f"{doc_id}/{item_id}: unknown obligation {raw['obligation']!r}")
            spans: list[Span] = []
            for quote in [raw["quote"], *raw.get("alt_quotes", [])]:
                located = index.locate_all(quote)
                if not located:
                    problems.append(f"{doc_id}/{item_id}: quote not found in source text: {quote[:60]!r}")
                spans.extend(located)
            document.items.append(GoldItem(
                item_id=item_id,
                quote=raw["quote"],
                alt_quotes=tuple(raw.get("alt_quotes", [])),
                requirement_type=raw["type"],
                obligation=raw["obligation"],
                optional=bool(raw.get("optional", False)),
                language=str(raw.get("language") or meta["language"]),
                note=raw.get("note"),
                spans=tuple(spans),
            ))
        documents.append(document)
    return Dataset(root, manifest, documents, problems)


def summary(dataset: Dataset) -> dict:
    """Counts by language, script and source; used by ``validate`` and the report."""
    rows: dict[str, dict] = {}
    for document in dataset.documents:
        row = rows.setdefault(document.language, {
            "documents": 0, "required_items": 0, "optional_items": 0, "items_by_script": {}, "sources": {},
        })
        row["documents"] += 1
        row["sources"][document.attribute("source")] = row["sources"].get(document.attribute("source"), 0) + 1
        for item in document.items:
            row["optional_items" if item.optional else "required_items"] += 1
            if not item.optional:
                row["items_by_script"][item.script] = row["items_by_script"].get(item.script, 0) + 1
    return {"dataset_id": dataset.manifest.get("dataset_id"), "status": dataset.status, "languages": rows}
