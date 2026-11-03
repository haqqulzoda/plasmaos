#!/usr/bin/env python3
"""Requirement-extraction evaluation for English, Russian and Uzbek tender notices.

Offline commands (no network, no API key, no database):

    python scripts/eval_requirement_extraction.py validate
    python scripts/eval_requirement_extraction.py score --outputs <dir> [--label <name>] [--out <dir>]
    python scripts/eval_requirement_extraction.py scope-check [--out <dir>]

Live command (calls the paid model provider; operator only, with their own key):

    python scripts/eval_requirement_extraction.py live --pipeline pursuit --out <dir> \\
        --confirm-live-provider-calls [--max-docs N] [--analysis-language document|en|ru|uz]

Source refresh (public network; rebuilds source texts and compares them with the stored ones):

    python scripts/eval_requirement_extraction.py build-sources

Run from ``backend/``. See ``backend/evaluation/README.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evaluation.requirements_eval import adapters, dataset as dataset_module, report, scoring  # noqa: E402

DEFAULT_DATASET = BACKEND_DIR / "evaluation" / "datasets" / "req_eval_v0_draft"
DEFAULT_REPORT_DIR = BACKEND_DIR.parent / ".private-storage" / "eval_reports"  # gitignored
GROUPINGS = (("language", "en"), ("script", "LATIN"), ("source", "world_bank"), ("procurement_type", None),
             ("country", None), ("format", None), ("requirement_type", None), ("obligation", None))


def _load(path: Path) -> dataset_module.Dataset:
    data = dataset_module.load(path)
    if data.problems:
        for problem in data.problems:
            print(f"DATASET PROBLEM: {problem}", file=sys.stderr)
    return data


def cmd_validate(args: argparse.Namespace) -> int:
    data = _load(args.dataset)
    print(json.dumps(dataset_module.summary(data), ensure_ascii=False, indent=2))
    print(f"problems: {len(data.problems)}")
    return 1 if data.problems else 0


def cmd_score(args: argparse.Namespace) -> int:
    data = _load(args.dataset)
    if data.problems:
        return 1
    stored = adapters.load_run(args.outputs)
    unknown = sorted(set(stored) - set(data.by_id()))
    if unknown:
        print(f"Ignoring outputs for unknown documents: {', '.join(unknown)}", file=sys.stderr)
    results = scoring.score_run(data, {doc_id: predictions for doc_id, (predictions, _) in stored.items()})
    scored = [result for result in results if result.has_output]
    payload = {
        "meta": {
            "run_label": args.label or args.outputs.name, "dataset_id": data.manifest.get("dataset_id"),
            "dataset_status": data.status, "outputs": str(args.outputs), "documents": len(results),
            "documents_with_output": len(scored),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "min_overlap": scoring.MIN_OVERLAP, "bootstrap_samples": args.samples, "bootstrap_seed": scoring.BOOTSTRAP_SEED,
        },
        "overall": scoring.overall(scored),
        "groups": [
            scoring.group_report(scored, grouping, reference=reference, samples=args.samples)
            for grouping, reference in GROUPINGS
        ],
    }
    markdown = report.render_score(payload)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"score-{payload['meta']['run_label']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=list), encoding="utf-8"
        )
        (args.out / f"score-{payload['meta']['run_label']}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


def cmd_scope_check(args: argparse.Namespace) -> int:
    from evaluation.requirements_eval import scope_check

    data = _load(args.dataset)
    if data.problems:
        return 1
    payload = scope_check.run(data, samples=args.samples)
    markdown = report.render_scope_check(payload)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "scope-check.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out / "scope-check.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    from evaluation.requirements_eval import live

    data = _load(args.dataset)
    if data.problems:
        return 1
    try:
        summary = live.run_sync(
            data, pipeline=args.pipeline, out=args.out, confirmed=args.confirm_live_provider_calls,
            analysis_language=args.analysis_language, max_docs=args.max_docs, only=args.only, resume=args.resume,
        )
    except live.LiveModeRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in summary.items() if k != "documents"}, indent=2))
    print(f"Stored outputs for {len(summary['documents'])} document(s) in {args.out}. Score them with: "
          f"python scripts/eval_requirement_extraction.py score --outputs {args.out}")
    return 1 if summary["failures"] else 0


def cmd_build_sources(args: argparse.Namespace) -> int:
    from evaluation.requirements_eval import sources

    manifest_path = args.dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = 0
    for meta in manifest["documents"]:
        fetch = sources.fetch_world_bank if meta["source"] == "world_bank" else sources.fetch_uzex
        try:
            row = fetch(meta["source_ref"])
        except Exception as exc:  # network or removal at the source
            print(f"{meta['doc_id']}: fetch failed ({type(exc).__name__})")
            changed += 1
            continue
        rebuilt = sources.build_text(meta["source"], row)
        stored = (args.dataset / meta["text_path"]).read_text(encoding="utf-8")
        status = "unchanged" if sources.matches_with_redactions(stored, rebuilt) else "CHANGED"
        print(f"{meta['doc_id']}: {status}")
        if status == "CHANGED":
            changed += 1  # never overwritten: labels were made against the stored text
    return 1 if changed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="check labels against source texts and print counts")
    score = sub.add_parser("score", help="score stored outputs (offline)")
    score.add_argument("--outputs", type=Path, required=True, help="directory of <doc_id>.json outputs")
    score.add_argument("--label", default=None)
    score.add_argument("--out", type=Path, default=None, help=f"write JSON and markdown here (e.g. {DEFAULT_REPORT_DIR})")
    score.add_argument("--samples", type=int, default=scoring.BOOTSTRAP_SAMPLES)
    scope = sub.add_parser("scope-check", help="offline language check of the deterministic scope classifier")
    scope.add_argument("--out", type=Path, default=None)
    scope.add_argument("--samples", type=int, default=2000)
    live = sub.add_parser("live", help="run the real pipeline (paid provider; operator only)")
    live.add_argument("--pipeline", choices=("pursuit", "compliance"), required=True)
    live.add_argument("--out", type=Path, required=True)
    live.add_argument("--confirm-live-provider-calls", action="store_true")
    live.add_argument("--analysis-language", choices=("document", "en", "ru", "uz"), default="document")
    live.add_argument("--max-docs", type=int, default=None)
    live.add_argument("--only", nargs="*", default=None, help="document ids")
    live.add_argument("--resume", action="store_true")
    sub.add_parser("build-sources", help="refetch public sources and compare with stored texts (never overwrites)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return {
        "validate": cmd_validate, "score": cmd_score, "scope-check": cmd_scope_check,
        "live": cmd_live, "build-sources": cmd_build_sources,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
