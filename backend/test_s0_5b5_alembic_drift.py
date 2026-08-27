"""Static contracts for Sprint 0.5B.5 metadata-only Alembic drift closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint

from app.models.all_models import Base


BACKEND_DIR = Path(__file__).resolve().parent
BASELINE_DIR = BACKEND_DIR / "db" / "baselines"
CANONICAL_COMMENT = (
    "SHA-256 seal incorporating override state. "
    "Null when no overrides have been applied."
)


def test_proposal_orm_declares_canonical_named_uniqueness() -> None:
    table = Base.metadata.tables["proposals"]
    matching = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_proposals_user_tender"
    ]
    assert len(matching) == 1
    assert tuple(column.name for column in matching[0].columns) == ("user_id", "tender_id")
    assert not [index for index in table.indexes if index.name == "uq_proposals_user_tender"]


def test_override_seal_schema_comment_matches_historical_contract() -> None:
    column = Base.metadata.tables["tender_analyses"].c.override_seal
    assert column.comment == CANONICAL_COMMENT
    assert column.nullable
    assert str(column.type) == "VARCHAR(64)"
    assert "sorted_override_node_ids" in (column.doc or "")


def test_repository_graph_extends_b3_with_compliance_ownership() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260827_0002_s2_2_analysis_version_foundation"]
    assert (
        script.get_revision("20260827_0001_s2_1_compliance_ownership").down_revision
        == "20260826_0002_s1_2_wb_project_enrichment"
    )
    assert (
        script.get_revision("20260826_0002_s1_2_wb_project_enrichment").down_revision
        == "20260826_0001_s1_1_project_foundation"
    )
    assert (
        script.get_revision("20260826_0001_s1_1_project_foundation").down_revision
        == "20260825_0001_s0_5b3"
    )
    assert script.get_revision("20260825_0001_s0_5b3").down_revision == "20260824_0002_s0_4c"
    assert len(list((BACKEND_DIR / "alembic" / "versions").glob("*.py"))) == 23


def test_historical_migrations_are_untouched() -> None:
    expected = {
        "d21a4f2b7c31_enforce_unique_user_tender_proposals.py": (
            "9db9df2d871630780dbbb7029152416f4057b1f3ad86ee284c204a870b9ec623"
        ),
        "a8f3d1c2e5b4_add_override_seal_to_tender_analyses.py": (
            "4bb6343e5e29358b1ff7fe4616442eb29e78b5369149b8711805bf793f37de76"
        ),
    }
    for name, digest in expected.items():
        path = BACKEND_DIR / "alembic" / "versions" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_immutable_baseline_and_manifest_are_untouched() -> None:
    snapshot = BASELINE_DIR / "20260824_0002_s0_4c.sql"
    manifest_path = BASELINE_DIR / "20260824_0002_s0_4c.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == (
        "8d34e4a5a57be2867c326b151ae6ef034cf34ab3dab02ad212996a6257396f7b"
    )
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == (
        "5007013a5aab84d5c08730aedef742a929978949305c146511a14293f8a776ad"
    )
    assert manifest["snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    sql = snapshot.read_text(encoding="utf-8")
    assert "ADD CONSTRAINT uq_proposals_user_tender UNIQUE (user_id, tender_id)" in sql
    assert f"COMMENT ON COLUMN public.tender_analyses.override_seal IS '{CANONICAL_COMMENT}'" in sql


def test_tender_recommendation_contract_is_unchanged() -> None:
    table = Base.metadata.tables["tender_recommendations"]
    assert set(table.columns) == {
        table.c.id,
        table.c.tender_id,
        table.c.company_profile_id,
        table.c.match_score,
        table.c.strategic_rationale,
        table.c.is_dismissed,
        table.c.created_at,
    }
    assert "uq_tender_recommendations_tender_profile" in {
        constraint.name for constraint in table.constraints
    }

