"""
Add company profile columns to company_profiles table.

Run this once: python add_vault_profile_columns.py
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine


async def add_vault_profile_columns():
    """Add root company profile columns to company_profiles table."""
    async with engine.begin() as conn:
        print("Adding company profile columns to company_profiles table...")

        columns = [
            ("company_name", "VARCHAR(255)"),
            ("director_name", "VARCHAR(255)"),
            ("address", "TEXT"),
            ("phone_contact", "VARCHAR(50)"),
            ("bank_name", "VARCHAR(255)"),
            ("mfo", "VARCHAR(10)"),
            ("account_number", "VARCHAR(30)"),
            ("inn", "VARCHAR(15)"),
        ]

        for col_name, col_type in columns:
            try:
                await conn.execute(
                    text(f"ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
                )
                print(f"  ✓ Added column: {col_name}")
            except Exception as e:
                print(f"  ✗ Column {col_name}: {e}")

        print("\nMigration complete!")


if __name__ == "__main__":
    asyncio.run(add_vault_profile_columns())
