
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent))

from app.core.config import settings
from app.db.session import engine
from sqlalchemy import text
from app.models.all_models import Base, User, Tender

async def run_diagnostics():
    print(f"--- DIAGNOSTICS START ---")
    print(f"DB URI: {settings.SQLALCHEMY_DATABASE_URI}")
    
    try:
        async with engine.connect() as conn:
            # Check connection
            await conn.execute(text("SELECT 1"))
            print("Database connection: SUCCESS")
            
            # Check tables
            for table in ["users", "tenders", "proposals"]:
                try:
                    res = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = res.scalar()
                    print(f"Table '{table}': EXISTS (Count: {count})")
                except Exception as e:
                    print(f"Table '{table}': ERROR or MISSING ({e})")
                    
    except Exception as e:
        print(f"Database connection: FAILED ({e})")
    
    print(f"--- DIAGNOSTICS END ---")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
