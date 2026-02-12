"""
Plasma AI - Telegram Bot Handlers

Handles /start command and 4-digit code verification for Traffic Light auth.
"""

import logging
import uuid
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy import select, text

logger = logging.getLogger(__name__)

from app.db.session import AsyncSessionLocal
from app.models.all_models import User, AuthSession, AuthSessionStatus

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """
    Handle /start command.
    
    Upserts user into database and sends welcome message.
    """
    tg_user = message.from_user
    if not tg_user:
        return
    
    async with AsyncSessionLocal() as session:
        # Check if user exists
        result = await session.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update existing user's name and username
            user.full_name = tg_user.full_name or tg_user.username or "Unknown"
            user.username = tg_user.username
            await session.commit()
        else:
            # Create new user (simplified - no organization)
            user_id = uuid.uuid4()
            
            await session.execute(
                text("""
                    INSERT INTO users (id, telegram_id, username, full_name, subscription_tier, is_admin, created_at)
                    VALUES (:id, :tg_id, :username, :name, 'SCOUT', false, NOW())
                """),
                {
                    "id": user_id,
                    "tg_id": tg_user.id,
                    "username": tg_user.username,
                    "name": tg_user.full_name or tg_user.username or "Unknown",
                }
            )
            await session.commit()
    
    await message.answer(
        "🚀 <b>Welcome to Plasma AI - Tender Officer!</b>\n\n"
        "I'm your autonomous assistant for Uzbekistan public tenders.\n\n"
        "Please send me your <b>4-digit login code</b> from the web app.",
        parse_mode="HTML"
    )


@router.message(F.text.regexp(r"^\d{4}$"))
async def handle_code(message: Message) -> None:
    """
    Handle 4-digit code messages.
    
    Verifies the auth session and links it to the user.
    """
    code = message.text
    tg_user = message.from_user
    if not tg_user or not code:
        return
    
    logger.info(f"[AUTH] Processing code: {code} from tg_user: {tg_user.id}")
    
    async with AsyncSessionLocal() as session:
        # Get the user
        user_result = await session.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        logger.info(f"[AUTH] User lookup for tg_id {tg_user.id}: {user.id if user else 'NOT FOUND'}")
        
        if not user:
            await message.answer(
                "⚠️ Please send /start first to register.",
                parse_mode="HTML"
            )
            return
        
        # Find pending session with this code
        session_result = await session.execute(
            select(AuthSession).where(
                AuthSession.code == code,
                AuthSession.status == AuthSessionStatus.PENDING
            )
        )
        auth_session = session_result.scalar_one_or_none()
        
        if auth_session:
            # Verify the session
            auth_session.status = AuthSessionStatus.VERIFIED
            auth_session.user_id = user.id
            await session.commit()
            
            await message.answer(
                "✅ <b>Login Verified!</b>\n\n"
                "Check your browser to continue.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ <b>Invalid or expired code.</b>\n\n"
                "Please request a new code from the web app.",
                parse_mode="HTML"
            )
