import logging
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import Response, JSONResponse
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.config import settings
from models.agent import AIAgent
from models.integration import FacebookIntegration
from services.chat_service import get_or_create_chat, save_message
from services.langchain_service import get_chat_response
from services.facebook_service import FacebookService
from services.usage_service import UsageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/facebook", tags=["Facebook"])

@router.get("/webhook")
async def verify_facebook_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Facebook Webhook Verification.
    Used when setting up the webhook in the Facebook App Dashboard.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.FB_VERIFY_TOKEN:
        logger.info("[FB WEBHOOK] Verification successful.")
        return Response(content=hub_challenge)
    
    logger.warning("[FB WEBHOOK] Verification failed. Mode: %s, Token: %s", hub_mode, hub_verify_token)
    return Response(content="Verification failed", status_code=403)

@router.post("/webhook")
async def handle_facebook_message(request: Request):
    """
    Processes incoming messages from Facebook Messenger and Instagram.
    """
    try:
        payload = await request.json()
        print(f"\n[WEBHOOK] Received payload: {payload}")
    except Exception as e:
        logger.error("[FB WEBHOOK] Failed to parse JSON payload: %s", str(e))
        return Response(content="Invalid payload", status_code=400)
    
    obj_type = payload.get("object")
    print(f"[WEBHOOK] Object type: {obj_type}")

    if obj_type not in ["page", "instagram"]:
        print(f"[WEBHOOK] Unsupported object type: {obj_type}")
        return JSONResponse(content={"status": f"unsupported object type: {obj_type}"}, status_code=200)

    for entry in payload.get("entry", []):
        entry_id = entry.get("id")
        print(f"[WEBHOOK] Processing entry: {entry_id}")

        # --- Handle Facebook Messenger ---
        if obj_type == "page":
            for messaging_event in entry.get("messaging", []):
                if "message" in messaging_event and not messaging_event["message"].get("is_echo"):
                    sender_id = messaging_event["sender"]["id"]
                    message_text = messaging_event["message"].get("text")
                    if not message_text: continue
                    
                    print(f"[FB WEBHOOK] Messenger message from {sender_id}: {message_text[:50]}")
                    await process_webhook_message(
                        platform="facebook",
                        business_platform_id=entry_id,
                        sender_id=sender_id,
                        message_text=message_text
                    )

        # --- Handle Instagram ---
        elif obj_type == "instagram":
            for messaging_event in entry.get("messaging", []):
                if "message" in messaging_event and not messaging_event["message"].get("is_echo"):
                    sender_id = messaging_event["sender"]["id"]
                    message_text = messaging_event["message"].get("text")
                    if not message_text: continue
                    
                    print(f"[IG WEBHOOK] Instagram message from {sender_id}: {message_text[:50]}")
                    await process_webhook_message(
                        platform="instagram",
                        business_platform_id=entry_id,
                        sender_id=sender_id,
                        message_text=message_text
                    )


    return Response(content="EVENT_RECEIVED")

async def process_webhook_message(platform: str, business_platform_id: str, sender_id: str, message_text: str):
    """
    Unified processing logic for all platforms.
    """
    print(f"[PROCESS] Platform: {platform}, ID: {business_platform_id}, Sender: {sender_id}")
    
    async with AsyncSessionLocal() as session:
        # 1. Lookup FacebookIntegration
        if platform == "facebook":
            filter_stmt = (FacebookIntegration.page_id == business_platform_id)
        elif platform == "instagram":
            filter_stmt = (FacebookIntegration.instagram_business_account_id == business_platform_id)
        else:
            return

        result = await session.execute(
            select(FacebookIntegration).where(filter_stmt, FacebookIntegration.is_active == True)
        )
        integration = result.scalar_one_or_none()
    
        if not integration:
            print(f"[PROCESS] No active integration found for {platform} ID: {business_platform_id}")
            return

        # 2. Fetch Agent
        agent_result = await session.execute(
            select(AIAgent).where(
                AIAgent.business_id == integration.business_id,
                AIAgent.active == True
            )
        )
        agent = agent_result.scalar_one_or_none()
    
        if not agent:
            print(f"[PROCESS] No active agent found for business: {integration.business_id}")
            return

        # 3. Get or create Chat
        chat_params = {"business_id": integration.business_id}
        if platform == "facebook": chat_params["fb_psid"] = sender_id
        elif platform == "instagram": chat_params["ig_sid"] = sender_id
        
        chat = await get_or_create_chat(**chat_params)

        # 4. Check if AI is enabled
        if not chat.enable_ai:
            print(f"[PROCESS] AI disabled for chat {chat.id}. Saving message.")
            await save_message(chat.id, "user", message_text)
            return

        # 5. Check Usage Limit (proxying as 'sms')
        has_usage = await UsageService.has_remaining_usage(session, agent.business_id, "sms")
        if not has_usage:
            print(f"[PROCESS] Business {agent.business_id} exceeded usage limit.")
            await save_message(chat.id, "user", message_text)
            await save_message(chat.id, "error", "AI response skipped: Usage limit exceeded.")
            return

        # 6. Get AI Response
        try:
            response_text = await get_chat_response(
                agent_id=agent.id,
                chat_id=chat.id,
                user_message=message_text,
                channel="text"
            )
        except Exception as e:
            print(f"[PROCESS] AI Error: {str(e)}")
            return

        # 7. Send Response back via appropriate Service
        success = False
        if platform == "facebook":
            success = await FacebookService.send_message(
                page_access_token=integration.page_access_token,
                recipient_id=sender_id,
                text=response_text
            )
        elif platform == "instagram":
            success = await FacebookService.send_instagram_message(
                page_access_token=integration.page_access_token,
                recipient_id=sender_id,
                text=response_text
            )

        if success:
            await UsageService.update_usage(session, agent.business_id, "sms", 1)
            print(f"[PROCESS] Successfully replied via {platform}")
                
    return Response(content="EVENT_RECEIVED")
