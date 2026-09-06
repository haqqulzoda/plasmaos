#!/usr/bin/env python3
"""Fresh bootstrap, sole head, current, drift and read-only schema preflight."""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_test_target import assert_local_test_target


async def main():
    assert_local_test_target()
    from scripts import test_s0_5b4_baseline as support
    database = support.database_name("release_migrations")
    await support.create_database(database)
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
        assert bootstrap.returncode == 0, "Disposable bootstrap failed"
        for command in ("heads", "current", "check"):
            result = await asyncio.to_thread(support.alembic, database, command)
            assert result.returncode == 0
            if command in {"heads", "current"}:
                assert result.stdout.count("20260904_0001_s8_2_analysis_language") == 1
            print(command, "PASS", flush=True)
        result = await asyncio.to_thread(subprocess.run,
            [sys.executable,"scripts/run_s0_3_schema_data_preflight.py","--compact"],
            cwd=support.BACKEND_DIR, env=support.environment(database), capture_output=True,text=True)
        assert result.returncode == 0, "Disposable schema preflight failed"
        print("schema preflight PASS",flush=True)
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    asyncio.run(main())
