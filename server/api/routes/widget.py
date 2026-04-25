"""
Widget Channel Route — REST API for web chat widget.

Receives JSON messages from the frontend widget,
uses ChatService for AI response with DB-backed conversation history.
Conversations are identified by session_key (unique per user).
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from services.chat_service import get_or_create_chat, get_agent_response, ChatServiceError

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

    Every request must include a `session_key` to identify the conversation.
    The frontend generates a unique session_key per user/tab.

    Request:
        POST /api/widget/1
        {
            "message": "Hello, I need to book an appointment",
            "session_key": "usr_abc123_tab1"
        }

    Response:
        {
            "content": "Sure! I can help you book an appointment.",
            "chat_id": 42,
            "session_key": "usr_abc123_tab1"
        }
    """
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if not payload.session_key.strip():
        raise HTTPException(status_code=400, detail="session_key is required")

    # ── 1. Fetch Agent ────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AIAgent)
            .options(selectinload(AIAgent.tools))
            .where(AIAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.active:
        raise HTTPException(status_code=403, detail="Agent is inactive")

    if not agent.business_id:
        raise HTTPException(status_code=400, detail="Agent has no business configured")

    # ── 2. Get or create Chat session ─────────────────────────────────────
    try:
        chat = await get_or_create_chat(
            business_id=agent.business_id,
            session_key=payload.session_key.strip(),
        )
    except ChatServiceError as e:
        logger.error("[WIDGET] Failed to get/create chat: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # ── 3. Get AI response ────────────────────────────────────────────────
    try:
        chat_response = await get_agent_response(
            agent=agent,
            user_message=payload.message.strip(),
            chat_id=chat.id,
            channel="widget",
        )
    except ChatServiceError as e:
        logger.error("[WIDGET] ChatService error for Agent %d: %s", agent_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    return WidgetMessageResponse(
        content=chat_response.content,
        chat_id=chat_response.chat_id,
        session_key=payload.session_key,
    )
