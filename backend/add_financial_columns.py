"""
Add financial columns to proposals table.

Run this once to add the new columns for margin, VAT, and currency.
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def add_financial_columns():
    """Add financial columns to proposals table."""
    async with engine.begin() as conn:
        print("Adding financial columns to proposals table...")
        
        # Add each column if it doesn't exist (PostgreSQL syntax)
        columns = [
            ("margin_percent", "FLOAT DEFAULT 20.0 NOT NULL"),
            ("include_vat", "BOOLEAN DEFAULT TRUE NOT NULL"),
            ("currency", "VARCHAR(10) DEFAULT 'UZS' NOT NULL"),
        ]
        
        for col_name, col_type in columns:
            try:
                await conn.execute(
                    text(f"ALTER TABLE proposals ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
                )
                print(f"  ✓ Added column: {col_name}")
            except Exception as e:
                print(f"  ✗ Column {col_name}: {e}")
        
        print("\nMigration complete!")

if __name__ == "__main__":
    asyncio.run(add_financial_columns())
