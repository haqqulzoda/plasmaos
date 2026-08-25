"""reconcile the TenderRecommendation table with its ORM contract

Revision ID: 20260825_0001_s0_5b3
Revises: 20260824_0002_s0_4c
Create Date: 2026-08-25 00:00:00.000000

The historical TenderRecommendation revision was a no-op. Some databases
therefore have this table from ``create_all`` while Alembic-only databases do
not. This forward migration creates a missing table, preserves a compatible
existing table, and refuses to bless a materially incompatible table.
"""

from __future__ import annotations

import re
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260825_0001_s0_5b3"
down_revision: Union[str, None] = "20260824_0002_s0_4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "tender_recommendations"
EXPECTED_COLUMNS = {
    "id": ("uuid", False),
    "tender_id": ("uuid", False),
    "company_profile_id": ("uuid", False),
    "match_score": ("integer", False),
    "strategic_rationale": ("text", False),
    "is_dismissed": ("boolean", False),
    "created_at": ("timestamptz", False),
}
EXPECTED_INDEXES = {
    "ix_tender_recommendations_tender_id": ("tender_id",),
    "ix_tender_recommendations_company_profile_id": ("company_profile_id",),
    "ix_tender_recommendations_created_at": ("created_at",),
}


def _type_kind(column_type: Any) -> str:
    if isinstance(column_type, postgresql.UUID):
        return "uuid"
    if isinstance(column_type, sa.Boolean):
        return "boolean"
    if isinstance(column_type, sa.Integer) and not isinstance(column_type, sa.BigInteger):
        return "integer"
    if isinstance(column_type, sa.Text):
        return "text"
    if isinstance(column_type, sa.DateTime) and bool(column_type.timezone):
        return "timestamptz"
    return str(column_type).casefold()


def _normalized_sql(value: Any) -> str:
    text_value = str(value or "").strip().casefold().replace('"', "")
    text_value = re.sub(r"::[a-z_ ]+", "", text_value)
    return re.sub(r"[\s()]", "", text_value)


def _validate_existing_table(inspector: Any, *, schema: str) -> None:
    problems: list[str] = []
    columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE_NAME, schema=schema)
    }
    for name, (expected_type, expected_nullable) in EXPECTED_COLUMNS.items():
        column = columns.get(name)
        if column is None:
            problems.append(f"missing required column {name}")
            continue
        actual_type = _type_kind(column["type"])
        if actual_type != expected_type:
            problems.append(
                f"column {name} has type {actual_type}, expected {expected_type}"
            )
        if bool(column.get("nullable")) != expected_nullable:
            problems.append(
                f"column {name} nullable={column.get('nullable')}, "
                f"expected {expected_nullable}"
            )

    dismissed_default = _normalized_sql(columns.get("is_dismissed", {}).get("default"))
    if dismissed_default not in {"false", "'false'"}:
        problems.append("is_dismissed must have server default false")
    created_default = _normalized_sql(columns.get("created_at", {}).get("default"))
    if created_default not in {"now", "current_timestamp"}:
        problems.append("created_at must have server default now()/CURRENT_TIMESTAMP")

    primary_key = inspector.get_pk_constraint(TABLE_NAME, schema=schema)
    if tuple(primary_key.get("constrained_columns") or ()) != ("id",):
        problems.append("primary key must be exactly (id)")

    expected_foreign_keys = {
        ("tender_id",): ("tenders", ("id",)),
        ("company_profile_id",): ("company_profiles", ("id",)),
    }
    actual_foreign_keys = {
        tuple(foreign_key.get("constrained_columns") or ()): foreign_key
        for foreign_key in inspector.get_foreign_keys(TABLE_NAME, schema=schema)
    }
    for local_columns, (remote_table, remote_columns) in expected_foreign_keys.items():
        foreign_key = actual_foreign_keys.get(local_columns)
        if foreign_key is None:
            problems.append(f"missing foreign key for {local_columns[0]}")
            continue
        if foreign_key.get("referred_table") != remote_table:
            problems.append(
                f"foreign key {local_columns[0]} references "
                f"{foreign_key.get('referred_table')}, expected {remote_table}"
            )
        if tuple(foreign_key.get("referred_columns") or ()) != remote_columns:
            problems.append(f"foreign key {local_columns[0]} must reference id")
        referred_schema = foreign_key.get("referred_schema")
        if referred_schema not in {None, schema}:
            problems.append(
                f"foreign key {local_columns[0]} references schema {referred_schema}, "
                f"expected {schema}"
            )
        ondelete = str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
        if ondelete != "CASCADE":
            problems.append(f"foreign key {local_columns[0]} must use ON DELETE CASCADE")

    unique_constraints = inspector.get_unique_constraints(TABLE_NAME, schema=schema)
    canonical_unique = next(
        (
            constraint
            for constraint in unique_constraints
            if constraint.get("name") == "uq_tender_recommendations_tender_profile"
        ),
        None,
    )
    if canonical_unique is None or tuple(canonical_unique.get("column_names") or ()) != (
        "tender_id",
        "company_profile_id",
    ):
        problems.append(
            "missing canonical unique constraint "
            "uq_tender_recommendations_tender_profile(tender_id, company_profile_id)"
        )

    checks = {
        constraint.get("name"): _normalized_sql(constraint.get("sqltext"))
        for constraint in inspector.get_check_constraints(TABLE_NAME, schema=schema)
    }
    score_check = checks.get("ck_tender_recommendations_match_score_range", "")
    if "match_score>=0" not in score_check or "match_score<=100" not in score_check:
        problems.append("missing canonical match_score range check (0..100)")

    indexes = {
        index.get("name"): tuple(index.get("column_names") or ())
        for index in inspector.get_indexes(TABLE_NAME, schema=schema)
        if not index.get("duplicates_constraint")
    }
    for name, expected_columns in EXPECTED_INDEXES.items():
        if name in indexes and indexes[name] != expected_columns:
            problems.append(
                f"index {name} covers {indexes[name]}, expected {expected_columns}"
            )

    if problems:
        details = "; ".join(problems)
        raise RuntimeError(
            f"Incompatible {schema}.{TABLE_NAME} schema; migration refused: {details}"
        )


def _create_table(*, schema: str) -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column("strategic_rationale", sa.Text(), nullable=False),
        sa.Column(
            "is_dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "match_score >= 0 AND match_score <= 100",
            name="ck_tender_recommendations_match_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["company_profile_id"],
            [f"{schema}.company_profiles.id"],
            name="tender_recommendations_company_profile_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            [f"{schema}.tenders.id"],
            name="tender_recommendations_tender_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="tender_recommendations_pkey"),
        sa.UniqueConstraint(
            "tender_id",
            "company_profile_id",
            name="uq_tender_recommendations_tender_profile",
        ),
        schema=schema,
    )


def _ensure_indexes(inspector: Any, *, schema: str) -> None:
    indexes = {
        index.get("name"): tuple(index.get("column_names") or ())
        for index in inspector.get_indexes(TABLE_NAME, schema=schema)
        if not index.get("duplicates_constraint")
    }
    for name, columns in EXPECTED_INDEXES.items():
        if name not in indexes:
            op.create_index(name, TABLE_NAME, list(columns), unique=False, schema=schema)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    schema = inspector.default_schema_name
    table_exists = TABLE_NAME in inspector.get_table_names(schema=schema)

    if not table_exists:
        _create_table(schema=schema)
        refreshed_inspector = sa.inspect(bind)
        _ensure_indexes(refreshed_inspector, schema=schema)
        return

    _validate_existing_table(inspector, schema=schema)
    _ensure_indexes(inspector, schema=schema)


def downgrade() -> None:
    # Intentionally non-destructive. Alembic cannot know whether this table was
    # created by this migration or predated it via historical create_all. A
    # blind DROP would destroy recommendation history. Roll forward instead.
    pass
