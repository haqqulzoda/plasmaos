"""
Add company profile columns to users table.

Run this once to add the new columns for company settings.
"""
import asyncio
from app.db.session import engine

async def add_company_columns():
    """Add company profile columns to users table."""
    async with engine.begin() as conn:
        print("Adding company profile columns to users table...")
        
        # Add each column if it doesn't exist (PostgreSQL syntax)
        columns = [
            ("company_name", "VARCHAR(255)"),
            ("director_name", "VARCHAR(255)"),
            ("address", "VARCHAR(500)"),
            ("phone_contact", "VARCHAR(50)"),
            ("bank_name", "VARCHAR(255)"),
            ("mfo", "VARCHAR(10)"),
            ("account_number", "VARCHAR(30)"),
            ("inn", "VARCHAR(15)"),
        ]
        
        for col_name, col_type in columns:
            try:
                await conn.execute(
                    text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
                )
                print(f"  ✓ Added column: {col_name}")
            except Exception as e:
                print(f"  ✗ Column {col_name}: {e}")
        
        print("\nMigration complete!")

if __name__ == "__main__":
    from sqlalchemy import text
    asyncio.run(add_company_columns())
