"""Audited admin account inspection and promotion command."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text

from app.core.access import (
    PLATFORM_ROLE_ADMIN,
    USER_APPROVAL_APPROVED,
    configured_email_allowlist,
)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _user_payload(user: Any | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "google_id": user.google_id,
        "email": _normalize_email(user.email),
        "name": user.name,
        "platform_role": user.platform_role,
        "approval_status": user.approval_status,
        "is_admin": bool(user.is_admin),
        "approved_at": user.approved_at,
        "auth_version": int(getattr(user, "auth_version", 0) or 0),
        "created_at": user.created_at,
    }


def _user_row_payload(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "google_id": row["google_id"],
        "email": _normalize_email(row["email"]),
        "name": row["name"],
        "platform_role": row["platform_role"],
        "approval_status": row["approval_status"],
        "is_admin": bool(row["is_admin"]),
        "approved_at": row["approved_at"],
        "auth_version": row.get("auth_version"),
        "created_at": row["created_at"],
    }


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


async def _has_column(db, *, table_name: str, column_name: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


async def _has_table(db, table_name: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


async def _admin_repair_schema_status(db) -> dict[str, bool]:
    return {
        "users_auth_version": await _has_column(
            db,
            table_name="users",
            column_name="auth_version",
        ),
        "admin_activity_events": await _has_table(db, "admin_activity_events"),
    }


async def _load_user_row_for_inspect(db, email: str) -> dict[str, Any] | None:
    has_auth_version = await _has_column(
        db,
        table_name="users",
        column_name="auth_version",
    )
    auth_version_select = "auth_version" if has_auth_version else "NULL::integer AS auth_version"
    result = await db.execute(
        text(
            f"""
            SELECT
                id,
                google_id,
                email,
                name,
                platform_role,
                approval_status,
                is_admin,
                approved_at,
                {auth_version_select},
                created_at
            FROM users
            WHERE lower(email) = :email
            """
        ),
        {"email": email},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _load_user(db, email: str) -> User | None:
    from app.models.all_models import User

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    return result.scalar_one_or_none()


async def inspect_admin(args: argparse.Namespace) -> int:
    from app.db.session import AsyncSessionLocal

    email = _normalize_email(args.email)
    admin_allowlist = configured_email_allowlist("PLASMA_ADMIN_EMAILS")
    async with AsyncSessionLocal() as db:
        schema = await _admin_repair_schema_status(db)
        user = await _load_user_row_for_inspect(db, email)
        _print_payload(
            {
                "mode": "inspect",
                "email": email,
                "schema": schema,
                "admin_allowlist_match": email in admin_allowlist,
                "user": _user_row_payload(user),
            }
        )
    return 0 if user is not None else 1


async def promote_admin(args: argparse.Namespace) -> int:
    from app.db.session import AsyncSessionLocal
    from app.services.admin_activity import (
        bump_auth_version,
        record_admin_activity,
        user_role_snapshot,
    )

    email = _normalize_email(args.email)
    expected_google_id = args.google_id.strip()
    admin_allowlist = configured_email_allowlist("PLASMA_ADMIN_EMAILS")

    if email not in admin_allowlist:
        _print_payload(
            {
                "mode": "promote",
                "status": "blocked",
                "reason": "email_not_in_PLASMA_ADMIN_EMAILS",
                "email": email,
            }
        )
        return 2

    async with AsyncSessionLocal() as db:
        schema = await _admin_repair_schema_status(db)
        if not all(schema.values()):
            _print_payload(
                {
                    "mode": "promote",
                    "status": "blocked",
                    "reason": "schema_not_migrated",
                    "email": email,
                    "schema": schema,
                }
            )
            return 5

        user = await _load_user(db, email)
        if user is None:
            _print_payload(
                {
                    "mode": "promote",
                    "status": "blocked",
                    "reason": "user_not_found",
                    "email": email,
                }
            )
            return 3

        if user.google_id != expected_google_id:
            _print_payload(
                {
                    "mode": "promote",
                    "status": "blocked",
                    "reason": "google_id_mismatch",
                    "email": email,
                    "actual_google_id": user.google_id,
                }
            )
            return 4

        actor_user = None
        actor_label = args.actor_label
        if args.actor_email:
            actor_user = await _load_user(db, _normalize_email(args.actor_email))
            actor_label = actor_label or f"admin-management-command:{_normalize_email(args.actor_email)}"
        actor_label = actor_label or "admin-management-command"

        before = user_role_snapshot(user)
        changed = False
        if user.platform_role != PLATFORM_ROLE_ADMIN:
            user.platform_role = PLATFORM_ROLE_ADMIN
            changed = True
        if user.approval_status != USER_APPROVAL_APPROVED:
            user.approval_status = USER_APPROVAL_APPROVED
            changed = True
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if user.approved_at is None:
            user.approved_at = datetime.now(timezone.utc)
            changed = True

        if changed:
            bump_auth_version(user)
            await record_admin_activity(
                db,
                action="admin_promoted",
                actor_user=actor_user,
                actor_label=actor_label,
                target_user=user,
                reason=args.reason,
                metadata={
                    "before": before,
                    "after": user_role_snapshot(user),
                    "verified_google_id": expected_google_id,
                    "admin_allowlist_match": True,
                    "fresh_auth_required": True,
                },
            )
            await db.commit()
            await db.refresh(user)
        else:
            await db.rollback()

        _print_payload(
            {
                "mode": "promote",
                "status": "changed" if changed else "no_op",
                "email": email,
                "fresh_auth_required": changed,
                "user": _user_payload(user),
            }
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one account without writing data.")
    inspect_parser.add_argument("--email", required=True)

    promote_parser = subparsers.add_parser("promote", help="Promote an allowlisted verified account to admin.")
    promote_parser.add_argument("--email", required=True)
    promote_parser.add_argument("--google-id", required=True)
    promote_parser.add_argument("--actor-email")
    promote_parser.add_argument("--actor-label")
    promote_parser.add_argument(
        "--reason",
        default="Verified allowlisted main administrator repair.",
    )

    return parser


async def async_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "inspect":
        return await inspect_admin(args)
    if args.mode == "promote":
        return await promote_admin(args)
    parser.error("unknown mode")
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
