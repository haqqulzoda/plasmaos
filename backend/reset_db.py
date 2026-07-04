import asyncio
from sqlalchemy import text
from app.db.session import engine
from app.models.all_models import Base

async def reset_models():
    async with engine.begin() as conn:
        print("--- DROPPING ALL TABLES WITH CASCADE ---")
        # Drop all tables with CASCADE to handle dependencies
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        
        print("--- CREATING NEW TABLES ---")
        await conn.run_sync(Base.metadata.create_all)
        print("--- RESET COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(reset_models())