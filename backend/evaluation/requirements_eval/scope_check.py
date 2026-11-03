"""Offline bias check of the compliance extractor's deterministic scope classifier.

``requirement_extractor.classify_requirement_scope`` decides, after the model has
extracted a requirement, whether it can affect bid eligibility. It does this with
keyword lists. This check needs no model and no API key: for every hand-labelled
mandatory bid-stage requirement it simulates a correct extraction (category DQ,
evidence verified, quote = the gold quote cut to the extractor's 15-word limit)
and records whether the classifier marks it as bid-blocking
(``affects_bid_eligibility`` and ``scope_review_status == accepted``).

A gap between languages here is a property of product code, not of any model.

It also counts the classifier's keyword lists by language. The Latin-script terms
are English except the Uzbek words listed in ``UZBEK_LATIN_TERMS`` (classified by
hand when this check was written; re-check when the lists change).
"""

from __future__ import annotations

import ast
import random
import re
from collections import Counter
from pathlib import Path

from .dataset import Dataset

BID_STAGE_TYPES = {"ELIGIBILITY", "QUALIFICATION", "FINANCIAL", "DOCUMENT", "SUBMISSION"}
UZBEK_LATIN_TERMS = {"litsenziya", "rad et", "sertifikat", "tajriba"}
_UZBEK_CYRILLIC_LETTERS = re.compile(r"[ўқғҳЎҚҒҲ]")
_UZBEK_CYRILLIC_WORDS = {"шартнома"}
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
SOURCE_FILENAME = "compiled_master_text"
MAX_QUOTE_WORDS = 15


def _term_language(term: str) -> str:
    if _CYRILLIC.search(term):
        if _UZBEK_CYRILLIC_LETTERS.search(term) or term in _UZBEK_CYRILLIC_WORDS:
            return "uz-Cyrl"
        return "ru"
    return "uz-Latn" if term in UZBEK_LATIN_TERMS else "en"


def lexicon_coverage(module_path: Path) -> dict[str, dict[str, int]]:
    """Keyword-list sizes by language, read statically from the extractor source."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, int]] = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        name = getattr(target, "id", "")
        value = getattr(node, "value", None)
        if not name.endswith("_TERMS") or not isinstance(value, ast.Tuple):
            continue
        terms = [element.value for element in value.elts if isinstance(element, ast.Constant)]
        result[name] = dict(Counter(_term_language(term) for term in terms))
    totals: Counter = Counter()
    for counts in result.values():
        totals.update(counts)
    result["TOTAL"] = dict(totals)
    return result


def _first_words(text: str, limit: int) -> str:
    return " ".join(text.split()[:limit])


def run(dataset: Dataset, *, seed: int = 20261109, samples: int = 2000) -> dict:
    from app.core.agents import requirement_extractor as rx  # product code; imports without settings

    rows: list[dict] = []
    for document in dataset.documents:
        payload = f"[[FILE: {SOURCE_FILENAME}]]\n[[PAGE 1]]\n{document.text}"
        for item in document.items:
            if item.optional or item.obligation != "MANDATORY" or item.requirement_type not in BID_STAGE_TYPES:
                continue
            requirement = rx.TenderRequirement(
                category=rx.RequirementCategory.DQ,
                headline="-",
                source_filename=SOURCE_FILENAME,
                source_page=1,
                exact_quote=_first_words(item.quote, MAX_QUOTE_WORDS),
                validation_status=rx.EvidenceValidationStatus.ACCEPTED,
                validation_reason="Simulated: gold quote from the evaluation set.",
                source_verified=True,
            )
            classified = rx.classify_requirement_scope(requirement, payload)
            rows.append({
                "doc_id": document.doc_id, "item_id": item.item_id, "language": document.language,
                "item_language": item.language, "script": item.script, "type": item.requirement_type,
                "scope": classified.requirement_scope.value,
                "review": classified.scope_review_status.value,
                "blocking": bool(classified.affects_bid_eligibility
                                 and classified.scope_review_status == rx.ScopeReviewStatus.ACCEPTED),
            })
    by: dict[str, dict] = {}
    for key in ("language", "item_language", "script", "type"):
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row[key], []).append(row)
        by[key] = {}
        for value, members in sorted(groups.items()):
            docs = sorted({row["doc_id"] for row in members})
            rng = random.Random(seed)
            draws: list[float] = []
            for _ in range(samples):
                picked = [docs[rng.randrange(len(docs))] for _ in docs]
                sample = [row for doc in picked for row in members if row["doc_id"] == doc]
                if sample:
                    draws.append(sum(row["blocking"] for row in sample) / len(sample))
            draws.sort()
            ci = (draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]) if len(draws) >= 20 else None
            by[key][value] = {
                "items": len(members), "documents": len(docs),
                "blocking": sum(row["blocking"] for row in members),
                "blocking_share": sum(row["blocking"] for row in members) / len(members),
                "blocking_share_ci95": ci,
                "needs_review": sum(row["review"] == "needs_review" for row in members),
                "scopes": dict(Counter(row["scope"] for row in members)),
            }
    return {
        "method": (
            "Gold MANDATORY items of type " + ", ".join(sorted(BID_STAGE_TYPES))
            + " passed to classify_requirement_scope as verified DQ requirements (quote cut to 15 words)."
        ),
        "rows": rows, "by": by,
        "lexicon": lexicon_coverage(Path(rx.__file__)),
    }
