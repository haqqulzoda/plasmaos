"""
Plasma AI - Telegram Notification Service

Sends real-time alerts for new tenders to users with Telegram connected.
Uses python-telegram-bot for async message sending with InlineKeyboard buttons.
"""

import asyncio
import logging
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Singleton bot instance
_bot: Optional[Bot] = None


def get_bot() -> Bot:
    """Get or create the Telegram bot instance."""
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    return _bot


async def send_tender_alert(
    chat_id: int,
    tender_id: str,
    title: str,
    budget: float,
    currency: str = "UZS",
    region: Optional[str] = None,
) -> bool:
    """
    Send a new tender alert to a Telegram user with interactive buttons.
    
    Args:
        chat_id: User's Telegram chat ID
        tender_id: UUID of the tender in our database
        title: Tender title
        budget: Tender budget amount
        currency: Currency code (default UZS)
        region: Region/location (optional)
    
    Returns:
        True if message sent successfully, False otherwise.
    """
    bot = get_bot()
    
    # Format budget with thousands separators
    if budget >= 1_000_000_000:
        budget_str = f"{budget / 1_000_000_000:.1f}B {currency}"
    elif budget >= 1_000_000:
        budget_str = f"{budget / 1_000_000:.0f}M {currency}"
    else:
        budget_str = f"{budget:,.0f} {currency}"
    
    # Build message with Markdown formatting
    message = (
        "🚀 *NEW TENDER FOUND*\n\n"
        f"🏗 {title}\n\n"
        f"💰 *Budget:* {budget_str}\n"
    )
    
    if region:
        message += f"📍 *Region:* {region}\n"
    
    # Inline keyboard with action buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⚡ Generate Draft Proposal",
            callback_data=f"gen_proposal:{tender_id}",
        )],
        [InlineKeyboardButton(
            "🔗 Open in PlasmaOS",
            url=f"http://localhost:3000/dashboard/tenders",
        )],
    ])
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
        logger.info(f"Telegram alert sent to {chat_id} for tender {tender_id}")
        return True
    except TelegramError as e:
        logger.error(f"Failed to send Telegram alert to {chat_id}: {e}")
        return False


async def broadcast_new_tender(
    tender_id: str,
    title: str,
    budget: float,
    currency: str,
    region: Optional[str],
    user_chat_ids: list[int],
) -> int:
    """
    Broadcast a new tender alert to multiple users.
    
    Args:
        tender_id: UUID of the tender
        title: Tender title
        budget: Budget amount
        currency: Currency code
        region: Region name
        user_chat_ids: List of Telegram chat IDs to notify
    
    Returns:
        Number of successfully sent notifications.
    """
    if not user_chat_ids:
        logger.info("No users with Telegram connected, skipping broadcast")
        return 0
    
    logger.info(f"Broadcasting tender {tender_id[:8]}... to {len(user_chat_ids)} users")
    
    # Send to all users concurrently
    tasks = [
        send_tender_alert(chat_id, tender_id, title, budget, currency, region)
        for chat_id in user_chat_ids
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success_count = sum(1 for r in results if r is True)
    
    logger.info(f"Broadcast complete: {success_count}/{len(user_chat_ids)} sent")
    return success_count
