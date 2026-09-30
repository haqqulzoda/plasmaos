#!/usr/bin/env python3
"""Pursuit analysis smoke check after a deploy.

Default (read-only; no provider calls, no writes). Run inside the backend or
pursuit-analysis worker container, which has the release's environment:

    docker compose exec -T worker_pursuit_analysis python scripts/analysis_smoke.py [--hours 24] [--json]

Prints the resolved routing configuration (models, fallbacks, chunk sizes, timeouts,
budgets), whether an API key is configured (never its value), and count-only run
health for the last --hours: runs by status, failure stages, pipeline versions, runs
queued too long, and RUNNING runs whose lease has expired. Exit 1 on: no API key; a
budget that cannot fit one request; RUNNING runs with an expired lease; QUEUED runs
older than --max-queued-minutes. Failed runs are reported, not failed on, because a
provider outage is not a deploy defect.

--live (end to end through the public API; one real provider call per run). Needs no
database access; run it from anywhere that reaches the API:

    ANALYSIS_SMOKE_TOKEN=<bearer token of the smoke user> python scripts/analysis_smoke.py --live \\
        --api-base https://<API_DOMAIN>/api/v1 --org-id <uuid> --org-name "<exact test org name>" \\
        [--tender-id <uuid>] [--runs 1] [--max-latency 60] [--min-requirements 5]

It creates (or reuses) one SOURCE pursuit for an open World Bank REOI in a dedicated test
organization, seals that tender's OFFICIAL_NOTICE and starts an analysis, then waits for
COMPLETED + READY_FOR_REVIEW. Guard: it refuses to run unless the token's user belongs to
exactly one organization, that organization's display name equals --org-name, and its only
active member is that user, so it can never write into a customer organization. The token is
read from ANALYSIS_SMOKE_TOKEN only (never argv, never printed). Output is counts and ids.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REOI_QUERY = "Request for Expression of Interest"


# ---- read-only mode (inside the stack) -------------------------------------------------------


def configuration() -> tuple[dict, list[str]]:
    from app.core.agents import pursuit_analyzer as analyzer
    from app.core.agents.requirement_extractor import _resolve_gemini_api_key

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
    from sqlalchemy import func, select

    from app.db.session import AsyncSessionLocal, engine
    import app.models.all_models  # noqa: F401  (registers every mapper before the first query)
    from app.models.pursuit_analysis import AnalysisRun

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


def read_only(args: argparse.Namespace) -> int:
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


# ---- live mode (through the API) ------------------------------------------------------------


class LiveSmokeError(RuntimeError):
    """The live smoke cannot run safely or did not pass."""


class Api:
    def __init__(self, base: str, token: str, organization_id: str, timeout: float = 60) -> None:
        self.base = base.rstrip("/")
        self._token = token
        self.organization_id = organization_id
        self.timeout = timeout

    def call(self, method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-Organization-ID", self.organization_id)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read()
                return response.status, (json.loads(data) if data else None)
        except urllib.error.HTTPError as exc:
            return exc.code, {"detail": exc.read().decode(errors="replace")[:200]}


def assert_dedicated_test_organization(api: Api, org_name: str) -> None:
    """Refuse unless the token user's only organization is the named, single-member test org."""
    status, organizations = api.call("GET", "/organizations")
    if status != 200 or not isinstance(organizations, list):
        raise LiveSmokeError(f"cannot list the token user's organizations (HTTP {status})")
    if len(organizations) != 1:
        raise LiveSmokeError(
            f"the smoke user belongs to {len(organizations)} organizations; it must belong to exactly one dedicated test organization"
        )
    organization = organizations[0]
    if str(organization.get("organization_id")) != api.organization_id:
        raise LiveSmokeError("--org-id is not the smoke user's organization")
    if (organization.get("display_name") or "") != org_name:
        raise LiveSmokeError("the organization's display name does not equal --org-name")
    status, members = api.call("GET", f"/organizations/{api.organization_id}/members")
    if status != 200 or not isinstance(members, list):
        raise LiveSmokeError(f"cannot list the test organization's members (HTTP {status})")
    active = [member for member in members if str(member.get("state", "")).upper() == "ACTIVE"]
    if len(active) != 1 or str(active[0].get("membership_id") or active[0].get("id")) != str(organization.get("membership_id")):
        raise LiveSmokeError("the test organization must have exactly one active member: the smoke user")


def pick_reoi(api: Api) -> str:
    query = urllib.parse.urlencode({"source_system": "world_bank", "q": REOI_QUERY, "limit": 25})
    status, page = api.call("GET", f"/explorer/tenders?{query}")
    if status != 200 or not isinstance(page, dict) or not page.get("items"):
        raise LiveSmokeError(f"no open World Bank REOI found (HTTP {status}); pass --tender-id")
    return str(page["items"][0]["tender"]["id"])


def live_run(api: Api, pursuit_id: str, *, poll_seconds: float, max_wait: float) -> dict:
    status, candidate = api.call("GET", f"/pursuits/{pursuit_id}/analysis-pack-candidate")
    if status != 200 or not isinstance(candidate, dict):
        raise LiveSmokeError(f"pack candidate failed (HTTP {status})")
    notices = [d for d in candidate.get("source_documents", []) if d.get("role") == "OFFICIAL_NOTICE" and d.get("parse_ready")]
    if not notices:
        raise LiveSmokeError("the tender has no parse-ready OFFICIAL_NOTICE; run the D1-03 backfill or pass another --tender-id")
    request = {
        "candidate_sha256": candidate["candidate_sha256"], "analysis_language": "en",
        "source_document_ids": [notices[0]["tender_document_id"]], "private_version_ids": [],
    }
    started = time.monotonic()
    status, start = api.call("POST", f"/pursuits/{pursuit_id}/analysis-runs", request)
    if status != 202 or not isinstance(start, dict):
        raise LiveSmokeError(f"analysis start failed (HTTP {status})")
    run_id = start["analysis_run_id"]
    result: dict = {}
    while time.monotonic() - started < max_wait:
        status, body = api.call("GET", f"/pursuits/{pursuit_id}/analysis-runs/{run_id}")
        if status == 200 and isinstance(body, dict) and body.get("status") in {"COMPLETED", "FAILED"}:
            result = body
            break
        time.sleep(poll_seconds)
    latency = round(time.monotonic() - started, 1)
    origins: dict[str, int] = {}
    for item in result.get("requirements", []) + result.get("positions", []):
        origin = (item.get("source_locator") or {}).get("context_origin") or "NONE"
        origins[origin] = origins.get(origin, 0) + 1
    return {
        "run_id": run_id,
        "status": result.get("status", "TIMEOUT"),
        "quality_state": result.get("quality_state"),
        "latency_s": latency,
        "model": result.get("model_name"),
        "pipeline": result.get("pipeline_version"),
        "requirements": len(result.get("requirements", [])),
        "positions": len(result.get("positions", [])),
        "gaps": len(result.get("gaps", [])),
        "context_origins": origins,
        "failure_stage": result.get("failure_stage"),
    }


def live(args: argparse.Namespace, environ: dict | None = None) -> int:
    env = os.environ if environ is None else environ
    token = env.get("ANALYSIS_SMOKE_TOKEN", "").strip()
    if not token:
        print("FAIL: set ANALYSIS_SMOKE_TOKEN to the smoke user's bearer token", file=sys.stderr)
        return 2
    if not args.api_base or not args.org_id or not args.org_name:
        print("FAIL: --live needs --api-base, --org-id and --org-name", file=sys.stderr)
        return 2
    api = Api(args.api_base, token, args.org_id)
    try:
        assert_dedicated_test_organization(api, args.org_name)
        tender_id = args.tender_id or pick_reoi(api)
        status, pursuit = api.call("POST", "/pursuits/source", {"tender_id": tender_id})
        if status not in (200, 201) or not isinstance(pursuit, dict):
            raise LiveSmokeError(f"source pursuit create failed (HTTP {status})")
        records = [
            live_run(api, str(pursuit["pursuit_id"]), poll_seconds=args.poll_seconds, max_wait=args.max_wait)
            for _ in range(args.runs)
        ]
    except LiveSmokeError as exc:
        print(f"FAIL: {exc}")
        return 1
    problems = []
    for index, record in enumerate(records, start=1):
        print(json.dumps({"run": index, "tender_id": tender_id, **record}))
        if record["status"] != "COMPLETED" or record["quality_state"] != "READY_FOR_REVIEW":
            problems.append(f"run {index}: {record['status']} / {record['quality_state']}")
        if record["requirements"] < args.min_requirements:
            problems.append(f"run {index}: {record['requirements']} requirements < {args.min_requirements}")
        if record["latency_s"] > args.max_latency:
            problems.append(f"run {index}: latency {record['latency_s']} s > {args.max_latency} s")
    for problem in problems:
        print(f"FAIL: {problem}")
    print("live analysis smoke: " + ("FAILED" if problems else "OK"))
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, default=24, help="Run-health window (default 24).")
    parser.add_argument("--max-queued-minutes", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    live_group = parser.add_argument_group("--live (end to end through the API)")
    live_group.add_argument("--live", action="store_true")
    live_group.add_argument("--api-base", help="e.g. https://api.example.com/api/v1")
    live_group.add_argument("--org-id", help="The dedicated test organization's id.")
    live_group.add_argument("--org-name", help="Its exact display name (safety check).")
    live_group.add_argument("--tender-id", help="Open World Bank REOI; default: first match in Explorer.")
    live_group.add_argument("--runs", type=int, default=1)
    live_group.add_argument("--max-latency", type=float, default=60.0)
    live_group.add_argument("--min-requirements", type=int, default=5)
    live_group.add_argument("--max-wait", type=float, default=900.0)
    live_group.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    return live(args) if args.live else read_only(args)


if __name__ == "__main__":
    sys.exit(main())
