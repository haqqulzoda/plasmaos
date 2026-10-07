"""D1-01: pursuit analyzer reliability (retry, fallback, cap, timeout, concurrency).

Every provider interaction is mocked; no network, database, or secret is used.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import requests
import urllib3
from pydantic import ValidationError

from app.core.agents import pursuit_analyzer as analyzer
from app.core.agents.pursuit_analyzer import ExtractedFact, SealedTextInput


BACKEND_DIR = Path(__file__).parent
PRIMARY = "primary-model"
FALLBACKS = ("fallback-one", "fallback-two")
QUOTE = "Bidder shall submit three references."


def _fact(quote: str = QUOTE, normalized: str = "Three references", **overrides) -> ExtractedFact:
    return ExtractedFact(
        kind="CORPORATE_REQUIREMENT", original_quote=quote, normalized_text=normalized,
        category="Bid Submission", requirement_type="PROPOSAL_CONTENT",
        stage_scope="BID_SUBMISSION", distinction="MANDATORY", **overrides,
    )


def _payload(*facts: ExtractedFact) -> str:
    return analyzer.EXTRACTED_FACTS.dump_json(list(facts)).decode()


def _schema_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        analyzer.EXTRACTED_FACTS.validate_json("{not json")
    return caught.value


class _Response:
    def __init__(self, text: str | None, usage: object | None = None):
        self.text = text
        self.usage_metadata = usage


class _Usage:
    prompt_token_count = 1000
    candidates_token_count = 200
    total_token_count = 1700


class FakeClient:
    """Stands in for the SDK client; each call consumes the next scripted outcome."""

    script: list[object] = []
    calls: list[dict[str, object]] = []
    constructed: list[dict[str, object]] = []

    def __init__(self, api_key=None, http_options=None):
        type(self).constructed.append({"api_key": api_key, "http_options": http_options})
        self.models = self

    def generate_content(self, model, contents, config):
        type(self).calls.append(
            {"model": model, "contents": contents, "config": config, "at": analyzer._monotonic()}
        )
        outcome = type(self).script.pop(0)
        if callable(outcome):
            outcome = outcome()  # lets a scripted attempt advance the fake clock, then fail or answer
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome if isinstance(outcome, _Response) else _Response(outcome, _Usage())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    FakeClient.script, FakeClient.calls, FakeClient.constructed = [], [], []
    monkeypatch.setattr(analyzer, "_TimeoutClient", FakeClient)
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    return FakeClient


def _extract() -> analyzer.ChunkFacts:
    item = SealedTextInput(uuid4(), "sealed.txt", QUOTE)
    return analyzer._extract_chunk_sync(item, item.text, "en", "test-key")


def _models_called() -> list[object]:
    return [call["model"] for call in FakeClient.calls]


# --- retry once -------------------------------------------------------------


def test_malformed_json_is_retried_once_then_succeeds(client) -> None:
    client.script = ["{not json", _payload(_fact())]
    facts = _extract()
    assert [fact.original_quote for fact in facts] == [QUOTE]
    assert _models_called() == [PRIMARY, PRIMARY]
    assert facts.meta["attempts"] == 2
    assert facts.meta["model_name"] == PRIMARY
    assert facts.meta["failure_classes"] == ["ValidationError"]


def test_schema_invalid_output_is_retried_once(client) -> None:
    invalid = json.dumps([{"kind": "CORPORATE_REQUIREMENT", "unexpected": True}])
    client.script = [invalid, _payload(_fact())]
    assert len(_extract()) == 1
    assert _models_called() == [PRIMARY, PRIMARY]


def test_empty_response_is_retried_once(client) -> None:
    client.script = ["", "   ", _payload(_fact())]
    facts = _extract()
    # The second empty response exhausts the primary; the first fallback answers.
    assert _models_called() == [PRIMARY, PRIMARY, FALLBACKS[0]]
    assert facts.meta["model_name"] == FALLBACKS[0]
    assert facts.meta["failure_classes"] == ["RuntimeError", "RuntimeError"]


@pytest.mark.parametrize(
    "timeout_error",
    [
        requests.exceptions.ReadTimeout("read timed out"),
        requests.exceptions.ConnectTimeout("connect timed out"),
        TimeoutError("timed out"),
        requests.exceptions.ConnectionError(urllib3.exceptions.ReadTimeoutError(None, "u", "body read timed out")),
    ],
)
def test_timeout_is_retried_once_then_succeeds(client, timeout_error) -> None:
    client.script = [timeout_error, _payload(_fact())]
    facts = _extract()
    assert _models_called() == [PRIMARY, PRIMARY]
    assert facts.meta["attempts"] == 2


def test_non_retryable_provider_error_fails_immediately_as_before(client) -> None:
    client.script = [RuntimeError("quota exhausted"), _payload(_fact())]
    with pytest.raises(RuntimeError, match="quota exhausted"):
        _extract()
    assert _models_called() == [PRIMARY]
    # A connection failure that is not a timeout is not retried either.
    client.calls.clear()
    client.script = [requests.exceptions.ConnectionError("refused")]
    with pytest.raises(requests.exceptions.ConnectionError):
        _extract()
    assert _models_called() == [PRIMARY]


# --- double failure keeps the classified failure ----------------------------


def test_double_failure_raises_the_existing_classified_failure(client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", ())
    client.script = ["{not json", "{still not json"]
    with pytest.raises(ValidationError):  # same type the worker classifies as schema failure today
        _extract()
    assert _models_called() == [PRIMARY, PRIMARY]


def test_double_empty_response_keeps_the_original_runtime_error(client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", ())
    client.script = ["", ""]
    with pytest.raises(RuntimeError, match="Pursuit analyzer returned an empty response") as caught:
        _extract()
    assert type(caught.value) is RuntimeError


def test_double_timeout_raises_the_timeout(client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", ())
    client.script = [requests.exceptions.ReadTimeout("t1"), requests.exceptions.ReadTimeout("t2")]
    with pytest.raises(requests.exceptions.ReadTimeout, match="t2"):
        _extract()


def test_fallbacks_only_after_the_primary_retry_and_in_order(client) -> None:
    client.script = ["{bad", "{bad", "{bad", _payload(_fact())]
    facts = _extract()
    assert _models_called() == [PRIMARY, PRIMARY, FALLBACKS[0], FALLBACKS[1]]
    assert facts.meta["model_name"] == FALLBACKS[1]
    assert facts.meta["attempts"] == 4


def test_every_model_failing_raises_the_last_failure(client) -> None:
    client.script = ["{bad", "{bad", "{bad", requests.exceptions.ReadTimeout("last")]
    with pytest.raises(requests.exceptions.ReadTimeout, match="last"):
        _extract()
    assert len(FakeClient.calls) == 4


def test_primary_success_never_touches_fallbacks(client) -> None:
    client.script = [_payload(_fact())]
    facts = _extract()
    assert _models_called() == [PRIMARY]
    assert facts.meta == {
        "model_name": PRIMARY, "attempts": 1, "failure_classes": [],
        "prompt_tokens": 1000, "output_tokens": 200, "thinking_tokens": 500,
    }


# --- cap and timeout reach the client ---------------------------------------


def test_output_cap_timeout_and_unchanged_contract_are_passed_to_the_client(client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "MAX_OUTPUT_TOKENS", 1234)
    monkeypatch.setattr(analyzer, "REQUEST_TIMEOUT_SECONDS", 7)
    client.script = [_payload(_fact())]
    _extract()
    assert client.constructed == [{"api_key": "test-key", "http_options": {"timeout": 7}}]
    config = client.calls[0]["config"]
    assert config.max_output_tokens == 1234
    assert config.temperature == 0.0
    assert config.system_instruction == analyzer.SYSTEM_PROMPT
    assert config.response_schema == analyzer.PURSUIT_ANALYSIS_RESPONSE_SCHEMA
    assert config.response_mime_type == "application/json"


def test_the_sdk_timeout_reaches_the_http_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pinned SDK ignores http_options timeouts; the shim must forward it to requests."""
    seen: dict[str, object] = {}

    def send(self, request, **kwargs):
        seen.update(kwargs)
        seen["url"] = request.url
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "candidates": [{"content": {"role": "model", "parts": [{"text": "[]"}]}, "finishReason": "STOP"}],
        }).encode()
        response.headers["content-type"] = "application/json"
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    client = analyzer._TimeoutClient(api_key="test-key", http_options={"timeout": 30})
    result = client.models.generate_content(
        model="gemini-test",
        contents="hello",
        config=analyzer.types.GenerateContentConfig(max_output_tokens=99),
    )
    assert result.text == "[]"
    assert seen["timeout"] == (analyzer.CONNECT_TIMEOUT_SECONDS, 30)  # (connect, read)
    assert seen["stream"] is False
    assert "gemini-test:generateContent" in str(seen["url"])


def test_configuration_defaults_and_environment_overrides() -> None:
    code = (
        "import json;from app.core.agents import pursuit_analyzer as a;"
        "print(json.dumps([a.MODEL_NAME, list(a.FALLBACK_MODEL_NAMES), a.MAX_OUTPUT_TOKENS,"
        " a.REQUEST_TIMEOUT_SECONDS, a.CHUNK_BUDGET_SECONDS, a.RUN_BUDGET_SECONDS, a.CHUNK_CONCURRENCY,"
        " a.MODEL_TIMEOUT_SECONDS, a.LONG_PACK_CHARACTERS, a.LONG_MODEL_NAME, list(a.LONG_FALLBACK_MODEL_NAMES),"
        " a.MAX_CHUNK_CHARACTERS, a.LONG_CHUNK_CHARACTERS]))"
    )

    def configured(**environment: str) -> list[object]:
        import os

        env = {key: value for key, value in os.environ.items() if not key.startswith(("GEMINI_PURSUIT", "PURSUIT_"))}
        env.update(environment)
        done = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=True
        )
        return json.loads(done.stdout.strip().splitlines()[-1])

    assert configured() == [
        "gemini-3.8-flash", ["gemini-3.7-flash", "gemini-3.1-pro-preview"], 32768, 90, 240, 480, 3,
        {"gemini-3.1-pro-preview": 150}, 60000, "gemini-3.1-pro-preview", ["gemini-3.8-flash"], 100000, 100000,
    ]
    assert configured(
        GEMINI_PURSUIT_MODEL="m1", GEMINI_PURSUIT_FALLBACK_MODELS="m2, m1,m3,m2",
        GEMINI_PURSUIT_MAX_OUTPUT_TOKENS="4096", GEMINI_PURSUIT_TIMEOUT_SECONDS="45",
        PURSUIT_ANALYSIS_CHUNK_BUDGET_SECONDS="100", PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS="300",
        PURSUIT_ANALYSIS_CHUNK_CONCURRENCY="5", GEMINI_PURSUIT_MODEL_TIMEOUTS="m1=120",
    )[:8] == ["m1", ["m2", "m3"], 4096, 45, 100, 300, 5, {"m1": 120}]
    assert configured(
        GEMINI_PURSUIT_LONG_PACK_CHARS="80000", GEMINI_PURSUIT_LONG_MODEL="l1",
        GEMINI_PURSUIT_LONG_FALLBACK_MODELS="l1,l2", GEMINI_PURSUIT_CHUNK_CHARS="40000",
        GEMINI_PURSUIT_LONG_CHUNK_CHARS="30000",
    )[8:] == [80000, "l1", ["l2"], 40000, 30000]
    assert configured(GEMINI_PURSUIT_MODEL_TIMEOUTS="")[7] == {}
    assert configured(GEMINI_PURSUIT_FALLBACK_MODELS="", PURSUIT_ANALYSIS_CHUNK_CONCURRENCY="0")[1] == []
    assert configured(PURSUIT_ANALYSIS_CHUNK_CONCURRENCY="0")[6] == 1
    assert configured(PURSUIT_ANALYSIS_CHUNK_CONCURRENCY="many")[6] == 3
    assert configured(PURSUIT_ANALYSIS_RUN_BUDGET_SECONDS="soon")[5] == 480


# --- concurrency, ordering, de-duplication ----------------------------------

CHUNK_TEXT = "".join(f"Chunk {index} clause {index}: Bidder shall provide item {index}. " for index in range(8))


@pytest.fixture
def small_chunks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "MAX_CHUNK_CHARACTERS", 80)
    monkeypatch.setattr(analyzer, "CHUNK_OVERLAP_CHARACTERS", 10)
    monkeypatch.setattr(analyzer, "SMALL_CHUNK_OVERLAP_CHARACTERS", 10)
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    # These tests pin the chunk mechanics of one extraction pass; test_d2_analysis_quality covers passes.
    monkeypatch.setattr(analyzer, "SHORT_PASSES", 1)


def _pack(text: str = CHUNK_TEXT) -> list[SealedTextInput]:
    return [SealedTextInput(uuid4(), "sealed.txt", text)]


def _chunk_index(text: str, chunk: str) -> int:
    return [value for _, value in analyzer._chunks(text)].index(chunk)


def _quote_in(chunk: str) -> str:
    return chunk[5:35]  # always locatable inside its own chunk


def test_chunks_run_concurrently_within_the_bound_and_merge_in_chunk_order(small_chunks, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 2)
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}
    total_chunks = len(analyzer._chunks(CHUNK_TEXT))
    assert total_chunks >= 6

    def stub(item, chunk, language, api_key, models=None):
        number = _chunk_index(CHUNK_TEXT, chunk)
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.03 * (total_chunks - number))  # earlier chunks finish last
        with lock:
            state["running"] -= 1
        return analyzer.ChunkFacts(
            [_fact(_quote_in(chunk), f"Item {number}")], {"model_name": PRIMARY, "attempts": 1}
        )

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))

    assert state["peak"] == 2
    assert [fact.fact.normalized_text for fact in result] == [f"Item {n}" for n in range(total_chunks)]
    assert [(c["item_index"], c["chunk_index"]) for c in result.diagnostics["chunks"]] == [
        (0, index) for index in range(total_chunks)
    ]
    assert result.diagnostics["chunk_concurrency"] == 2
    assert result.diagnostics["duplicate_count"] == 0


def test_duplicates_across_overlapping_chunks_keep_the_first_chunk_and_counters_stay_correct(
    small_chunks, monkeypatch
) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 3)
    monkeypatch.setattr(analyzer, "MAX_CHUNK_CHARACTERS", 70)
    monkeypatch.setattr(analyzer, "CHUNK_OVERLAP_CHARACTERS", 30)
    monkeypatch.setattr(analyzer, "SMALL_CHUNK_OVERLAP_CHARACTERS", 30)
    quote = "Three references."
    text = "x" * 40 + " " + quote + " " + "y" * 60  # the quote sits in the overlap of chunks 0 and 1
    assert len(analyzer._chunks(text)) == 3

    def stub(item, chunk, language, api_key, models=None):
        number = _chunk_index(text, chunk)
        if number == 2:
            return []
        time.sleep(0.15 if number == 0 else 0.0)  # chunk 1 finishes first
        facts = [_fact(quote, "Three references", confidence=0.1 if number == 0 else 0.9)]
        if number == 1:
            facts.append(_fact("not present in the source", "Unlocatable quote"))
        return facts  # plain lists (as older tests supply) must keep working

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items(_pack(text), "en"))

    assert len(result) == 1
    assert result[0].fact.confidence == 0.1  # chunk order, not completion order, decides
    counters = result.diagnostics
    assert counters["duplicate_count"] == 1
    assert counters["provenance_rejected_count"] == 1
    assert counters["raw_requirement_count"] == 3
    assert counters["verified_requirement_count"] == 1
    assert counters["chunk_count"] == len(counters["chunks"]) == 3
    assert all(record["attempts"] == 1 for record in counters["chunks"])  # defaults for plain lists


def test_diagnostics_are_count_only_and_record_attempts_retries_latency_and_models(small_chunks, monkeypatch) -> None:
    secret = "PRIVATE-SOURCE-MARKER"
    text = CHUNK_TEXT + secret

    def stub(item, chunk, language, api_key, models=None):
        number = _chunk_index(text, chunk)
        used_fallback = number == 1
        return analyzer.ChunkFacts(
            [_fact(_quote_in(chunk), f"Item {number}")],
            {
                "model_name": FALLBACKS[0] if used_fallback else PRIMARY,
                "attempts": 3 if used_fallback else 1,
                "failure_classes": ["ValidationError", "ReadTimeout"] if used_fallback else [],
                "output_tokens": 11,
            },
        )

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items(_pack(text), "en"))
    diagnostics = result.diagnostics

    chunks = diagnostics["chunks"]
    assert diagnostics["chunk_count"] == len(chunks) > 1
    assert diagnostics["attempt_count"] == sum(c["attempts"] for c in chunks)
    assert diagnostics["retry_count"] == 2
    assert diagnostics["fallback_chunk_count"] == 1
    assert chunks[1]["failure_classes"] == ["ValidationError", "ReadTimeout"]
    assert diagnostics["analysis_models"] == [PRIMARY, FALLBACKS[0]]
    assert diagnostics["model_name"] == f"{PRIMARY},{FALLBACKS[0]}"
    assert all(isinstance(c["latency_ms"], int) and c["latency_ms"] >= 0 for c in chunks)
    assert diagnostics["max_output_tokens"] == analyzer.MAX_OUTPUT_TOKENS
    assert diagnostics["request_timeout_seconds"] == analyzer.REQUEST_TIMEOUT_SECONDS
    serialized = json.dumps(diagnostics)
    assert secret not in serialized and "Bidder shall" not in serialized


def test_a_failed_chunk_stops_new_provider_work_and_raises_the_classified_failure(small_chunks, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 1)
    started: list[int] = []

    def stub(item, chunk, language, api_key, models=None):
        number = _chunk_index(CHUNK_TEXT, chunk)
        started.append(number)
        if number == 1:
            raise _schema_error()
        return analyzer.ChunkFacts([], {"model_name": PRIMARY, "attempts": 1})

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    with pytest.raises(ValidationError):  # not an ExceptionGroup: the worker classifies by type
        asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))
    assert started == [0, 1]


def test_failure_under_concurrency_raises_the_earliest_chunks_failure(small_chunks, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 3)

    def stub(item, chunk, language, api_key, models=None):
        number = _chunk_index(CHUNK_TEXT, chunk)
        if number == 0:
            time.sleep(0.1)
            raise requests.exceptions.ReadTimeout("chunk 0")
        if number == 1:
            raise _schema_error()
        return analyzer.ChunkFacts([], {"model_name": PRIMARY, "attempts": 1})

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    with pytest.raises(requests.exceptions.ReadTimeout, match="chunk 0"):
        asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))


def test_analysis_requires_an_api_key(monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))


def test_empty_pack_yields_no_facts_and_default_model(small_chunks) -> None:
    result = asyncio.run(analyzer.analyze_pack_items([], "en"))
    assert list(result) == [] and result.diagnostics["chunk_count"] == 0
    assert result.diagnostics["model_name"] == PRIMARY


# --- D1-02 bench tool (offline: golden checker, records, report) ---------------


def _bench():
    from scripts import bench_pursuit_models

    return bench_pursuit_models


def _golden_verified(monkeypatch, transform=lambda facts: facts):
    from test_p0_real_rfp_extraction import FIXTURE, _golden_facts

    text = FIXTURE.read_text(encoding="utf-8")
    facts = transform([fact.model_copy(deep=True) for fact in _golden_facts(text)])
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test")
    monkeypatch.setattr(analyzer, "_extract_chunk_sync", lambda *_: list(facts))
    pack = [SealedTextInput(uuid4(), "b4a", text, 8, True)]
    return text, asyncio.run(analyzer.analyze_pack_items(pack, "en"))


def test_bench_golden_checker_scores_the_p0_golden_facts_19_of_19(monkeypatch) -> None:
    _, verified = _golden_verified(monkeypatch)
    assert _bench().golden_coverage(list(verified)) == (19, [])


def test_bench_golden_checker_detects_missing_and_downgraded_obligations(monkeypatch) -> None:
    def degrade(facts):
        kept = [fact for fact in facts if "hourly rate" not in fact.original_quote.casefold()]
        position = next(fact for fact in kept if fact.position)
        for criterion in position.position.qualification_criteria:
            if "video" in criterion.normalized_text.casefold():
                criterion.distinction = "MANDATORY"  # preferred wording must not become mandatory
        return kept

    _, verified = _golden_verified(monkeypatch, degrade)
    covered, missing = _bench().golden_coverage(list(verified))
    assert covered == 17
    assert set(missing) == {"Hourly rate as customer-provided input", "Video capability preferred, not mandatory"}


def test_bench_run_records_are_count_only_and_disable_fallbacks(monkeypatch) -> None:
    bench = _bench()
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    text, _ = _golden_verified(monkeypatch)
    item = bench.BenchInput("b4a", "fixture", "fixture:x", text, 8, True)
    record = asyncio.run(bench.run_once("bench-model", item, 1))
    assert record["status"] == "SUCCESS" and record["golden_covered"] == 19
    assert analyzer.MODEL_NAME == "bench-model" and analyzer.FALLBACK_MODEL_NAMES == ()
    serialized = json.dumps(record)
    assert "Communications Consultant" not in serialized and "Bachelor" not in serialized


def test_bench_failures_are_classified_without_recording_messages(monkeypatch) -> None:
    bench = _bench()
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test")
    item = bench.BenchInput("reoi_1", "notice", "world_bank:X", "PRIVATE-NOTICE-TEXT " * 5, None, False)
    cases = {
        "SCHEMA_OUTPUT_FAILURE": _schema_error(),
        "TIMEOUT": requests.exceptions.ReadTimeout("PRIVATE-MESSAGE"),
        "EMPTY_RESPONSE": RuntimeError(analyzer.EMPTY_RESPONSE_MESSAGE),
    }
    for expected, error in cases.items():
        def failing(*_args, _error=error):
            raise _error

        monkeypatch.setattr(analyzer, "_extract_chunk_sync", failing)
        record = asyncio.run(bench.run_once("bench-model", item, 1))
        assert record["status"] == "FAILURE" and record["failure_class"] == expected
        assert "PRIVATE" not in json.dumps(record)


def test_bench_report_renders_selection_rule_notes_and_reference_label() -> None:
    bench = _bench()

    def record(model, name, run, status="SUCCESS", latency=40.0, **extra):
        base = {"model": model, "input": name, "run": run, "status": status, "failure_class": None,
                "latency_s": latency, "retry_count": 0, "verified_requirements": 15, "verified_positions": 1,
                "thinking_tokens": 900, "output_tokens": 5000}
        if status != "SUCCESS":
            base.update(failure_class="TIMEOUT")
        base.update(extra)  # an explicit failure_class overrides the default
        return base

    models = ["fast-model", bench.REFERENCE_MODEL]
    records = [
        record("fast-model", "b4a", 1, golden_covered=19), record("fast-model", "b4a", 2, golden_covered=19),
        record("fast-model", "b4a", 3, status="FAILURE", latency=180.0),
        record(bench.REFERENCE_MODEL, "b4a", 1, latency=60.0, golden_covered=19),
        record(bench.REFERENCE_MODEL, "b4a", 2, status="FAILURE", latency=1.8, failure_class="PROVIDER_HTTP_402"),
    ]
    inputs = [{"name": "b4a", "description": "fixture", "source_ref": "fixture:x", "characters": 5256,
               "page_markers": 8, "chunks": 1}]
    payload = {
        "meta": {"generated_at": "2026-09-29 00:00 UTC", "models": models, "runs_per_model_input": 3,
                 "max_output_tokens": 32768, "request_timeout_seconds": 180, "chunk_concurrency": 3,
                 "sdk_version": "0.3.0"},
        "summary": bench.summarize(records, models, inputs, 3), "records": records,
    }
    report = bench.render_markdown(payload)
    assert "fast-model" in report and f"{bench.REFERENCE_MODEL} (reference)" in report
    assert "| fast-model | 2/3 |" in report and "fail" in report  # 2/3 misses the 8/9 rule
    assert "Fallback ever needed among candidate models: yes (1 run(s)" in report
    reference = payload["summary"]["per_model"][bench.REFERENCE_MODEL]
    assert reference["reference_only"] is True
    # A billing/provider error is not a retry-exhausted failure: production would not fall back on it.
    assert reference["runs_where_fallback_would_be_needed"] == 0 and reference["provider_error_runs"] == 1
    assert "no fallback path" in report


# --- time budgets and provider error classes ------------------------------------

from google.genai import errors as genai_errors  # noqa: E402

PROVIDER_DETAIL = "PRIVATE-PROVIDER-DETAIL"


def _api_error(code: int) -> genai_errors.APIError:
    response = requests.Response()
    response.status_code = code
    response.reason = "provider"
    response._content = json.dumps(
        {"error": {"code": code, "message": PROVIDER_DETAIL, "status": "PROVIDER_STATUS"}}
    ).encode()
    with pytest.raises(genai_errors.APIError) as caught:
        genai_errors.APIError.raise_for_response(response)
    return caught.value


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.jitter_ranges: list[tuple[float, float]] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def jitter(self, low: float, high: float) -> float:
        self.jitter_ranges.append((low, high))
        return 5.0

    def spend(self, seconds: float, outcome):
        """A scripted provider attempt that takes ``seconds`` and then fails or answers."""
        def attempt():
            self.now += seconds
            return outcome
        return attempt


@pytest.fixture
def clock(client, monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(analyzer, "_monotonic", lambda: fake.now)
    monkeypatch.setattr(analyzer, "_sleep", fake.sleep)
    monkeypatch.setattr(analyzer, "_jitter", fake.jitter)
    monkeypatch.setattr(analyzer, "REQUEST_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(analyzer, "CHUNK_BUDGET_SECONDS", 240)
    return fake


def _timeout(clock: FakeClock, seconds: float = 90):
    return clock.spend(seconds, requests.exceptions.ReadTimeout("timed out"))


def test_chunk_budget_stops_new_attempts_and_raises_the_last_error(clock, client) -> None:
    client.script = [_timeout(clock) for _ in range(4)]
    with pytest.raises(requests.exceptions.ReadTimeout):
        _extract()
    # 0-90 and 90-180 fit; a third attempt would end at 270 > 240, so it never starts.
    assert [call["at"] for call in client.calls] == [0, 90]
    assert clock.now == 180


@pytest.mark.parametrize("budget", [60, 90, 100, 180, 240, 400, 1000])
def test_no_attempt_after_the_first_ever_starts_past_the_budget(clock, client, monkeypatch, budget) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_BUDGET_SECONDS", budget)
    client.script = [_timeout(clock) for _ in range(10)]
    with pytest.raises(requests.exceptions.ReadTimeout):
        _extract()
    starts = [call["at"] for call in client.calls]
    assert starts[0] == 0  # the first attempt always runs
    assert all(start + analyzer.REQUEST_TIMEOUT_SECONDS <= budget for start in starts[1:])
    assert len(starts) <= 1 + len(analyzer.FALLBACK_MODEL_NAMES) + 1  # the plan is never exceeded


def test_backoff_that_would_cross_the_budget_is_not_slept(clock, client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CHUNK_BUDGET_SECONDS", 100)
    monkeypatch.setattr(analyzer, "_jitter", lambda low, high: 8.0)
    client.script = [clock.spend(0, _api_error(503)), clock.spend(0, _api_error(503)), _payload(_fact())]
    with pytest.raises(genai_errors.ServerError):
        _extract()
    # 0 + 8 + 90 <= 100 so one backoff happens; then 8 + 8 + 90 > 100 so the chunk gives up.
    assert clock.sleeps == [8.0] and len(client.calls) == 2


@pytest.mark.parametrize("status", [429, 503, 504])
def test_transient_provider_errors_are_retried_once_after_a_jittered_backoff(clock, client, status) -> None:
    client.script = [_api_error(status), _payload(_fact())]
    facts = _extract()
    assert _models_called() == [PRIMARY, PRIMARY]
    assert clock.jitter_ranges == [(2.0, 8.0)] and clock.sleeps == [5.0]
    assert facts.meta["failure_classes"] == [f"{'ClientError' if status == 429 else 'ServerError'}:{status}"]


def test_transient_provider_errors_exhaust_into_the_fallback_chain(clock, client) -> None:
    client.script = [_api_error(503), _api_error(503), _payload(_fact())]
    facts = _extract()
    assert _models_called() == [PRIMARY, PRIMARY, FALLBACKS[0]]
    assert facts.meta["model_name"] == FALLBACKS[0] and len(clock.sleeps) == 2


@pytest.mark.parametrize("status", [400, 404, 500])
def test_other_provider_errors_are_not_retried(clock, client, status) -> None:
    client.script = [_api_error(status), _payload(_fact())]
    with pytest.raises(genai_errors.APIError):
        _extract()
    assert len(client.calls) == 1 and clock.sleeps == []


@pytest.mark.parametrize("status", [401, 402, 403])
def test_account_errors_fail_immediately_with_the_distinct_classified_failure(clock, client, caplog, status) -> None:
    client.script = [_api_error(status), _payload(_fact())]
    with caplog.at_level("WARNING", logger=analyzer.logger.name):
        with pytest.raises(analyzer.ProviderAccountError) as caught:
            _extract()
    error = caught.value
    assert error.code == "PROVIDER_ACCOUNT" and error.status_code == status
    assert len(client.calls) == 1 and clock.sleeps == []
    assert PROVIDER_DETAIL not in str(error) and error.__cause__ is None and error.__suppress_context__
    assert f"status={status}" in caplog.text
    assert PROVIDER_DETAIL not in caplog.text and "test-key" not in caplog.text


def test_account_errors_are_not_retryable_and_are_not_transient() -> None:
    assert not analyzer._is_retryable(analyzer.ProviderAccountError(402))
    assert not analyzer._is_retryable(analyzer.RunBudgetExceeded("budget"))
    assert analyzer.ACCOUNT_PROVIDER_STATUS_CODES.isdisjoint(analyzer.TRANSIENT_PROVIDER_STATUS_CODES)


def test_run_budget_stops_starting_chunks_and_fails_with_the_classified_failure(small_chunks, monkeypatch) -> None:
    fake = FakeClock()
    monkeypatch.setattr(analyzer, "_monotonic", lambda: fake.now)
    monkeypatch.setattr(analyzer, "CHUNK_CONCURRENCY", 1)
    monkeypatch.setattr(analyzer, "RUN_BUDGET_SECONDS", 250)
    started: list[int] = []

    def stub(item, chunk, language, api_key, models=None):
        started.append(_chunk_index(CHUNK_TEXT, chunk))
        fake.now += 200  # each chunk takes 200 s of the 250 s run budget
        return analyzer.ChunkFacts([], {"model_name": PRIMARY, "attempts": 1})

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    with pytest.raises(analyzer.RunBudgetExceeded) as caught:
        asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))
    assert caught.value.code == "RUN_BUDGET_EXCEEDED"
    assert started == [0, 1]  # chunk 2 would start at 400 s > 250 s and never does


def test_run_budget_lets_started_chunks_finish_and_a_fast_run_is_unaffected(small_chunks, monkeypatch) -> None:
    fake = FakeClock()
    monkeypatch.setattr(analyzer, "_monotonic", lambda: fake.now)
    monkeypatch.setattr(analyzer, "RUN_BUDGET_SECONDS", 480)

    def stub(item, chunk, language, api_key, models=None):
        fake.now += 1
        return analyzer.ChunkFacts([_fact(_quote_in(chunk), "Item")], {"model_name": PRIMARY, "attempts": 1})

    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    result = asyncio.run(analyzer.analyze_pack_items(_pack(), "en"))
    assert result.diagnostics["chunk_count"] == len(analyzer._chunks(CHUNK_TEXT))
    assert result.diagnostics["run_budget_seconds"] == 480 and result.diagnostics["chunk_budget_seconds"] == 240


def test_worker_classification_keeps_provider_detail_away_from_customers() -> None:
    from app.services import pursuit_analysis as service

    reason, code = service.classify_analysis_failure(analyzer.ProviderAccountError(402))
    assert reason == "The analysis provider is temporarily unavailable. Plasma has been notified."
    assert code == "PROVIDER_ACCOUNT" and "402" not in reason
    reason, code = service.classify_analysis_failure(analyzer.RunBudgetExceeded("budget spent"))
    assert (reason, code) == ("budget spent", "RUN_BUDGET_EXCEEDED")
    # Everything else is unchanged: bounded exception text and no failure code.
    assert service.classify_analysis_failure(RuntimeError("x" * 2000)) == ("x" * 1000, None)


# --- D1 re-run bench additions: recall, plan, stop rule -------------------------


def test_span_overlap_uses_the_shorter_span_and_a_50_percent_threshold() -> None:
    bench = _bench()
    assert bench.span_overlap_ratio((0, 100), (40, 60)) == 1.0  # the short span is fully inside
    assert bench.span_overlap_ratio((0, 100), (50, 150)) == 0.5
    assert bench.spans_match((0, 100), (50, 150)) is True  # exactly 50% qualifies
    assert bench.spans_match((0, 100), (51, 151)) is False
    assert bench.spans_match((0, 10), (10, 20)) is False and bench.span_overlap_ratio((5, 5), (0, 9)) == 0.0


def test_distinct_spans_merges_items_that_match_each_other() -> None:
    bench = _bench()
    assert bench.distinct_spans([(0, 100), (10, 90), (200, 300), (250, 350), (500, 510)]) == [(0, 100), (200, 300), (500, 510)]


def test_long_rfp_recall_against_the_reference_union_and_model_only_items() -> None:
    bench = _bench()
    ref = bench.REFERENCE_MODEL
    spans = {
        # Two reference runs: their union has four distinct items.
        ref: {"1": [(0, 100), (200, 300), (400, 500)], "2": [(0, 100), (600, 700)]},
        "flash-a": {
            "1": [(0, 90), (210, 290), (800, 900)],       # matches items 1, 2; one model-only item
            "2": [(0, 100), (400, 500), (600, 690)],       # matches items 1, 3, 4
        },
        "flash-b": {"1": []},
    }
    summary = bench.recall_summary(spans)
    assert summary["reference_items"] == 4 and summary["reference_runs"] == 2
    assert summary["reference_items_per_run"] == [3, 2]
    flash_a = summary["models"]["flash-a"]
    assert flash_a["recall_per_run"] == [0.5, 0.75] and flash_a["recall_median"] == 0.625
    assert flash_a["recall_union"] == 1.0
    assert flash_a["model_only_per_run"] == [1, 0] and flash_a["model_only_union"] == 1
    assert summary["models"]["flash-b"]["recall_median"] == 0.0  # a successful run with no items scores zero
    assert summary["models"]["flash-b"]["model_only_union"] == 0
    assert bench.recall_summary({"flash-a": {"1": [(0, 1)]}}) is None  # no reference run at all


def test_unmatched_reference_export_is_private_and_lists_only_misses(tmp_path) -> None:
    bench = _bench()
    phrase = "SECOND requirement missed by flash."
    text = "AAAA first requirement text. " + "x" * 50 + " " + phrase + " " + "y" * 40
    first = (0, 27)
    second = (text.index("SECOND"), text.index("SECOND") + len(phrase))
    spans = {bench.REFERENCE_MODEL: {"1": [first, second]}, "flash-a": {"1": [first]}}
    path = tmp_path / "private" / "unmatched.md"
    assert bench.export_unmatched_reference_items(path, text, spans) == 1
    exported = path.read_text(encoding="utf-8")
    assert phrase in exported and "AAAA first requirement" not in exported
    assert "matched in 0/1 run(s)" in exported and "PRIVATE" in exported.splitlines()[0]


def test_bench_output_locations_keep_private_material_out_of_docs() -> None:
    bench = _bench()
    assert "docs" not in bench.PRIVATE_DIR.parts and ".private-storage" in bench.PRIVATE_DIR.parts


def test_preset_and_uniform_plans() -> None:
    bench = _bench()
    args = bench.parse_args(["--preset", "r2"])
    plan = bench.build_plan(args)
    assert args.tag == "r2"
    assert plan["gemini-3.7-flash"] == {"b4a_full": 5, "reoi_1": 5, "reoi_2": 5, "long_rfp": 3}
    assert plan["gemini-3.8-flash"] == plan["gemini-3.7-flash"]
    assert plan[bench.REFERENCE_MODEL] == {"long_rfp": 3}
    uniform = bench.build_plan(bench.parse_args(["--runs", "2", "--models", "m1", "--inputs", "b4a_full", "long_rfp"]))
    assert uniform == {"m1": {"b4a_full": 2, "long_rfp": 2}}


def test_bench_classifies_account_budget_and_transient_provider_failures(monkeypatch) -> None:
    bench = _bench()
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)  # run_once switches the analyzer model; restore afterwards
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test")
    item = bench.BenchInput("reoi_1", "notice", "world_bank:X", "text " * 10, None, False)
    cases = {
        "PROVIDER_ACCOUNT": analyzer.ProviderAccountError(402),
        "RUN_BUDGET_EXCEEDED": analyzer.RunBudgetExceeded("spent"),
        "PROVIDER_HTTP_503": _api_error(503),
    }
    for expected, error in cases.items():
        def failing(*_args, _error=error):
            raise _error

        monkeypatch.setattr(analyzer, "_extract_chunk_sync", failing)
        record = asyncio.run(bench.run_once("bench-model", item, 1))
        assert record["failure_class"] == expected
        assert PROVIDER_DETAIL not in json.dumps(record)
    assert bench.classify_failure(analyzer.ProviderAccountError(401)) == analyzer.ProviderAccountError.code
    assert "PROVIDER_HTTP_503" in bench.RETRY_EXHAUSTED_CLASSES and "PROVIDER_ACCOUNT" not in bench.RETRY_EXHAUSTED_CLASSES


def test_bench_run_once_returns_requirement_spans_for_recall(monkeypatch) -> None:
    bench = _bench()
    monkeypatch.setattr(analyzer, "MODEL_NAME", PRIMARY)
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", FALLBACKS)
    text, _ = _golden_verified(monkeypatch)
    item = bench.BenchInput("long_rfp", "long", "giz:x", text, 8, True)
    spans: list = []
    record = asyncio.run(bench.run_once("bench-model", item, 1, spans))
    assert record["status"] == "SUCCESS"
    assert len(spans) == record["verified_requirements"] and all(0 <= s < e <= len(text) for s, e in spans)


# --- D1 v3: deterministic verbatim source windows ------------------------------

LIST_SOURCE = (
    "5.\nBIDDER'S PROPOSAL\n\n"
    "Required Materials. The Bidder must include the following information in the Proposal:\n\n"
    "a) Resume or corporate profile clearly reflecting qualifications and experiences.\n"
    "b) Samples of communication and media materials.\n"
    "c) List of at least three (3) professional references.\n\n"
    "Format. The Proposal shall not exceed five pages."
)
LIST_QUOTE = "b) Samples of communication and media materials."


def _window(text: str, quote: str) -> str:
    start = text.index(quote)
    bounds = analyzer._source_window(text, start, start + len(quote))
    assert bounds is not None
    return text[bounds[0]:bounds[1]]


def test_source_window_captures_a_lettered_list_preamble_ending_with_a_colon() -> None:
    window = _window(LIST_SOURCE, LIST_QUOTE)
    assert window in LIST_SOURCE and LIST_QUOTE in window
    assert window.startswith("Required Materials. The Bidder must include the following information in the Proposal:")
    assert window.endswith("c) List of at least three (3) professional references.")  # end of the quote's paragraph
    assert "Format." not in window  # the next paragraph is not included


def test_source_window_uses_a_section_heading_when_no_preamble_precedes() -> None:
    text = "Intro text.\n\n3.2 Eligibility\nThe consultant shall hold a licence.\nIt must be current.\n\nNext part."
    assert _window(text, "It must be current.") == "3.2 Eligibility\nThe consultant shall hold a licence.\nIt must be current."
    caps = "Preface.\n\nQUALIFICATIONS\n\nMinimum of 5 years experience.\n\nOther."
    assert _window(caps, "Minimum of 5 years experience.").startswith("QUALIFICATIONS")


def test_source_window_falls_back_to_the_paragraph_and_ignores_page_decoration() -> None:
    text = "Earlier paragraph.\n\nThe bidder shall be registered. It shall also be solvent.\n\nLater."
    assert _window(text, "It shall also be solvent.") == "The bidder shall be registered. It shall also be solvent."
    # A page marker, a running header with digits and a bare page number are not headings.
    decorated = "Heading line:\nfirst item\n\n[[PAGE 7]]\n1-25-2012 FINAL POSTED\n7\n\nsecond item continues here."
    window = _window(decorated, "second item continues here.")
    assert window.startswith("Heading line:")


def test_numbered_list_sentences_are_not_headings() -> None:
    assert not analyzer._is_context_anchor("2. The consultant shall mobilize within 14 days.")
    assert analyzer._is_context_anchor("2. Scope of Services")
    assert analyzer._is_context_anchor("5.")
    assert not analyzer._is_context_anchor("7")
    assert not analyzer._is_context_anchor("[[PAGE 7]]")
    assert analyzer._is_context_anchor("ТРЕБОВАНИЯ К КВАЛИФИКАЦИИ")  # Unicode upper case
    assert not analyzer._is_context_anchor("Требования к квалификации")


def test_source_window_cap_trims_only_at_whitespace_and_keeps_the_quote(monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CONTEXT_WINDOW_MAX_CHARACTERS", 120)
    items = "\n".join(f"{letter}) Requirement item {letter} with some words." for letter in "abcdefghij")
    text = "Required documents:\n" + items + "\n\nEnd."
    quote = "f) Requirement item f with some words."
    window = _window(text, quote)
    start = text.index(window)
    assert quote in window and len(window) <= 120
    assert start == 0 or text[start - 1].isspace()  # head cut at whitespace
    end = start + len(window)
    assert end == len(text) or text[end].isspace()  # tail cut at whitespace
    assert window == window.strip()


def test_a_quote_longer_than_the_cap_gets_no_window(monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "CONTEXT_WINDOW_MAX_CHARACTERS", 20)
    text = "Heading:\nThis quote is definitely longer than twenty characters."
    start = text.index("This")
    assert analyzer._source_window(text, start, len(text)) is None


def _analyze_one(monkeypatch, text: str, facts: list[ExtractedFact]):
    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "_extract_chunk_sync", lambda *_: list(facts))
    return asyncio.run(analyzer.analyze_pack_items([SealedTextInput(uuid4(), "sealed.txt", text)], "en"))


def test_bad_context_with_a_good_quote_is_kept_with_an_exact_source_window(monkeypatch) -> None:
    invented = "The consultant must submit samples (paraphrased by the model)."
    result = _analyze_one(monkeypatch, LIST_SOURCE, [_fact(LIST_QUOTE, "Samples", source_context=invented)])
    assert len(result) == 1
    kept = result[0]
    assert kept.context_origin == "SOURCE_WINDOW"
    assert kept.fact.source_context != invented and kept.fact.source_context in LIST_SOURCE
    assert LIST_QUOTE in kept.fact.source_context
    assert kept.fact.original_quote == LIST_QUOTE  # the quote itself is never altered
    assert result.diagnostics["provenance_rejected_count"] == 0
    assert result.diagnostics["context_source_window"] == 1


def test_good_context_is_unchanged_and_absent_context_stays_absent(monkeypatch) -> None:
    preamble = "Required Materials. The Bidder must include the following information in the Proposal:"
    quote_c = "c) List of at least three (3) professional references."
    result = _analyze_one(monkeypatch, LIST_SOURCE, [
        _fact(LIST_QUOTE, "Samples", source_context=preamble),
        _fact(quote_c, "References"),
    ])
    assert [(v.context_origin, v.fact.source_context) for v in result] == [("MODEL_VERBATIM", preamble), ("NONE", None)]
    d = result.diagnostics
    assert (d["context_model_verbatim"], d["context_source_window"], d["context_none"]) == (1, 0, 1)


def test_a_bad_quote_is_still_rejected_and_counts_as_the_only_provenance_rejection(monkeypatch) -> None:
    result = _analyze_one(monkeypatch, LIST_SOURCE, [
        _fact("d) A quote that is not in the document.", "Invented", source_context="Required Materials."),
        _fact(LIST_QUOTE, "Samples", source_context="not verbatim context"),
    ])
    assert [v.fact.original_quote for v in result] == [LIST_QUOTE]
    d = result.diagnostics
    assert d["provenance_rejected_count"] == 1  # quote failures only
    assert d["context_source_window"] == 1 and d["context_model_verbatim"] == 0 and d["context_none"] == 0
    assert d["verified_requirement_count"] == d["context_source_window"] + d["context_model_verbatim"] + d["context_none"]


def test_pipeline_and_prompt_versions_are_bumped_and_the_schema_is_not() -> None:
    # D2-01 bumps both again for the submission-instruction/informational instruction;
    # D2 analysis quality bumps both: two SHORT passes, and one restatement instruction.
    assert analyzer.PIPELINE_VERSION == "pursuit_analysis_pipeline_d2_v2"
    assert analyzer.PROMPT_VERSION == "pursuit_analysis_d2_v2"
    assert analyzer.SCHEMA_VERSION == "pursuit_analysis_output_p0_v2"
    prompt = " ".join(analyzer.SYSTEM_PROMPT.split())
    # D1 arm B adds exactly these two instructions; the trust rules around them are unchanged.
    assert "source_context must be copied character-for-character from the document or left null." in prompt
    assert "Treat each lettered or numbered item of a qualifications or required-materials list as a separate fact." in prompt
    assert "Return only facts directly supported by an exact verbatim quote." in prompt
    assert ("When the notice restates a criterion already stated elsewhere (for example a summary or bulleted list "
            "repeating numbered criteria), extract it once, quoting the most complete statement; do not extract the "
            "restatement as a separate requirement.") in prompt
    assert analyzer.PROMPT_SHA256 == __import__("hashlib").sha256(analyzer.SYSTEM_PROMPT.encode()).hexdigest()


# --- per-model timeouts --------------------------------------------------------


def test_model_timeout_overrides_parse_and_apply(clock, client, monkeypatch) -> None:
    assert analyzer._model_timeouts("gemini-3.1-pro-preview=150, bad, x=, y=0, z=abc,m2=45") == {
        "gemini-3.1-pro-preview": 150, "m2": 45,
    }
    monkeypatch.setattr(analyzer, "MODEL_TIMEOUT_SECONDS", {PRIMARY: 150})
    client.script = [_payload(_fact())]
    _extract()
    assert client.constructed[-1]["http_options"] == {"timeout": 150}


def test_a_slow_primary_retry_that_cannot_fit_is_skipped_for_a_faster_fallback(clock, client, monkeypatch) -> None:
    monkeypatch.setattr(analyzer, "MODEL_TIMEOUT_SECONDS", {PRIMARY: 150})
    client.script = [_timeout(clock, 150), _payload(_fact())]
    facts = _extract()
    # 150 + 150 > 240, so the primary retry is skipped; 150 + 90 <= 240, so the fallback runs.
    assert _models_called() == [PRIMARY, FALLBACKS[0]]
    assert facts.meta["model_name"] == FALLBACKS[0]
    assert [call["at"] for call in client.calls] == [0, 150]


# --- D1 v3: worker concurrency, golden checker, selection rule --------------------


def test_pursuit_worker_concurrency_is_env_configurable_with_default_two() -> None:
    compose = (BACKEND_DIR.parent / "docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  worker_pursuit_analysis:", 1)[1].split("\n  # ----", 1)[0]
    assert '"-Q", "pursuit_analysis"' in service
    assert '"--concurrency=${PURSUIT_ANALYSIS_WORKER_CONCURRENCY:-2}"' in service
    # Concurrent runs are safe because the claim is a row lock plus an owned lease
    # (proved against a disposable database in test_w4_pursuit_analysis.py).
    service_source = (BACKEND_DIR / "app" / "services" / "pursuit_analysis.py").read_text(encoding="utf-8")
    claim = service_source.split("async def process_analysis_run", 1)[1].split("run.status = \"RUNNING\"", 1)[0]
    assert ".with_for_update()" in claim and "run.lease_owner != worker_id" in claim


def test_golden_checker_ignores_source_context_so_windows_cannot_inflate_coverage(monkeypatch) -> None:
    bench = _bench()
    window = "a) Resume or corporate profile.\nb) Samples of communication and media materials.\nh) insurance acknowledgement"
    fact = _fact("b) Samples of communication and media materials.", "Samples", source_context=window)
    verified = [analyzer.VerifiedFact(uuid4(), fact, 0, 10, None, None, "SOURCE_WINDOW")]
    covered, missing = bench.golden_coverage(verified)
    assert "Work samples" not in missing
    assert "Resume/profile" in missing and "Insurance" in missing  # only present in the window


def test_selection_outcome_applies_the_d1_rule() -> None:
    bench = _bench()
    per_model = {
        "fast": {"reference_only": False, "b4a_runs": 5, "b4a_golden_19_of_19_runs": 4, "latency_p90_s": 20.0},
        "sparse": {"reference_only": False, "b4a_runs": 5, "b4a_golden_19_of_19_runs": 5, "latency_p90_s": 15.0},
        "weak": {"reference_only": False, "b4a_runs": 5, "b4a_golden_19_of_19_runs": 3, "latency_p90_s": 10.0},
        bench.REFERENCE_MODEL: {"reference_only": True, "b4a_runs": 0, "b4a_golden_19_of_19_runs": 0, "latency_p90_s": 90.0},
    }
    recall = {"models": {"fast": {"recall_median": 0.8}, "sparse": {"recall_median": 0.5}, "weak": {"recall_median": 0.9}}}
    outcome = bench.selection_outcome({"per_model": per_model, "long_rfp_recall": recall})
    assert [m for m, e in outcome.items() if e["qualifies"]] == ["fast"]
    assert outcome["sparse"]["golden_ok"] and not outcome["sparse"]["recall_ok"]
    assert not outcome["weak"]["golden_ok"] and bench.REFERENCE_MODEL not in outcome


def test_report_writes_keep_hand_written_run_notes(tmp_path) -> None:
    bench = _bench()
    report = tmp_path / "model-bench-x.md"
    report.write_text("# old generated\n\n## Run notes\n\n- a human note\n", encoding="utf-8")
    bench.write_report(report, "# new generated\n")
    assert report.read_text(encoding="utf-8") == "# new generated\n\n## Run notes\n\n- a human note\n"


# --- D1 final: exact model contexts and length-based routing ----------------------

CONTEXT_SOURCE = (
    "Section 4:\n"
    "The bidder’s  proposal shall\n"
    "include a work plan.\n\n"
    "[[PAGE 2]]\n"
    "Other text."
)


def test_a_normalized_model_context_is_persisted_as_the_exact_source_substring(monkeypatch) -> None:
    # The model wrote a straight apostrophe, single spaces and no line break.
    model_context = "Section 4: The bidder's proposal shall include a work plan."
    assert model_context not in CONTEXT_SOURCE and analyzer._normalized_contains(CONTEXT_SOURCE, model_context)
    result = _analyze_one(monkeypatch, CONTEXT_SOURCE, [
        _fact("include a work plan.", "Work plan", source_context=model_context),
    ])
    kept = result[0]
    assert kept.context_origin == "MODEL_VERBATIM"
    exact = "Section 4:\nThe bidder’s  proposal shall\ninclude a work plan."
    assert kept.fact.source_context == exact and exact in CONTEXT_SOURCE
    assert result.diagnostics["context_model_verbatim"] == 1


def test_an_exact_model_context_is_unchanged_and_the_nearest_occurrence_is_used() -> None:
    text = "Heading.\nclause A\nfiller " * 3 + "the quote here."
    near = text.index("the quote here.")
    span = analyzer._exact_span(text, "clause A", near)
    assert span == (text.rindex("clause A"), text.rindex("clause A") + len("clause A"))
    assert analyzer._exact_span(text, "clause   A", 0) == (text.index("clause A"), text.index("clause A") + 8)
    assert analyzer._exact_span(text, "not there", 0) is None
    assert analyzer._exact_span(text, " \n ", 0) is None  # empty after normalization


def test_normalization_is_computed_once_per_item(monkeypatch) -> None:
    calls = {"count": 0}
    original = analyzer._normalized_evidence

    def counting(value, *, map_offsets):
        if map_offsets and value == CONTEXT_SOURCE:
            calls["count"] += 1
        return original(value, map_offsets=map_offsets)

    monkeypatch.setattr(analyzer, "_normalized_evidence", counting)
    facts = [
        _fact("include a work plan.", f"Work plan {n}", source_context="The bidder's proposal shall include")
        for n in range(3)
    ]
    result = _analyze_one(monkeypatch, CONTEXT_SOURCE, facts)
    assert len(result) == 3 and all(v.context_origin == "MODEL_VERBATIM" for v in result)
    assert calls["count"] == 1


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analyzer, "LONG_PACK_CHARACTERS", 1_000)
    monkeypatch.setattr(analyzer, "MODEL_NAME", "short-primary")
    monkeypatch.setattr(analyzer, "FALLBACK_MODEL_NAMES", ("short-fallback", "short-last"))
    monkeypatch.setattr(analyzer, "LONG_MODEL_NAME", "long-primary")
    monkeypatch.setattr(analyzer, "LONG_FALLBACK_MODEL_NAMES", ("long-fallback",))
    monkeypatch.setattr(analyzer, "MAX_CHUNK_CHARACTERS", 5_000)
    monkeypatch.setattr(analyzer, "LONG_CHUNK_CHARACTERS", 400)


def test_routing_boundary_is_inclusive_for_the_short_route(routes) -> None:
    assert analyzer.route_for(1_000) == analyzer.Route("SHORT", ("short-primary", "short-fallback", "short-last"), 5_000)
    assert analyzer.route_for(1_001) == analyzer.Route("LONG", ("long-primary", "long-fallback"), 400)
    assert analyzer.route_for(0).name == "SHORT"


def _routed_run(monkeypatch, texts: list[str]):
    seen: list[tuple[int, tuple[str, ...]]] = []

    def stub(item, chunk, language, api_key, models=None):
        seen.append((len(chunk), models))
        return analyzer.ChunkFacts([], {"model_name": models[0], "attempts": 1})

    monkeypatch.setattr(analyzer, "_resolve_gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "_extract_chunk_sync", stub)
    pack = [SealedTextInput(uuid4(), f"part-{n}.txt", text) for n, text in enumerate(texts)]
    return asyncio.run(analyzer.analyze_pack_items(pack, "en")), seen


def test_the_route_uses_total_pack_characters_its_chain_and_its_chunk_size(routes, monkeypatch) -> None:
    # Two items of 600 characters: each is short, the pack (1,200) is long.
    result, seen = _routed_run(monkeypatch, ["x " * 300, "y " * 300])
    assert {models for _, models in seen} == {("long-primary", "long-fallback")}
    assert max(size for size, _ in seen) <= 400 and len(seen) == 4  # two 400-char chunks per item
    d = result.diagnostics
    assert (d["route"], d["pack_characters"], d["long_pack_threshold_characters"]) == ("LONG", 1_200, 1_000)
    assert d["route_models"] == ["long-primary", "long-fallback"] and d["route_chunk_characters"] == 400
    assert d["model_name"] == "long-primary" and d["fallback_chunk_count"] == 0

    assert d["pass_count"] == 1  # the LONG route runs one pass

    result, seen = _routed_run(monkeypatch, ["z " * 500])
    assert seen == [(1_000, ("short-primary", "short-fallback", "short-last"))] * analyzer.SHORT_PASSES
    assert result.diagnostics["route"] == "SHORT" and result.diagnostics["route_chunk_characters"] == 5_000
    assert result.diagnostics["pass_count"] == analyzer.SHORT_PASSES == 2


def test_fallback_chains_follow_the_route(clock, client, routes) -> None:
    long_chain = analyzer.route_for(10_000).models
    client.script = ["{bad", "{bad", _payload(_fact())]
    facts = analyzer._extract_chunk_sync(SealedTextInput(uuid4(), "s", QUOTE), QUOTE, "en", "k", long_chain)
    assert _models_called() == ["long-primary", "long-primary", "long-fallback"]
    assert facts.meta["model_name"] == "long-fallback"
    client.calls.clear()
    client.script = ["{bad"] * 4
    with pytest.raises(ValidationError):
        analyzer._extract_chunk_sync(SealedTextInput(uuid4(), "s", QUOTE), QUOTE, "en", "k", analyzer.route_for(10).models)
    assert _models_called() == ["short-primary", "short-primary", "short-fallback", "short-last"]


def test_chunk_overlap_is_1500_below_the_default_chunk_size_and_1000_at_it() -> None:
    text = "w" * 120_000
    small = analyzer._chunks(text, 30_000)
    assert [start for start, _ in small][:3] == [0, 28_500, 57_000]
    assert all(len(chunk) <= 30_000 for _, chunk in small) and small[-1][0] + len(small[-1][1]) == len(text)
    default = analyzer._chunks(text, 100_000)
    assert [start for start, _ in default] == [0, 99_000]


def test_the_queued_run_model_is_the_route_primary() -> None:
    service = (BACKEND_DIR / "app" / "services" / "pursuit_analysis.py").read_text(encoding="utf-8")
    assert "model_name=pursuit_analyzer.route_for(character_count).models[0]" in service
