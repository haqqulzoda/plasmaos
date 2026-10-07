#!/usr/bin/env python3
"""Check the release gate's dependency exceptions (docs/ops/DEPENDENCY_EXCEPTIONS.md).

    python backend/scripts/dependency_exceptions.py check [--today YYYY-MM-DD] [--file PATH]

Exit 0 when every ``EXCEPTION <name> EXPIRES <YYYY-MM-DD>`` line is still valid on --today
(the expiry day itself is included), 1 when any has expired (or a line is malformed), 2 when the
file lists none. The gate then blocks on the full ``npm audit`` again. Standard library only.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sys

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "docs" / "ops" / "DEPENDENCY_EXCEPTIONS.md"
LINE = re.compile(r"^EXCEPTION\s+(?P<name>[A-Za-z0-9._-]+)\s+EXPIRES\s+(?P<expires>\S+)\s*$")


def exceptions(text: str) -> list[tuple[str, str]]:
    return [(match["name"], match["expires"]) for line in text.splitlines() if (match := LINE.match(line.strip()))]


def check(text: str, today: date) -> tuple[int, list[str]]:
    found = exceptions(text)
    if not found:
        return 2, ["no dependency exceptions are listed"]
    status, lines = 0, []
    for name, expires in found:
        try:
            until = date.fromisoformat(expires)
        except ValueError:
            status = 1
            lines.append(f"{name}: malformed expiry {expires!r}")
            continue
        if today > until:
            status = 1
            lines.append(f"{name}: EXPIRED on {until.isoformat()} (renew it in docs/ops/DEPENDENCY_EXCEPTIONS.md or fix the advisory)")
        else:
            lines.append(f"{name}: active until {until.isoformat()}")
    return status, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args(argv)
    today = args.today or datetime.now(timezone.utc).date()
    status, lines = check(args.file.read_text(encoding="utf-8"), today)
    for line in lines:
        print(f"dependency exception {line}")
    return status


if __name__ == "__main__":
    sys.exit(main())
