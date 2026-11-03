"""Offline tests for the requirement-extraction evaluation harness (no network, no provider)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evaluation.requirements_eval import adapters, dataset as ds, live, scoring, sources
from evaluation.requirements_eval.adapters import Prediction
from evaluation.requirements_eval.text import SourceIndex, normalize, script_of

DATASET = Path(__file__).resolve().parent / "evaluation" / "datasets" / "req_eval_v0_draft"


@pytest.fixture(scope="module")
def data() -> ds.Dataset:
    return ds.load(DATASET)


def test_dataset_is_valid_draft_with_ten_documents_per_language(data):
    assert data.problems == []
    assert data.status == ds.DRAFT_STATUS
    counts = {language: 0 for language in ("en", "ru", "uz")}
    for document in data.documents:
        counts[document.language] += 1
        assert document.meta["url"].startswith("https://")
        assert document.meta["source_ref"]
        assert any(not item.optional for item in document.items)
    assert all(count >= 10 for count in counts.values()), counts


def test_dataset_texts_hold_no_email_addresses_or_labelled_phone_numbers(data):
    for document in data.documents:
        assert not sources._EMAIL.search(document.text), document.doc_id
        assert not sources._PHONE_LABELLED.search(document.text), document.doc_id


def test_oracle_predictions_score_perfectly(data):
    run = {d.doc_id: [Prediction(item.quote, item.obligation) for item in d.items] for d in data.documents}
    results = scoring.score_run(data, run)
    overall = scoring.overall(results)
    assert overall["recall"] == 1.0
    assert overall["precision"] == 1.0
    assert overall["mandatory_agreement"] == 1.0


def test_missing_outputs_are_not_scored_as_misses_by_the_cli_but_are_flagged(data):
    document = data.documents[0]
    result = scoring.score_document(document, None)
    assert result.has_output is False
    assert all(not outcome.matched for outcome in result.items)


def test_unlocated_and_duplicate_predictions(data):
    document = next(d for d in data.documents if any(i.alt_quotes for i in d.items))
    item = next(i for i in document.items if i.alt_quotes and not i.optional)
    predictions = [
        Prediction(item.quote, "MANDATORY"),
        Prediction(item.alt_quotes[0], "MANDATORY"),
        Prediction("This sentence does not occur in the notice at all.", None),
    ]
    result = scoring.score_document(document, predictions)
    statuses = [outcome.status for outcome in result.predictions]
    assert statuses == ["MATCHED", "DUPLICATE", "UNLOCATED"]
    total = scoring.counts([result])
    metrics = scoring.metrics(total)
    assert metrics["precision"] == 0.5  # duplicate excluded, unlocated counted
    assert metrics["unlocated_rate"] == pytest.approx(1 / 3)


def test_partial_quote_overlap_rule():
    index = SourceIndex("Late Bids will be rejected. Electronic bidding will not be permitted.")
    gold = index.locate_all("Late Bids will be rejected.")
    longer = index.locate_all("Late Bids will be rejected. Electronic bidding will not be permitted.")
    assert scoring.best_overlap(gold, longer) == 1.0  # shorter span fully inside


def test_uzbek_apostrophe_and_whitespace_variants_locate():
    text = "Ishtirokchi korruptsiyaning oldini olish bo‘yicha  bayonoti\n(shakl № 5)"
    index = SourceIndex(text)
    assert index.locate_all("ishtirokchi korruptsiyaning oldini olish bo'yicha bayonoti")
    assert index.locate_all("Ishtirokchi korruptsiyaning oldini olish boʻyicha bayonoti")
    assert not index.locate_all("Ishtirokchi korrupsiyaning oldini olish bo'yicha bayonoti")  # different spelling
    assert normalize("O‘zbekiston") == normalize("Oʻzbekiston") == normalize("O'zbekiston")


def test_script_detection():
    assert script_of("Шартнома тузиш учун қонуний ҳуқуққа эгалик.") == "CYRILLIC"
    assert script_of("Late Bids will be rejected.") == "LATIN"
    assert script_of("osmono’par bino (высотное здание)da") in {"MIXED", "LATIN"}


def test_adapters_accept_pursuit_and_compliance_dumps(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([
        {"kind": "CORPORATE_REQUIREMENT", "original_quote": "q1", "distinction": "SCORED"},
        {"fact": {"kind": "POSITION", "original_quote": "q2", "distinction": "MANDATORY"}},
    ]), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"doc_id": "b", "items": [
        {"exact_quote": "q3", "category": "DQ"}, {"exact_quote": "q4", "category": "NICE_TO_HAVE"}, {"other": 1},
    ]}), encoding="utf-8")
    (tmp_path / "run.json").write_text("{}", encoding="utf-8")
    run = adapters.load_run(tmp_path)
    assert set(run) == {"a", "b"}
    assert [(p.quote, p.obligation) for p in run["a"][0]] == [("q1", "SCORED"), ("q2", "MANDATORY")]
    assert [(p.quote, p.obligation) for p in run["b"][0]] == [("q3", "MANDATORY"), ("q4", "PREFERRED_OR_SCORED")]
    assert run["b"][1]["unparsed_records"] == 1


def test_group_report_flags_small_groups_and_reports_gap(data):
    run = {}
    for document in data.documents:
        keep = [item for item in document.items if not item.optional]
        if document.language != "en":
            keep = keep[: len(keep) // 2]
        run[document.doc_id] = [Prediction(item.quote) for item in keep]
    results = scoring.score_run(data, run)
    report = scoring.group_report(results, "language", reference="en", samples=200)
    assert report["groups"]["en"]["recall"] == 1.0
    assert report["groups"]["ru"]["recall"] < 1.0
    assert report["groups"]["ru"]["recall_gap_vs_reference"] < 0
    low, high = report["groups"]["ru"]["recall_gap_ci95"]
    assert low <= report["groups"]["ru"]["recall_gap_vs_reference"] <= high
    assert report["groups"]["en"]["insufficient"] is False
    by_type = scoring.group_report(results, "procurement_type", samples=50)
    assert any(entry["insufficient"] for entry in by_type["groups"].values())


def test_redaction_keeps_dates_and_amounts():
    text = ("Deadline 25.03.2026, budget USD 350,000. Tel: (992 37) 222-20-49, fax: + 992 37 2217525, "
            "тел. 378-32-92, e-mail: someone@example.org")
    redacted = sources.redact(text, ["Someone Name"])
    assert "25.03.2026" in redacted and "350,000" in redacted
    assert "222-20-49" not in redacted and "2217525" not in redacted and "378-32-92" not in redacted
    assert "@" not in redacted


def test_rebuilt_text_matches_stored_text_modulo_redactions():
    stored = "Attn: Mr. [REDACTED], Director\nTel: [REDACTED]\nBids must be delivered by 14:00."
    assert sources.matches_with_redactions(stored, "Attn: Mr. A Person, Director\nTel: [REDACTED]\nBids must be delivered by 14:00.")
    assert not sources.matches_with_redactions(stored, "Attn: Mr. A Person, Director\nTel: [REDACTED]\nBids must be delivered by 15:00.")
    assert not sources.matches_with_redactions(stored, "Attn: Mr. A\nPerson, Director\nTel: [REDACTED]\nBids must be delivered by 14:00.")


def test_manifest_stores_no_redacted_names(data):
    for document in data.documents:
        assert "redact" not in document.meta
        assert isinstance(document.meta["named_redactions"], int)


def test_live_mode_refuses_without_confirmation_or_key(data, monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(live.LiveModeRefused):
        live.check_preconditions(False)
    monkeypatch.setenv("GEMINI_API_KEY", "set-for-test")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(live.LiveModeRefused):
        live.check_preconditions(True)


def test_live_mode_writes_outputs_that_score_offline(data, monkeypatch, tmp_path):
    """The runner is replaced: no provider is called."""
    monkeypatch.setenv("GEMINI_API_KEY", "set-for-test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    calls: list[str] = []

    async def fake_runner(text: str, doc_id: str, language: str):
        calls.append(language)
        document = data.by_id()[doc_id]
        return [{"quote": item.quote, "obligation": item.obligation} for item in document.items], {"model": "fake"}

    monkeypatch.setitem(live.RUNNERS, "pursuit", fake_runner)
    summary = asyncio.run(live.run(data, pipeline="pursuit", out=tmp_path, confirmed=True, max_docs=3))
    assert len(summary["documents"]) == 3 and not summary["failures"]
    assert calls == [d.language for d in data.documents[:3]]
    stored = adapters.load_run(tmp_path)
    results = [r for r in scoring.score_run(data, {k: v[0] for k, v in stored.items()}) if r.has_output]
    assert scoring.overall(results)["recall"] == 1.0


def test_scope_check_lexicon_counts(tmp_path):
    from evaluation.requirements_eval import scope_check

    module = tmp_path / "m.py"
    module.write_text('_A_TERMS = ("reject", "отклон", "шартнома", "rad et", "ўз")\nOTHER = ("x",)\n', encoding="utf-8")
    coverage = scope_check.lexicon_coverage(module)
    assert coverage["_A_TERMS"] == {"en": 1, "ru": 1, "uz-Cyrl": 2, "uz-Latn": 1}
    assert "OTHER" not in coverage


def test_scope_check_runs_offline_on_product_classifier(data, monkeypatch):
    """Structure only: the measured shares are reported, not asserted, so a fix is not a test failure."""
    from evaluation.requirements_eval import scope_check

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    payload = scope_check.run(data, samples=50)
    assert set(payload["by"]["language"]) == {"en", "ru", "uz"}
    for entry in payload["by"]["language"].values():
        assert entry["items"] > 0 and 0.0 <= entry["blocking_share"] <= 1.0
    assert payload["lexicon"]["TOTAL"]["en"] > 0
