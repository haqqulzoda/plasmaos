"""Closeout regressions for S4 admin activity and document availability."""

from __future__ import annotations

import unittest

from sqlalchemy.exc import SQLAlchemyError

try:
    from app.api.endpoints import admin as admin_endpoints
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        admin_endpoints = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


class _MissingOptionalTableSession:
    def __init__(self) -> None:
        self.rolled_back = False

    async def execute(self, _query):
        raise SQLAlchemyError("relation readiness_documents does not exist")

    async def rollback(self) -> None:
        self.rolled_back = True


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class AdminActivityCloseoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_metric_missing_table_degrades_to_zero(self) -> None:
        assert admin_endpoints is not None

        session = _MissingOptionalTableSession()
        count = await admin_endpoints._count_optional_model_rows(
            session,
            admin_endpoints.ReadinessDocument,
        )

        self.assertEqual(count, 0)
        self.assertTrue(session.rolled_back)


if __name__ == "__main__":
    unittest.main()
