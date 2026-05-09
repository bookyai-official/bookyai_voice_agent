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

    # ── 3. Initialize Agent (Stateless) ───────────────────────────────────
    try:
        tools = get_tools(agent_cfg)
        test_agent = BaseAgent(
            model_name="gpt-4o-mini",
            openai_api_key=settings.OPENAI_API_KEY,
            system_prompt=agent_cfg.system_prompt,
            tools=tools,
            temperature=agent_cfg.temperature or 0.7
        )
        
        # Hydrate the checkpointer with provided history
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        
        lc_messages = []
        history = messages[:-1]
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
        
        if lc_messages:
            await test_agent.checkpointer.aupdate_state(config, {"messages": lc_messages})

        # ── 4. Run Agent ──────────────────────────────────────────────────────
        current_input = messages[-1].get("content")
        response_text = await test_agent.run(current_input, thread_id)
        
        # ── 5. Update Usage ─────────────────────────────────────────────────
        await UsageService.update_usage(db, agent_cfg.business_id, "sms", 1)
        
        return {
            "role":        "assistant",
            "content":     response_text,
            "response_id": "langchain_resp",
            "usage":       {}
        }

    except Exception as exc:
        logger.error("[TEST CHAT] LangChain error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))