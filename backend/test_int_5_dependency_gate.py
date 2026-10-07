"""INT-5: the dependency gate blocks on production npm dependencies while a dated exception is valid."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import dependency_exceptions  # noqa: E402

DOC = (ROOT / "docs" / "ops" / "DEPENDENCY_EXCEPTIONS.md").read_text(encoding="utf-8")


def test_the_recorded_exception_is_the_braces_chain_until_2026_11_08() -> None:
    assert dependency_exceptions.exceptions(DOC) == [("npm-dev-braces-chain", "2026-11-08")]
    for needle in ("eslint-config-next", "fast-glob", "micromatch", "braces", "GHSA-vfj7-8cjw-p6xm",
                   "found 0 vulnerabilities", "2026-10-08", "2026-11-08"):
        assert needle in DOC, needle


def test_the_exception_is_valid_through_its_expiry_day_and_fails_after() -> None:
    assert dependency_exceptions.check(DOC, date(2026, 10, 8))[0] == 0
    assert dependency_exceptions.check(DOC, date(2026, 11, 8))[0] == 0      # the expiry day is included
    status, lines = dependency_exceptions.check(DOC, date(2026, 11, 9))
    assert status == 1 and "EXPIRED" in lines[0]                           # the full audit blocks again
    assert dependency_exceptions.check("no exceptions here", date(2026, 10, 8))[0] == 2
    assert dependency_exceptions.check("EXCEPTION x EXPIRES 2026-13-40", date(2026, 10, 8))[0] == 1
    assert dependency_exceptions.main(["check", "--today", "2026-10-08"]) == 0
    assert dependency_exceptions.main(["check", "--today", "2026-12-01"]) == 1


def test_the_gate_reports_the_full_audit_and_blocks_on_production_dependencies() -> None:
    gate = (ROOT / "scripts" / "run_release_gate.sh").read_text(encoding="utf-8")
    group = gate[gate.index("    config-dependencies)"):gate.index("    *) echo \"Unknown release gate group")]
    report = group.index("run_npm audit --audit-level=high) || true")       # full audit: report only
    check = group.index("dependency_exceptions.py check")
    blocking = group.index("run_npm audit --omit=dev --audit-level=high")
    expired = group.rindex("run_npm audit --audit-level=high)")              # after expiry: full audit blocks
    assert report < check < blocking < expired
    assert group.count("|| true") == 1
