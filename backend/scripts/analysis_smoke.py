#!/usr/bin/env python3
"""Read-only smoke check of pursuit analysis after a deploy (no provider calls, no writes).

Run inside the backend or pursuit-analysis worker container, which has the release's
environment:

    docker compose exec -T worker_pursuit_analysis python scripts/analysis_smoke.py [--hours 24] [--json]

Prints the resolved routing configuration (models, fallbacks, chunk sizes, timeouts,
budgets), whether an API key is configured (never its value), and count-only run
health for the last --hours: runs by status, failure stages, pipeline versions, runs
queued too long, and RUNNING runs whose lease has expired.

Exit 1 on: no API key; a budget that cannot fit one request; RUNNING runs with an
expired lease; QUEUED runs older than --max-queued-minutes. Failed runs are reported,
not failed on, because a provider outage is not a deploy defect.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select

from app.core.agents import pursuit_analyzer as analyzer
from app.core.agents.requirement_extractor import _resolve_gemini_api_key
from app.db.session import AsyncSessionLocal, engine
from app.models.pursuit_analysis import AnalysisRun


def configuration() -> tuple[dict, list[str]]:
    short = analyzer.route_for(0)
    long = analyzer.route_for(analyzer.LONG_PACK_CHARACTERS + 1)
    config = {
        "prompt_version": analyzer.PROMPT_VERSION,
        "pipeline_version": analyzer.PIPELINE_VERSION,
        "long_pack_threshold_chars": analyzer.LONG_PACK_CHARACTERS,
        "routes": {
            route.name: {
                "models": list(route.models),
                "chunk_chars": route.chunk_characters,
                "timeouts_s": {model: analyzer._timeout_for(model) for model in route.models},
            }
            for route in (short, long)
        },
        "max_output_tokens": analyzer.MAX_OUTPUT_TOKENS,
        "chunk_budget_s": analyzer.CHUNK_BUDGET_SECONDS,
        "run_budget_s": analyzer.RUN_BUDGET_SECONDS,
        "chunk_concurrency": analyzer.CHUNK_CONCURRENCY,
        "worker_concurrency": os.getenv("PURSUIT_ANALYSIS_WORKER_CONCURRENCY", "(compose default)"),
        "api_key_configured": bool(_resolve_gemini_api_key()),
    }
    problems = []
    if not config["api_key_configured"]:
        problems.append("no Gemini API key is configured")
    for name, route in config["routes"].items():
        primary = route["models"][0]
        if route["timeouts_s"][primary] > analyzer.CHUNK_BUDGET_SECONDS:
            problems.append(f"{name} primary {primary} timeout exceeds the chunk budget")
    if analyzer.RUN_BUDGET_SECONDS < analyzer.CHUNK_BUDGET_SECONDS:
        problems.append("run budget is smaller than one chunk budget")
    return config, problems


async def run_health(hours: int, max_queued_minutes: int) -> tuple[dict, list[str]]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    try:
        async with AsyncSessionLocal() as db:
            by_status = dict((await db.execute(
                select(AnalysisRun.status, func.count()).where(AnalysisRun.created_at >= since).group_by(AnalysisRun.status)
            )).all())
            failure_stages = dict((await db.execute(
                select(AnalysisRun.failure_stage, func.count())
                .where(AnalysisRun.created_at >= since, AnalysisRun.status == "FAILED")
                .group_by(AnalysisRun.failure_stage)
            )).all())
            pipelines = dict((await db.execute(
                select(AnalysisRun.pipeline_version, func.count())
                .where(AnalysisRun.created_at >= since).group_by(AnalysisRun.pipeline_version)
            )).all())
            stale_running = await db.scalar(
                select(func.count()).where(AnalysisRun.status == "RUNNING", AnalysisRun.lease_until < now)
            )
            old_queued = await db.scalar(select(func.count()).where(
                AnalysisRun.status == "QUEUED", AnalysisRun.created_at < now - timedelta(minutes=max_queued_minutes)
            ))
    finally:
        await engine.dispose()
    health = {
        "window_hours": hours,
        "runs_by_status": by_status,
        "failed_by_stage": {str(stage): count for stage, count in failure_stages.items()},
        "runs_by_pipeline_version": pipelines,
        "running_with_expired_lease": stale_running or 0,
        f"queued_longer_than_{max_queued_minutes}_min": old_queued or 0,
    }
    problems = []
    if stale_running:
        problems.append(f"{stale_running} RUNNING run(s) have an expired lease (is the pursuit_analysis worker alive?)")
    if old_queued:
        problems.append(f"{old_queued} QUEUED run(s) older than {max_queued_minutes} min (is Beat dispatching?)")
    return health, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, default=24, help="Run-health window (default 24).")
    parser.add_argument("--max-queued-minutes", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config, problems = configuration()
    health, run_problems = asyncio.run(run_health(args.hours, args.max_queued_minutes))
    problems += run_problems
    report = {"configuration": config, "run_health": health, "problems": problems}
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"pipeline {config['pipeline_version']}  prompt {config['prompt_version']}")
        print(f"API key configured: {'yes' if config['api_key_configured'] else 'NO'}")
        for name, route in config["routes"].items():
            chain = ", ".join(f"{model} ({route['timeouts_s'][model]} s)" for model in route["models"])
            print(f"route {name}: {chain}; chunk {route['chunk_chars']} chars")
        print(
            f"long-pack threshold {config['long_pack_threshold_chars']} chars; budgets chunk {config['chunk_budget_s']} s,"
            f" run {config['run_budget_s']} s; chunk concurrency {config['chunk_concurrency']};"
            f" worker concurrency {config['worker_concurrency']}; max output tokens {config['max_output_tokens']}"
        )
        print(f"last {args.hours} h runs by status: {health['runs_by_status'] or '{}'}")
        print(f"failed by stage: {health['failed_by_stage'] or '{}'}")
        print(f"by pipeline version: {health['runs_by_pipeline_version'] or '{}'}")
        print(f"RUNNING with expired lease: {health['running_with_expired_lease']}")
        for problem in problems:
            print(f"FAIL: {problem}")
        print("analysis smoke: " + ("FAILED" if problems else "OK"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
