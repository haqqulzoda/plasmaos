import asyncio
import uuid
from sqlalchemy import text
from app.db.session import engine

async def force_verify(code: str):
    async with engine.begin() as conn:
        print(f"--- STARTING SIMULATION FOR CODE: {code} ---")
        
        # 1. CHECK IF USER ALREADY EXISTS (by telegram_id)
        result = await conn.execute(
            text("SELECT id, organization_id FROM users WHERE telegram_id = :tg_id"),
            {"tg_id": 123456789}
        )
        existing_user = result.fetchone()
        
        if existing_user:
            # Reuse existing user
            user_id = existing_user[0]
            org_id = existing_user[1]
            print(f"--- REUSING EXISTING USER: {user_id} ---")
        else:
            # 2. CREATE NEW ORGANIZATION AND USER
            org_id = uuid.uuid4()
            user_id = uuid.uuid4()
            
            print(f"--- CREATING DUMMY ORGANIZATION: {org_id} ---")
            await conn.execute(
                text("""
                    INSERT INTO organizations (id, name, tier, settings, created_at, updated_at) 
                    VALUES (:id, :name, 'FREE', '{}', NOW(), NOW())
                """),
                {"id": org_id, "name": "Test_Organization"}
            )
            
            print(f"--- CREATING DUMMY USER: {user_id} ---")
            await conn.execute(
                text("""
                    INSERT INTO users (id, telegram_id, full_name, organization_id, role, created_at, updated_at) 
                    VALUES (:id, :tg_id, :name, :org_id, 'OWNER', NOW(), NOW())
                """),
                {"id": user_id, "tg_id": 123456789, "name": "Test_User", "org_id": org_id}
            )
        
        # 3. LINK THE SESSION TO THE USER
        print(f"--- VERIFYING SESSION ---")
        result = await conn.execute(
            text("""
                UPDATE auth_sessions 
                SET status = 'VERIFIED', user_id = :user_id 
                WHERE code = :code
            """),
            {"user_id": user_id, "code": code}
        )
        
        if result.rowcount == 0:
            print(f"--- WARNING: No session found with code {code}. Run /auth/init first! ---")
        else:
            print("--- SUCCESS: SESSION VERIFIED & LINKED ---")

if __name__ == "__main__":
    # Ensure this code matches what you sent to /auth/init
    asyncio.run(force_verify("9999"))