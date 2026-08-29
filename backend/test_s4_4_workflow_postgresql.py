"""Expose the Sprint 4.4 disposable PostgreSQL proof to pytest."""

from __future__ import annotations

import asyncio

from scripts.test_s4_4_tender_engagement_workflow_ux import scenario
from scripts import test_s0_5b4_baseline as support


def test_s4_4_workflow_against_disposable_postgresql() -> None:
    async def run() -> None:
        database = support.database_name("s44_pytest")
        await support.create_database(database)
        try:
            result = await scenario(database)
            assert result["alembic_check"] == "clean"
        finally:
            await support.drop_database(database)

    asyncio.run(run())
