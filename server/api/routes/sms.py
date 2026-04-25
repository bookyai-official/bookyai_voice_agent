"""
SMS Channel Routes — Twilio SMS incoming webhook and outbound API.

Incoming: Receives SMS via Twilio webhook, gets AI response, replies via Twilio REST.
Outbound: Django calls this API to send an AI-initiated SMS to a phone number.

Conversations are identified by phone_number and stored in Chat/Message tables.
"""

import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from models.business import BusinessConfiguration
from services.chat_service import get_or_create_chat, get_agent_response, ChatServiceError
from api.dependencies import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sms", tags=["SMS"])


@router.post("/incoming/{agent_id}")
async def handle_incoming_sms(request: Request, agent_id: int):
    """
    Twilio SMS webhook. Receives an incoming SMS, generates an AI response,
    and sends the reply back via Twilio REST API.

    Conversations are tracked by phone_number in the Chat table.
    """
    form_data = await request.form()
    from_number = form_data.get("From", "")
    to_number   = form_data.get("To", "")
    body        = form_data.get("Body", "").strip()
    message_sid = form_data.get("MessageSid", "unknown")

    logger.info(
        "[SMS] Incoming from %s to %s (Agent %d): %s",
        from_number, to_number, agent_id, body[:100],
    )

    if not body:
        logger.warning("[SMS] Empty message body — ignoring.")
        return Response(content="<Response/>", media_type="application/xml")

    # ── 1. Fetch Agent + Business Config ──────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AIAgent, BusinessConfiguration)
            .outerjoin(
                BusinessConfiguration,
                AIAgent.business_id == BusinessConfiguration.business_id,
            )
            .options(selectinload(AIAgent.tools))
            .where(AIAgent.id == agent_id)
        )
        row = result.first()

    if not row:
        logger.error("[SMS] Agent %d not found.", agent_id)
        return Response(content="<Response/>", media_type="application/xml")

    agent, biz_config = row

    if not agent.active:
        logger.warning("[SMS] Agent %d is inactive.", agent_id)
        return Response(content="<Response/>", media_type="application/xml")

    if not agent.business_id:
        logger.error("[SMS] Agent %d has no business_id.", agent_id)
        return Response(content="<Response/>", media_type="application/xml")

    # ── 2. Check Twilio credentials ───────────────────────────────────────
    twilio_sid   = biz_config.twilio_sid if biz_config else None
    twilio_token = biz_config.twilio_auth_token if biz_config else None
    reply_from   = agent.phone_number or (biz_config.twilio_phone_number if biz_config else None)

    if not twilio_sid or not twilio_token or not reply_from:
        logger.error("[SMS] Missing Twilio credentials for Agent %d.", agent_id)
        return Response(content="<Response/>", media_type="application/xml")

    # ── 3. Get or create Chat by phone_number ─────────────────────────────
    try:
        chat = await get_or_create_chat(
            business_id=agent.business_id,
            phone_number=from_number,
        )
    except ChatServiceError as e:
        logger.error("[SMS] Failed to get/create chat: %s", e)
        return Response(content="<Response/>", media_type="application/xml")

    # ── 4. Get AI response ────────────────────────────────────────────────
    try:
        chat_response = await get_agent_response(
            agent=agent,
            user_message=body,
            chat_id=chat.id,
            channel="sms",
        )
    except ChatServiceError as e:
        logger.error("[SMS] ChatService error for Agent %d: %s", agent_id, e)
        return Response(content="<Response/>", media_type="application/xml")

    # ── 5. Send reply via Twilio REST API ─────────────────────────────────
    try:
        from twilio.rest import Client
        client = Client(twilio_sid, twilio_token)
        client.messages.create(
            body=chat_response.content,
            from_=reply_from,
            to=from_number,
        )
        logger.info("[SMS] Reply sent to %s (Agent %d): %s", from_number, agent_id, chat_response.content[:100])
    except Exception as e:
        logger.error("[SMS] Failed to send Twilio reply: %s", e)

    # Return empty TwiML — we already sent via REST
    return Response(content="<Response/>", media_type="application/xml")


# ── Outbound SMS ──────────────────────────────────────────────────────────────

class OutboundSMSRequest(BaseModel):
    to_number: str
    agent_id: int
    message: str
    lead_info: Optional[str] = None


@router.post("/outbound", dependencies=[Depends(verify_token)])
async def send_outbound_sms(payload: OutboundSMSRequest):
    """
    Send an AI-powered outbound SMS. Called by Django.

    Creates/finds a Chat by phone_number, generates AI response with context,
    and sends via Twilio.

    Request:
        {
            "to_number": "+1234567890",
            "agent_id": 1,
            "message": "Reach out to this lead about their appointment tomorrow",
            "lead_info": "Name: John, Service: Haircut, Time: 3pm"
        }

    Response:
        {
            "status": "sent",
            "content": "Hi John! ...",
            "message_sid": "SM...",
            "chat_id": 42
        }
    """
    # ── 1. Fetch Agent + Business Config ──────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AIAgent, BusinessConfiguration)
            .outerjoin(
                BusinessConfiguration,
                AIAgent.business_id == BusinessConfiguration.business_id,
            )
            .options(selectinload(AIAgent.tools))
            .where(AIAgent.id == payload.agent_id)
        )
        row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent, biz_config = row

    if not agent.active:
        raise HTTPException(status_code=403, detail="Agent is inactive")

    if not agent.business_id:
        raise HTTPException(status_code=400, detail="Agent has no business configured")

    # ── 2. Check Twilio credentials ───────────────────────────────────────
    twilio_sid   = biz_config.twilio_sid if biz_config else None
    twilio_token = biz_config.twilio_auth_token if biz_config else None
    from_number  = agent.phone_number or (biz_config.twilio_phone_number if biz_config else None)

    if not twilio_sid or not twilio_token or not from_number:
        raise HTTPException(
            status_code=400,
            detail="Twilio credentials or phone number missing for this agent/business.",
        )

    # ── 3. Get or create Chat by phone_number ─────────────────────────────
    try:
        chat = await get_or_create_chat(
            business_id=agent.business_id,
            phone_number=payload.to_number,
        )
    except ChatServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── 4. Build the prompt for the AI ────────────────────────────────────
    user_prompt = payload.message
    if payload.lead_info:
        user_prompt += f"\n\nLead Information:\n{payload.lead_info}"

    try:
        chat_response = await get_agent_response(
            agent=agent,
            user_message=user_prompt,
            chat_id=chat.id,
            channel="sms_outbound",
        )
    except ChatServiceError as e:
        logger.error("[SMS OUTBOUND] ChatService error for Agent %d: %s", payload.agent_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    # ── 5. Send via Twilio ────────────────────────────────────────────────
    try:
        from twilio.rest import Client
        client = Client(twilio_sid, twilio_token)
        twilio_message = client.messages.create(
            body=chat_response.content,
            from_=from_number,
            to=payload.to_number,
        )
        logger.info(
            "[SMS OUTBOUND] Sent to %s (Agent %d, SID %s): %s",
            payload.to_number, payload.agent_id,
            twilio_message.sid, chat_response.content[:100],
        )
        return {
            "status": "sent",
            "content": chat_response.content,
            "message_sid": twilio_message.sid,
            "chat_id": chat_response.chat_id,
        }
    except Exception as e:
        logger.error("[SMS OUTBOUND] Failed to send via Twilio: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to send SMS: {str(e)}")
