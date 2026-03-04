from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError

from app.db.session import get_db
from app.models.company import Certification, CompanyProfile, FinancialHistory, License

try:
    from psycopg2.errors import UndefinedTable as PsycopgUndefinedTable
except Exception:  # pragma: no cover - psycopg2 may not be installed for asyncpg deployments
    PsycopgUndefinedTable = None


MODELS_TO_VERIFY = (
    CompanyProfile,
    Certification,
    License,
    FinancialHistory,
)


def _is_undefined_table_error(exc: BaseException) -> bool:
    if PsycopgUndefinedTable is not None and isinstance(exc, PsycopgUndefinedTable):
        return True

    if isinstance(exc, ProgrammingError):
        orig: Any = getattr(exc, "orig", None)
        if orig is None:
            return False

        if PsycopgUndefinedTable is not None and isinstance(orig, PsycopgUndefinedTable):
            return True

        orig_name = orig.__class__.__name__.lower()
        orig_msg = str(orig).lower()
        return (
            "undefinedtable" in orig_name
            or "undefined table" in orig_msg
            or "does not exist" in orig_msg
        )

    return False


async def _count_rows(session: Any, model: Any) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def main() -> None:
    db_gen = get_db()
    session = await anext(db_gen)

    try:
        for model in MODELS_TO_VERIFY:
            table_name = model.__tablename__
            try:
                row_count = await _count_rows(session, model)
                print(f"SUCCESS: table '{table_name}' exists (rows={row_count}).")
            except ProgrammingError as exc:
                if _is_undefined_table_error(exc):
                    print(
                        f"FATAL: required table '{table_name}' is missing (UndefinedTable). "
                        "Company Vault migration is not applied."
                    )
                    raise SystemExit(1) from exc
                raise
            except Exception as exc:
                if _is_undefined_table_error(exc):
                    print(
                        f"FATAL: required table '{table_name}' is missing (UndefinedTable). "
                        "Company Vault migration is not applied."
                    )
                    raise SystemExit(1) from exc
                raise
    finally:
        await db_gen.aclose()


if __name__ == "__main__":
    asyncio.run(main())
