"""
Plasma AI - Telegram Bot Handlers

Handles /start command, 4-digit code verification for Traffic Light auth,
and one-click proposal generation via InlineKeyboard callbacks.
"""

import logging
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from sqlalchemy import select, text

logger = logging.getLogger(__name__)

from app.db.session import AsyncSessionLocal
from app.models.all_models import User, AuthSession, AuthSessionStatus, Tender, Proposal, ProposalStatus

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


# =============================================================================
# One-Click Proposal Generation Callback
# =============================================================================

@router.callback_query(F.data.startswith("gen_proposal:"))
async def handle_generate_proposal(callback: CallbackQuery) -> None:
    """
    Handle the '⚡ Generate Draft Proposal' button press.
    
    1. Looks up the user and tender
    2. Runs AI analysis on the tender
    3. Generates a PDF Commercial Proposal
    4. Sends the PDF back to the user in chat
    """
    tg_user = callback.from_user
    if not tg_user:
        await callback.answer("❌ User not found")
        return
    
    # Parse tender_id from callback data
    tender_id_str = callback.data.split(":", 1)[1] if callback.data else ""
    if not tender_id_str:
        await callback.answer("❌ Invalid tender ID")
        return
    
    # Acknowledge immediately
    await callback.answer("⏳ Generating proposal...")
    
    # Send a status message
    status_msg = await callback.message.answer(
        "⏳ <b>Generating your Commercial Proposal...</b>\n\n"
        "🤖 AI is analyzing the tender...\n"
        "This usually takes 10-30 seconds.",
        parse_mode="HTML",
    )
    
    try:
        async with AsyncSessionLocal() as session:
            # 1. Find the user
            user_result = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                await status_msg.edit_text(
                    "❌ <b>Please /start the bot first!</b>",
                    parse_mode="HTML",
                )
                return
            
            # 2. Find the tender
            try:
                tender_uuid = uuid.UUID(tender_id_str)
            except ValueError:
                await status_msg.edit_text(
                    "❌ <b>Invalid tender reference.</b>",
                    parse_mode="HTML",
                )
                return
            
            tender_result = await session.execute(
                select(Tender).where(Tender.id == tender_uuid)
            )
            tender = tender_result.scalar_one_or_none()
            
            if not tender:
                await status_msg.edit_text(
                    "❌ <b>Tender not found.</b> It may have been removed.",
                    parse_mode="HTML",
                )
                return
            
            # 3. Find or create a Proposal for this tender
            proposal_result = await session.execute(
                select(Proposal).where(
                    Proposal.user_id == user.id,
                    Proposal.tender_id == tender.id,
                )
            )
            proposal = proposal_result.scalar_one_or_none()
            
            if not proposal:
                proposal = Proposal(
                    user_id=user.id,
                    tender_id=tender.id,
                    status=ProposalStatus.GENERATING,
                    structured_data={},
                )
                session.add(proposal)
                await session.commit()
                await session.refresh(proposal)
            
            # 4. Run AI analysis on tender title/description
            ai_summary = ""
            ai_items = []
            delivery_days = 30
            
            try:
                # Use tender title as context for quick analysis
                from app.core.ai import analyze_tender_text_async
                
                # Build company context
                company_context = {
                    "company_name": user.company_name or "",
                    "core_services": getattr(user, "core_services", "") or "",
                    "past_experience": getattr(user, "past_experience", "") or "",
                }
                
                analysis_text = (
                    f"Tender Title: {tender.title}\n"
                    f"Budget: {tender.budget} {tender.currency}\n"
                    f"Region: {tender.region or 'Not specified'}\n"
                    f"Category: {tender.category or 'General'}\n"
                )
                
                ai_result = await analyze_tender_text_async(
                    analysis_text, company_context
                )
                
                ai_summary = ai_result.get("summary", "")
                ai_items = ai_result.get("items", [])
                delivery_days = ai_result.get("delivery_days", 30)
                
                # Update proposal with AI data
                proposal.structured_data = {
                    "ai_summary": ai_summary,
                    "ai_items": ai_items,
                    "delivery_days": delivery_days,
                    "generated_via": "telegram_bot",
                }
                proposal.status = ProposalStatus.COMPLETED
                await session.commit()
                
            except Exception as e:
                logger.error(f"[BOT] AI analysis failed: {e}")
                ai_summary = f"Tender for: {tender.title}"
            
            # 5. Generate PDF
            await status_msg.edit_text(
                "📄 <b>Creating PDF document...</b>",
                parse_mode="HTML",
            )
            
            from app.core.pdf_generator import generate_quick_proposal_pdf
            
            pdf_bytes = generate_quick_proposal_pdf(
                company_name=user.company_name or "Your Company LLC",
                director_name=user.director_name or "Director",
                address=user.address or "",
                tender_title=tender.title,
                tender_budget=tender.budget,
                currency=tender.currency or "UZS",
                ai_summary=ai_summary,
                items=ai_items,
                delivery_days=delivery_days,
                inn=user.inn or "",
                bank_name=user.bank_name or "",
                mfo=user.mfo or "",
                account_number=user.account_number or "",
            )
            
            # 6. Send PDF to user
            safe_title = tender.title[:40].replace("/", "-").replace("\\", "-")
            filename = f"Proposal_{safe_title}.pdf"
            
            pdf_file = BufferedInputFile(pdf_bytes, filename=filename)
            
            await callback.message.answer_document(
                document=pdf_file,
                caption=(
                    f"✅ <b>Commercial Proposal Generated!</b>\n\n"
                    f"📋 {tender.title[:80]}\n"
                    f"💰 {tender.budget:,.0f} {tender.currency or 'UZS'}\n\n"
                    f"🏢 From: {user.company_name or 'Your Company'}"
                ),
                parse_mode="HTML",
            )
            
            # Delete the status message
            try:
                await status_msg.delete()
            except Exception:
                pass
            
            logger.info(
                f"[BOT] Proposal PDF sent to {tg_user.id} "
                f"for tender {tender_id_str[:8]}..."
            )
    
    except Exception as e:
        logger.error(f"[BOT] Proposal generation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        try:
            await status_msg.edit_text(
                f"❌ <b>Generation failed:</b> {str(e)[:100]}\n\n"
                "Please try again or use the web app.",
                parse_mode="HTML",
            )
        except Exception:
            pass
