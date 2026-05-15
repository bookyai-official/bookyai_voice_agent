"""
ChatService — Unified conversation session management.

Provides helpers to:
1. Find or create a Chat session (by phone_number or session_key)
2. Save user/assistant messages to the DB
"""

import logging
from sqlalchemy.future import select
from core.database import AsyncSessionLocal
from models.conversation import Chat, Message

logger = logging.getLogger(__name__)

class ChatServiceError(Exception):
    """Raised when the ChatService encounters a non-recoverable error."""
    pass

async def get_or_create_chat(
    business_id: int | str,
    phone_number: str | None = None,
    session_key: str | None = None,
    fb_psid: str | None = None,
    ig_sid: str | None = None,
    wa_id: str | None = None,
) -> Chat:
    """
    Find an existing Chat or create a new one.

    Lookup priority:
    - SMS/Voice channel: by business_id + phone_number
    - Widget channel: by business_id + session_key
    - Facebook Messenger: by business_id + fb_psid
    - Instagram: by business_id + ig_sid
    - WhatsApp: by business_id + wa_id
    """
    # Ensure business_id is a string to match PostgreSQL VARCHAR column
    business_id = str(business_id)

    async with AsyncSessionLocal() as db:

        query = select(Chat).where(Chat.business_id == business_id, Chat.is_active == True)

        if phone_number:
            query = query.where(Chat.phone_number == phone_number)
        elif session_key:
            query = query.where(Chat.session_key == session_key)
        elif fb_psid:
            query = query.where(Chat.fb_psid == fb_psid)
        elif ig_sid:
            query = query.where(Chat.ig_sid == ig_sid)
        elif wa_id:
            query = query.where(Chat.wa_id == wa_id)
        else:
            raise ChatServiceError("Either phone_number, session_key, fb_psid, ig_sid, or wa_id is required")

        result = await db.execute(query)
        chat = result.scalar_one_or_none()

        if chat:
            return chat

        # Create new chat
        chat = Chat(
            business_id=business_id,
            phone_number=phone_number,
            session_key=session_key,
            fb_psid=fb_psid,
            ig_sid=ig_sid,
            wa_id=wa_id,
        )
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
        logger.info(
            "[CHAT SERVICE] Created new Chat id=%d (business=%s, %s)",
            chat.id, business_id,
            f"phone={phone_number}" if phone_number else (
                f"fb_psid={fb_psid}" if fb_psid else (
                    f"ig_sid={ig_sid}" if ig_sid else (
                        f"wa_id={wa_id}" if wa_id else f"session={session_key}"
                    )
                )
            ),
        )
        return chat

async def save_message(chat_id: int, role: str, content: str) -> Message:
    """Save a message turn (user, assistant, tool_call, error) to the DB."""
    async with AsyncSessionLocal() as db:
        msg = Message(chat_id=chat_id, role=role, content=content)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg
