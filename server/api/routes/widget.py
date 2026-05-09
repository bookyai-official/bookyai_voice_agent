"""
Widget Channel Route — REST API for web chat widget.

Receives JSON messages from the frontend widget,
uses LangChain SMSAgent for AI response with DB-backed conversation history.
Conversations are identified by session_key (unique per user).
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from services.chat_service import get_or_create_chat, ChatServiceError
from services.usage_service import UsageService
from services.langchain_service import get_chat_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget", tags=["Widget"])

class WidgetMessageRequest(BaseModel):
    message: str
    session_key: str

class WidgetMessageResponse(BaseModel):
    content: str
    chat_id: int
    session_key: str

@router.post("/{agent_id}", response_model=WidgetMessageResponse)
async def widget_chat(agent_id: int, payload: WidgetMessageRequest):
    """
    Public-facing widget chat endpoint with DB-backed conversation history.
    """
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if not payload.session_key.strip():
        raise HTTPException(status_code=400, detail="session_key is required")

    # ── 1. Fetch Agent ────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AIAgent)
            .where(AIAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.active:
        raise HTTPException(status_code=403, detail="Agent is inactive")

    # ── 2. Get or create Chat session ─────────────────────────────────────
    try:
        chat = await get_or_create_chat(
            business_id=agent.business_id,
            session_key=payload.session_key.strip(),
        )
    except ChatServiceError as e:
        logger.error("[WIDGET] Failed to get/create chat: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # ── 2.5 Check if AI is enabled for this chat ──────────────────────────
    if not chat.enable_ai:
        from services.chat_service import save_message
        await save_message(chat.id, "user", payload.message.strip())
        return WidgetMessageResponse(
            content="AI response is currently disabled for this conversation.",
            chat_id=chat.id,
            session_key=payload.session_key,
        )

    # ── 2.7 Check Usage Limit ─────────────────────────────────────────────
    async with AsyncSessionLocal() as db_session:
        has_usage = await UsageService.has_remaining_usage(db_session, agent.business_id, "sms")
        if not has_usage:
            from services.chat_service import save_message
            await save_message(chat.id, "user", payload.message.strip())
            await save_message(
                chat.id,
                "error",
                "AI response skipped: Business has exceeded its usage limit."
            )
            return WidgetMessageResponse(
                content="AI assistance is currently unavailable due to usage limits.",
                chat_id=chat.id,
                session_key=payload.session_key,
            )

    # ── 3. Get AI response (LangChain) ────────────────────────────────────
    try:
        response_text = await get_chat_response(
            agent_id=agent.id,
            chat_id=chat.id,
            user_message=payload.message.strip(),
            channel="text"
        )
    except Exception as e:
        logger.error("[WIDGET] LangChain error: %s", e)
        raise HTTPException(status_code=502, detail="Error generating AI response.")

    return WidgetMessageResponse(
        content=response_text,
        chat_id=chat.id,
        session_key=payload.session_key,
    )
