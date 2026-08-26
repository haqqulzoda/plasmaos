"""Static/metadata contract tests for Sprint 0.5B.3."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.all_models import Base


ROOT = Path(__file__).resolve().parent
MIGRATION_PATH = (
    ROOT
    / "alembic/versions/20260825_0001_s0_5b3_tender_recommendation_reconciliation.py"
)
HISTORICAL_PATH = (
    ROOT / "alembic/versions/65c42c5b80fa_add_tenderrecommendation_table.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("s0_5b3_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TenderRecommendationOrmContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = Base.metadata.tables["tender_recommendations"]

    def test_complete_column_contract(self) -> None:
        self.assertEqual(
            list(self.table.columns),
            [
                self.table.c.id,
                self.table.c.tender_id,
                self.table.c.company_profile_id,
                self.table.c.match_score,
                self.table.c.strategic_rationale,
                self.table.c.is_dismissed,
                self.table.c.created_at,
            ],
        )
        self.assertTrue(all(not column.nullable for column in self.table.columns))
        self.assertIsInstance(self.table.c.id.type, PGUUID)
        self.assertIsInstance(self.table.c.tender_id.type, PGUUID)
        self.assertIsInstance(self.table.c.company_profile_id.type, PGUUID)
        self.assertIsInstance(self.table.c.match_score.type, Integer)
        self.assertIsInstance(self.table.c.strategic_rationale.type, Text)
        self.assertIsInstance(self.table.c.is_dismissed.type, Boolean)
        self.assertIsInstance(self.table.c.created_at.type, DateTime)
        self.assertTrue(self.table.c.created_at.type.timezone)

    def test_primary_key_foreign_keys_and_delete_contract(self) -> None:
        self.assertEqual([column.name for column in self.table.primary_key], ["id"])
        foreign_keys = {
            foreign_key.parent.name: foreign_key
            for foreign_key in self.table.foreign_keys
        }
        self.assertEqual(foreign_keys["tender_id"].target_fullname, "tenders.id")
        self.assertEqual(
            foreign_keys["company_profile_id"].target_fullname,
            "company_profiles.id",
        )
        self.assertEqual(foreign_keys["tender_id"].ondelete, "CASCADE")
        self.assertEqual(foreign_keys["company_profile_id"].ondelete, "CASCADE")

    def test_unique_check_default_and_index_contract(self) -> None:
        unique = next(
            constraint
            for constraint in self.table.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_tender_recommendations_tender_profile"
        )
        self.assertEqual(
            tuple(column.name for column in unique.columns),
            ("tender_id", "company_profile_id"),
        )
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in self.table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("match_score >= 0", checks["ck_tender_recommendations_match_score_range"])
        self.assertIn("match_score <= 100", checks["ck_tender_recommendations_match_score_range"])
        self.assertEqual(str(self.table.c.is_dismissed.server_default.arg), "false")
        self.assertIn("now", str(self.table.c.created_at.server_default.arg).casefold())
        self.assertEqual(
            {index.name: tuple(column.name for column in index.columns) for index in self.table.indexes},
            {
                "ix_tender_recommendations_tender_id": ("tender_id",),
                "ix_tender_recommendations_company_profile_id": ("company_profile_id",),
                "ix_tender_recommendations_created_at": ("created_at",),
            },
        )


class TenderRecommendationMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migration = _load_migration()
        cls.source = MIGRATION_PATH.read_text(encoding="utf-8")

    def test_repository_has_expected_new_head_and_parent(self) -> None:
        config = Config()
        config.set_main_option("script_location", str(ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)
        self.assertEqual(
            script.get_current_head(),
            "20260826_0002_s1_2_wb_project_enrichment",
        )
        self.assertEqual(self.migration.down_revision, "20260824_0002_s0_4c")

    def test_migration_contract_matches_orm_columns(self) -> None:
        self.assertEqual(
            set(self.migration.EXPECTED_COLUMNS),
            set(Base.metadata.tables["tender_recommendations"].columns.keys()),
        )
        self.assertEqual(
            self.migration.EXPECTED_INDEXES,
            {
                "ix_tender_recommendations_tender_id": ("tender_id",),
                "ix_tender_recommendations_company_profile_id": ("company_profile_id",),
                "ix_tender_recommendations_created_at": ("created_at",),
            },
        )

    def test_incompatible_schema_raises_clear_failure(self) -> None:
        class IncompatibleInspector:
            def get_columns(self, _table, schema=None):
                del schema
                return [{"name": "id", "type": PGUUID(), "nullable": False, "default": None}]

            def get_pk_constraint(self, _table, schema=None):
                del schema
                return {"constrained_columns": ["id"]}

            def get_foreign_keys(self, _table, schema=None):
                del schema
                return []

            def get_unique_constraints(self, _table, schema=None):
                del schema
                return []

            def get_check_constraints(self, _table, schema=None):
                del schema
                return []

            def get_indexes(self, _table, schema=None):
                del schema
                return []

        with self.assertRaisesRegex(RuntimeError, "Incompatible public.tender_recommendations"):
            self.migration._validate_existing_table(
                IncompatibleInspector(),
                schema="public",
            )

    def test_downgrade_contains_no_destructive_operation(self) -> None:
        tree = ast.parse(self.source)
        downgrade = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
        )
        calls = [
            node
            for node in ast.walk(downgrade)
            if isinstance(node, ast.Call)
        ]
        self.assertEqual(calls, [])
        self.assertNotIn("drop_table", ast.get_source_segment(self.source, downgrade) or "")

    def test_historical_noop_revision_remains_immutable(self) -> None:
        source = HISTORICAL_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("upgrade", "downgrade"):
            self.assertTrue(
                any(isinstance(node, ast.Pass) for node in ast.walk(functions[name]))
            )


if __name__ == "__main__":
    unittest.main()
