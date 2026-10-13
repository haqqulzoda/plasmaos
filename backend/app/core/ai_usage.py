"""Sprint 1: per-call AI usage, collected without changing provider-call signatures.

A service opens ``collect_ai_usage()`` around provider work; each provider call reports
``record_ai_call(...)`` (model, token counts, latency, outcome). The collector is a
context variable holding a list, so calls made in ``asyncio.to_thread`` workers and in
tasks created inside the block land in the same list. Outside a collector, reporting is a
no-op. Only counts and timings are kept: never prompts, outputs or document text.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class AICall:
    model_name: str
    outcome: str  # SUCCEEDED | FAILED
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    latency_ms: int | None


_COLLECTOR: ContextVar[list[AICall] | None] = ContextVar("plasma_ai_usage", default=None)


@contextmanager
def collect_ai_usage() -> Iterator[list[AICall]]:
    calls: list[AICall] = []
    token = _COLLECTOR.set(calls)
    try:
        yield calls
    finally:
        _COLLECTOR.reset(token)


def _count(usage: object, name: str) -> int | None:
    value = getattr(usage, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_counts(response: object | None) -> tuple[int | None, int | None, int | None]:
    """(input, output, thinking) from a google-genai response's usage_metadata."""
    usage = getattr(response, "usage_metadata", None) if response is not None else None
    prompt = _count(usage, "prompt_token_count")
    output = _count(usage, "candidates_token_count")
    total = _count(usage, "total_token_count")
    thinking = _count(usage, "thoughts_token_count")
    if thinking is None and None not in (prompt, output, total):
        # google-genai 0.3.0 does not surface thoughts_token_count; the remainder is thinking.
        thinking = max(0, total - prompt - output)
    return prompt, output, thinking


def record_ai_call(model_name: str, *, started: float, response: object | None = None, succeeded: bool) -> None:
    calls = _COLLECTOR.get()
    if calls is None:
        return
    prompt, output, thinking = usage_counts(response)
    calls.append(AICall(
        model_name=str(model_name or "unknown")[:200],
        outcome="SUCCEEDED" if succeeded else "FAILED",
        input_tokens=prompt, output_tokens=output, thinking_tokens=thinking,
        latency_ms=max(0, int((time.monotonic() - started) * 1000)),
    ))
