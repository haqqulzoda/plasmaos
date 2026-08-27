#!/usr/bin/env python3
"""Read-only aggregate-identity diagnostics for TenderAnalysis parents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text

from app.db.session import AsyncSessionLocal, engine


AGGREGATE_AUDIT_SQL = text(
    """
    WITH grouped AS (
        SELECT ownership_state, user_id, company_profile_id, tender_id,
               COUNT(*)::bigint AS parents
        FROM tender_analyses
        GROUP BY ownership_state, user_id, company_profile_id, tender_id
    ),
    invalid AS (
        SELECT COUNT(*)::bigint AS rows
        FROM tender_analyses AS analysis
        LEFT JOIN company_profiles AS profile
          ON profile.id = analysis.company_profile_id
        WHERE
          (analysis.ownership_state = 'OWNED' AND (
             analysis.user_id IS NULL OR analysis.company_profile_id IS NULL OR
             profile.id IS NULL OR profile.user_id <> analysis.user_id
          )) OR
          (analysis.ownership_state = 'QUARANTINED_LEGACY' AND (
             analysis.user_id IS NOT NULL OR analysis.company_profile_id IS NOT NULL
          ))
    )
    SELECT
      (SELECT COUNT(*)::bigint FROM tender_analyses) AS total_tender_analyses,
      COUNT(*)::bigint AS distinct_logical_aggregate_keys,
      COUNT(*) FILTER (WHERE parents = 1)::bigint AS keys_with_one_parent,
      COUNT(*) FILTER (WHERE parents > 1)::bigint AS keys_with_multiple_parents,
      COALESCE(MAX(parents), 0)::bigint AS max_parents_per_key,
      COUNT(*) FILTER (
        WHERE ownership_state = 'OWNED'
      )::bigint AS owned_logical_aggregate_keys,
      COUNT(*) FILTER (
        WHERE ownership_state = 'OWNED' AND parents = 1
      )::bigint AS owned_single_parent_keys,
      COUNT(*) FILTER (
        WHERE ownership_state = 'OWNED' AND parents > 1
      )::bigint AS owned_multi_parent_keys,
      COUNT(*) FILTER (
        WHERE ownership_state = 'QUARANTINED_LEGACY'
      )::bigint AS quarantined_keys,
      COUNT(*) FILTER (
        WHERE ownership_state = 'QUARANTINED_LEGACY' AND parents > 1
      )::bigint AS quarantined_multi_parent_keys,
      (SELECT rows FROM invalid) AS invalid_canonical_keys
    FROM grouped
    """
)


async def main() -> int:
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(AGGREGATE_AUDIT_SQL)).mappings().one()
            await db.rollback()
        payload = {key: int(value or 0) for key, value in row.items()}
        payload["canonical_parent_mechanism"] = "transaction_advisory_lock"
        payload["post_cutover_marker"] = False
        payload["post_cutover_canonical_parents"] = None
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
