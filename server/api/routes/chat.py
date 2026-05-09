"""
Test Chat Route — Authenticated endpoint for testing agents via text.

Stateless — does NOT save to Chat/Message tables.
Uses LangChain BaseAgent for execution with an ephemeral thread_id.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import logging
import uuid

from core.database import get_db
from core.config import settings
from models.agent import AIAgent
from api.dependencies import verify_token
from services.usage_service import UsageService
from agents.base import BaseAgent
from agents.tools import get_tools
from langchain_core.messages import HumanMessage, AIMessage

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger(__name__)

@router.post("/{agent_id}", dependencies=[Depends(verify_token)])
async def agent_chat_test(
    agent_id: int,
    payload:  dict,
    db:       AsyncSession = Depends(get_db),
):
    """
    Stateless text chat for testing agents. No DB records created.
    """
    # ── 1. Fetch agent ────────────────────────────────────────────────────
    db_result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools))
        .where(AIAgent.id == agent_id)
    )
    agent_cfg: AIAgent | None = db_result.scalar_one_or_none()
    if not agent_cfg:
        raise HTTPException(status_code=404, detail="Agent not found")

    # ── 1.5 Check Usage Limit ─────────────────────────────────────────────
    has_usage = await UsageService.has_remaining_usage(db, agent_cfg.business_id, "sms")
    if not has_usage:
        raise HTTPException(status_code=403, detail="Business has exceeded usage limit.")

    # ── 2. Validate request ───────────────────────────────────────────────
    messages: list[dict] = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # ── 3. Get or Create Chat Session ─────────────────────────────────────
    # We use a stable session_key for testing this agent to persist history
    session_key = payload.get("session_key", f"test_widget_{agent_id}")
    from services.chat_service import get_or_create_chat
    chat = await get_or_create_chat(
        business_id=agent_cfg.business_id,
        session_key=session_key
    )

    # ── 4. Get AI Response via Unified Service ────────────────────────────
    try:
        current_input = messages[-1].get("content")
        from services.langchain_service import get_chat_response
        response_text = await get_chat_response(
            agent_id=agent_id,
            chat_id=chat.id,
            user_message=current_input
        )
        
        # ── 5. Update Usage ─────────────────────────────────────────────────
        await UsageService.update_usage(db, agent_cfg.business_id, "sms", 1)
        
        return {
            "role":        "assistant",
            "content":     response_text,
            "response_id": "langchain_resp",
            "chat_id":     chat.id,
            "session_key": session_key
        }

    except Exception as exc:
        logger.error("[TEST CHAT] LangChain error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))