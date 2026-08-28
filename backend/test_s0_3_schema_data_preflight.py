from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts/run_s0_3_schema_data_preflight.py"
SPEC = importlib.util.spec_from_file_location("s0_3_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SchemaDataPreflightSafetyTests(unittest.TestCase):
    def test_sql_guard_accepts_reads_and_rejects_mutations(self) -> None:
        for query in ("SELECT 1", "SHOW transaction_read_only", "WITH x AS (SELECT 1) SELECT * FROM x"):
            MODULE.ReadOnlyPreflight._assert_read_only_sql(query)

        for query in (
            "INSERT INTO users DEFAULT VALUES",
            "UPDATE users SET name = 'x'",
            "DELETE FROM users",
            "CREATE TABLE unsafe(id int)",
            "DROP TABLE users",
            "ALTER TABLE users ADD COLUMN unsafe int",
            "WITH removed AS (DELETE FROM users RETURNING id) SELECT * FROM removed",
        ):
            with self.subTest(query=query):
                with self.assertRaises(RuntimeError):
                    MODULE.ReadOnlyPreflight._assert_read_only_sql(query)

    def test_script_uses_read_only_transaction_and_unconditional_rollback(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("connection.transaction(readonly=True)", source)
        self.assertIn("await transaction.rollback()", source)
        self.assertNotIn("await transaction.commit()", source)
        self.assertNotIn("from app.", source)
        self.assertNotIn("import app.", source)

    def test_environment_descriptor_does_not_expose_connection_secrets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    (
                        "POSTGRES_SERVER=127.0.0.1",
                        "POSTGRES_PORT=6543",
                        "POSTGRES_USER=sensitive-user",
                        "POSTGRES_PASSWORD=sensitive-password",
                        "POSTGRES_DB=sensitive-database",
                    )
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _kwargs, descriptor = MODULE._connection_kwargs(env_path)

        rendered = json.dumps(descriptor)
        self.assertEqual(descriptor["descriptor"], "local development PostgreSQL")
        self.assertNotIn("sensitive-user", rendered)
        self.assertNotIn("sensitive-password", rendered)
        self.assertNotIn("sensitive-database", rendered)

    def test_repository_head_is_resolved_without_running_migrations(self) -> None:
        self.assertEqual(
            MODULE._repository_heads(),
            ["20260828_0002_s3_4_admin_audit_hardening"],
        )


if __name__ == "__main__":
    unittest.main()
