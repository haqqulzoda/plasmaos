"""
Sovereign Audit Trail cryptographic service.

Implements hash-chain creation for human-in-the-loop authorizations.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

ACTION_TYPE = "MITIGATION_AUTHORIZED"
GENESIS_PREVIOUS_HASH = "GENESIS"


async def get_latest_audit_hash(session: AsyncSession) -> str | None:
    """
    Return the most recent ledger hash.

    The newest record is selected by descending timestamp.
    Returns None when no audit records exist yet (genesis case).
    """
    stmt = (
        select(AuditLog.current_hash)
        .order_by(AuditLog.timestamp.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def generate_sha256_hash(payload: dict, previous_hash: str | None) -> str:
    """
    Deterministically hash a payload linked to the previous ledger hash.

    Rules:
    - Payload JSON is serialized with `sort_keys=True` for deterministic ordering.
    - When `previous_hash` is None, use the genesis marker ("GENESIS").
    """
    payload_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    anchor_hash = previous_hash if previous_hash is not None else GENESIS_PREVIOUS_HASH
    chain_material = f"{anchor_hash}|{payload_json}".encode("utf-8")
    return hashlib.sha256(chain_material).hexdigest()


async def record_audit_action(
    session: AsyncSession,
    analysis_id: UUID,
    user_id: str,
    risk_type: str,
) -> AuditLog:
    """
    Record a MITIGATION_AUTHORIZED action into the hash-chained audit ledger.

    Steps:
    1) Read latest chain hash.
    2) Build deterministic payload.
    3) Generate current hash.
    4) Persist and commit ledger row.
    """
    previous_hash = await get_latest_audit_hash(session)
    current_timestamp = datetime.now(timezone.utc)

    payload: dict[str, str] = {
        "analysis_id": str(analysis_id),
        "user_id": user_id,
        "action": ACTION_TYPE,
        "risk_type": risk_type,
        "timestamp": current_timestamp.isoformat(),
    }

    current_hash = generate_sha256_hash(payload=payload, previous_hash=previous_hash)

    audit_entry = AuditLog(
        analysis_id=analysis_id,
        user_id=user_id,
        action_type=ACTION_TYPE,
        risk_type=risk_type,
        timestamp=current_timestamp,
        previous_hash=previous_hash,
        current_hash=current_hash,
    )

    session.add(audit_entry)
    await session.commit()
    await session.refresh(audit_entry)
    return audit_entry

