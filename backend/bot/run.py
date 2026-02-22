"""
Plasma AI - Telegram Bot Entry Point

Run with: python -m bot.run
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import settings
from app.models import audit as audit_models  # noqa: F401
from bot.handlers import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and run the bot."""
    logger.info("--- STARTING PLASMA AI BOT ---")
    
    # Create bot with default properties
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    
    # Create dispatcher and register handlers
    dp = Dispatcher()
    dp.include_router(router)
    
    # Start polling
    logger.info("--- BOT IS NOW POLLING ---")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
