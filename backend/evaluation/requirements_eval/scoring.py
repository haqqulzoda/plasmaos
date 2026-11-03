"""Score predictions against gold labels, overall and per group, with bootstrap intervals.

Matching (per document)
-----------------------
* Every predicted quote is located in the source text (normalized, see ``text.py``).
  A quote that cannot be located is ``unlocated``: it counts against precision and is
  reported separately as a provenance failure.
* A prediction and a gold item match when one of their spans overlaps by at least
  ``MIN_OVERLAP`` of the shorter span (the rule used by ``scripts/bench_pursuit_models.py``).
  Alternative gold quotes are extra spans of the same item.
* Assignment is one-to-one and greedy by overlap; at equal overlap a required item is
  preferred over an optional one.
* A located prediction left unassigned that still overlaps an already matched gold item is a
  ``duplicate`` (for example the same rule quoted in both Uzbek scripts). Duplicates are counted
  and reported but excluded from precision. Any other unassigned prediction is ``unmatched``.
* Optional gold items are excluded from the recall denominator; a prediction matching one is
  neither a hit nor a false positive.

Metrics
-------
recall    = matched required items / required items
precision = matched predictions (required or optional) / (matched + unmatched + unlocated)
F1        = harmonic mean of the two
mandatory agreement = share of matched required items whose predicted obligation agrees with
            the gold label on "mandatory or not" (only where the pipeline provides one)

Groups are compared with a document-level (cluster) bootstrap; a group with fewer than
``MIN_DOCS`` documents or ``MIN_ITEMS`` required items is reported but flagged
``insufficient`` and must not be used to claim or rule out a difference.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from .adapters import Prediction
from .dataset import Dataset, Document, GoldItem
from .text import best_overlap, script_of

MIN_OVERLAP = 0.5
MIN_DOCS = 10
MIN_ITEMS = 30
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20261109


@dataclass
class ItemOutcome:
    item: GoldItem
    matched: bool
    predicted_obligation: str | None = None


@dataclass
class PredictionOutcome:
    prediction: Prediction
    status: str  # MATCHED, MATCHED_OPTIONAL, DUPLICATE, UNMATCHED, UNLOCATED

    @property
    def script(self) -> str:
        return script_of(self.prediction.quote)


@dataclass
class DocumentResult:
    document: Document
    items: list[ItemOutcome] = field(default_factory=list)
    predictions: list[PredictionOutcome] = field(default_factory=list)
    has_output: bool = True


def score_document(document: Document, predictions: list[Prediction] | None) -> DocumentResult:
    if predictions is None:
        return DocumentResult(document, [ItemOutcome(item, False) for item in document.items], [], has_output=False)
    assert document.index is not None
    located = [document.index.locate_all(prediction.quote) for prediction in predictions]
    pairs: list[tuple[float, int, int, int]] = []
    for gold_index, item in enumerate(document.items):
        for pred_index, spans in enumerate(located):
            if not spans:
                continue
            ratio = best_overlap(list(item.spans), spans)
            if ratio >= MIN_OVERLAP:
                pairs.append((ratio, 0 if not item.optional else 1, gold_index, pred_index))
    pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2], pair[3]))
    gold_to_pred: dict[int, int] = {}
    pred_to_gold: dict[int, int] = {}
    for _, _, gold_index, pred_index in pairs:
        if gold_index in gold_to_pred or pred_index in pred_to_gold:
            continue
        gold_to_pred[gold_index] = pred_index
        pred_to_gold[pred_index] = gold_index
    overlapping = {pred_index for _, _, _, pred_index in pairs}
    result = DocumentResult(document)
    for gold_index, item in enumerate(document.items):
        pred_index = gold_to_pred.get(gold_index)
        result.items.append(ItemOutcome(
            item, pred_index is not None,
            predictions[pred_index].obligation if pred_index is not None else None,
        ))
    for pred_index, prediction in enumerate(predictions):
        if not located[pred_index]:
            status = "UNLOCATED"
        elif pred_index in pred_to_gold:
            status = "MATCHED_OPTIONAL" if document.items[pred_to_gold[pred_index]].optional else "MATCHED"
        elif pred_index in overlapping:
            status = "DUPLICATE"
        else:
            status = "UNMATCHED"
        result.predictions.append(PredictionOutcome(prediction, status))
    return result


def score_run(dataset: Dataset, run: dict[str, list[Prediction]]) -> list[DocumentResult]:
    return [score_document(document, run.get(document.doc_id)) for document in dataset.documents]


# --- aggregation ---------------------------------------------------------------------------

ItemFilter = Callable[[GoldItem], bool]
PredFilter = Callable[[PredictionOutcome], bool]


def _is_mandatory(value: str | None) -> bool:
    return value == "MANDATORY"


def counts(
    results: list[DocumentResult], item_filter: ItemFilter | None = None, pred_filter: PredFilter | None = None,
) -> dict[str, int]:
    total = Counter()
    for result in results:
        for outcome in result.items:
            if outcome.item.optional or (item_filter and not item_filter(outcome.item)):
                continue
            total["required"] += 1
            if outcome.matched:
                total["matched_required"] += 1
                if outcome.predicted_obligation is not None:
                    total["obligation_compared"] += 1
                    if _is_mandatory(outcome.predicted_obligation) == _is_mandatory(outcome.item.obligation):
                        total["obligation_agree"] += 1
        for outcome in result.predictions:
            if pred_filter and not pred_filter(outcome):
                continue
            total["predictions"] += 1
            total[outcome.status.lower()] += 1
        total["documents"] += 1
        total["documents_without_output"] += 0 if result.has_output else 1
    return dict(total)


def metrics(total: dict[str, int]) -> dict[str, float | None]:
    required = total.get("required", 0)
    matched = total.get("matched", 0) + total.get("matched_optional", 0)
    denominator = matched + total.get("unmatched", 0) + total.get("unlocated", 0)
    recall = total.get("matched_required", 0) / required if required else None
    precision = matched / denominator if denominator else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    compared = total.get("obligation_compared", 0)
    predictions = total.get("predictions", 0)
    return {
        "recall": recall, "precision": precision, "f1": f1,
        "mandatory_agreement": total.get("obligation_agree", 0) / compared if compared else None,
        "unlocated_rate": total.get("unlocated", 0) / predictions if predictions else None,
    }


def _interval(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 20:
        return None
    ordered = sorted(values)
    return ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]


DOCUMENT_GROUPINGS = ("language", "source", "country", "procurement_type", "format", "value_band")
ITEM_GROUPINGS = ("script", "requirement_type", "obligation", "item_language")

Selector = Callable[[list[DocumentResult]], tuple[list[DocumentResult], ItemFilter | None, PredFilter | None]]


def _selectors(results: list[DocumentResult], grouping: str) -> dict[str, Selector]:
    if grouping in DOCUMENT_GROUPINGS:
        values = sorted({result.document.attribute(grouping) for result in results})
        return {
            value: (lambda rs, v=value: ([r for r in rs if r.document.attribute(grouping) == v], None, None))
            for value in values
        }
    if grouping == "script":
        values = sorted({o.item.script for r in results for o in r.items} | {p.script for r in results for p in r.predictions})
        return {
            value: (lambda rs, v=value: (rs, lambda item: item.script == v, lambda pred: pred.script == v))
            for value in values
        }
    if grouping in {"requirement_type", "obligation", "item_language"}:
        attribute = "language" if grouping == "item_language" else grouping
        values = sorted({getattr(o.item, attribute) for r in results for o in r.items})
        return {
            value: (lambda rs, v=value: (rs, lambda item: getattr(item, attribute) == v, lambda pred: False))
            for value in values
        }
    raise ValueError(f"unknown grouping {grouping!r}")


def _documents_with_items(members: list[DocumentResult], item_filter: ItemFilter | None) -> int:
    return sum(
        1 for r in members
        if any(not o.item.optional and (item_filter is None or item_filter(o.item)) for o in r.items)
    )


def group_report(
    results: list[DocumentResult], grouping: str, *, reference: str | None = None,
    seed: int = BOOTSTRAP_SEED, samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    """Metrics per group value, bootstrap 95% intervals, and the recall gap to ``reference``.

    Document groupings split documents. Item groupings (``script``, ``requirement_type``,
    ``obligation``, ``item_language``) split gold items (and, for ``script``, predictions) inside
    every document. Either way the bootstrap resamples whole documents from the full result set,
    and every group (and its gap to the reference) is computed on the same resample.
    Precision is not defined for ``requirement_type``/``obligation``/``item_language`` groups
    because predictions carry no such label; it is reported as ``None`` there.
    """
    selectors = _selectors(results, grouping)
    report: dict = {"grouping": grouping, "reference": reference, "groups": {}}
    for value, select in selectors.items():
        members, item_filter, pred_filter = select(results)
        total = counts(members, item_filter, pred_filter)
        values = metrics(total)
        if grouping in {"requirement_type", "obligation", "item_language"}:
            values["precision"] = values["f1"] = values["unlocated_rate"] = None
        documents = _documents_with_items(members, item_filter)
        report["groups"][value] = {
            **values, "counts": total, "documents_with_required_items": documents,
            "insufficient": documents < MIN_DOCS or total.get("required", 0) < MIN_ITEMS,
        }
    rng = random.Random(seed)
    draws: dict[str, list[float | None]] = {value: [] for value in selectors}
    for _ in range(samples if results else 0):
        sample = [results[rng.randrange(len(results))] for _ in results]
        for value, select in selectors.items():
            members, item_filter, pred_filter = select(sample)
            draws[value].append(metrics(counts(members, item_filter, pred_filter))["recall"])
    for value, entry in report["groups"].items():
        entry["recall_ci95"] = _interval([v for v in draws[value] if v is not None])
    if reference is not None and reference in report["groups"]:
        reference_recall = report["groups"][reference]["recall"]
        for value, entry in report["groups"].items():
            if value == reference or entry["recall"] is None or reference_recall is None:
                continue
            differences = [
                mine - theirs for mine, theirs in zip(draws[value], draws[reference])
                if mine is not None and theirs is not None
            ]
            entry["recall_gap_vs_reference"] = entry["recall"] - reference_recall
            entry["recall_gap_ci95"] = _interval(differences)
    return report


def overall(results: list[DocumentResult]) -> dict:
    total = counts(results)
    return {**metrics(total), "counts": total}
