"""
Plasma AI — Fire Drill: Telegram Bot Alert Test

Tests the "Speed Demon" phase by sending a real Telegram notification
with the [⚡ Generate Draft Proposal] inline button.

Usage (inside Docker):
    docker exec plasma_backend python debug_bot_trigger.py

Usage (local, if env vars are set):
    python debug_bot_trigger.py
"""

import asyncio
import sys

from sqlalchemy import select, desc

from app.db.session import AsyncSessionLocal
from app.models.all_models import Tender, User
from app.core.telegram import send_tender_alert


# ── HARDCODED FALLBACK ──────────────────────────────────────────────
# If no user with telegram_id exists in the DB, paste YOUR chat ID here.
# To find your chat ID: message @userinfobot on Telegram.
FALLBACK_CHAT_ID: int | None = None  # e.g. 123456789
# ────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("\n🔥 FIRE DRILL — Telegram Bot Alert Test")
    print("=" * 50)

    async with AsyncSessionLocal() as session:
        # ── Step 1: Fetch the latest tender ──
        print("\n📡 Step 1: Fetching latest tender from DB...")
        result = await session.execute(
            select(Tender).order_by(desc(Tender.created_at)).limit(1)
        )
        tender = result.scalar_one_or_none()

        if tender is None:
            print("❌ No tenders found in the database!")
            print("   Run the scraper or seed_tenders.py first.")
            sys.exit(1)

        print(f"   ✅ Found tender: {tender.title[:80]}")
        print(f"   💰 Budget: {tender.budget:,.0f} {tender.currency}")
        print(f"   📍 Region: {tender.region or 'N/A'}")
        print(f"   🆔 ID: {tender.id}")

        # ── Step 2: Find a user with a telegram_id ──
        print("\n👤 Step 2: Looking for a user with telegram_id...")
        result = await session.execute(
            select(User).where(User.telegram_id.isnot(None)).limit(1)
        )
        user = result.scalar_one_or_none()

        if user and user.telegram_id:
            chat_id = user.telegram_id
            print(f"   ✅ Found user: {user.full_name} (telegram_id={chat_id})")
        elif FALLBACK_CHAT_ID:
            chat_id = FALLBACK_CHAT_ID
            print(f"   ⚠️  No users with telegram_id found.")
            print(f"   📌 Using FALLBACK_CHAT_ID: {chat_id}")
        else:
            print("   ❌ No users with telegram_id in DB and no FALLBACK_CHAT_ID set.")
            print("\n   HOW TO FIX:")
            print("   Option A: Start the Telegram bot, send /start, authenticate.")
            print("   Option B: Set FALLBACK_CHAT_ID in this script.")
            print("             Message @userinfobot on Telegram to get your chat ID.")
            sys.exit(1)

        # ── Step 3: Send the alert ──
        print(f"\n🚀 Step 3: Sending Telegram alert to chat_id={chat_id}...")
        success = await send_tender_alert(
            chat_id=chat_id,
            tender_id=str(tender.id),
            title=tender.title,
            budget=tender.budget,
            currency=tender.currency,
            region=tender.region,
        )

        if success:
            print("\n" + "=" * 50)
            print("✅ FIRE DRILL PASSED!")
            print("   Check your Telegram — you should see the alert")
            print("   with the [⚡ Generate Draft Proposal] button.")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("❌ FIRE DRILL FAILED!")
            print("   send_tender_alert returned False.")
            print("   Check the logs above for TelegramError details.")
            print("=" * 50)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
