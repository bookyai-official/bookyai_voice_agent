import json
import logging
import asyncio
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.config import settings
from models.agent import AIAgent
from services.openai_realtime import OpenAIRealtimeClient
from agents.factory import AgentFactory
from services.voice_service import VoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

@router.websocket("/webcall/{agent_id}")
async def web_call_stream(websocket: WebSocket, agent_id: int):
    """
    Browser-based bidirectional WebSocket for real-time agent testing.
    Uses unified VoiceAgent and VoiceService.
    """
    await websocket.accept()
    logger.info(f"[WEB CALL] New connection for Agent {agent_id}")

    # 1. Fetch Config via Service
    agent_config, biz_config = await VoiceService.get_session_config(agent_id)
    if not agent_config or not agent_config.active:
        logger.warning(f"[WEB CALL] Agent {agent_id} not found or inactive.")
        await websocket.send_json({"type": "error", "message": "Agent not found or inactive."})
        await websocket.close()
        return
    
    # 2. Check Usage via Service
    remaining_seconds = await VoiceService.check_usage_limit(agent_config.business_id)
    if remaining_seconds <= 0:
        logger.warning(f"[WEB CALL] Business {agent_config.business_id} has 0 minutes remaining.")
        await websocket.send_json({"type": "error", "message": "Call minutes limit reached."})
        await websocket.close()
        return

    # 3. Initialize Agent & Client
    web_call_sid = f"wc_{uuid.uuid4().hex[:16]}"
    voice_agent = await AgentFactory.create_voice_agent(
        agent_id=agent_id,
        openai_api_key=settings.OPENAI_API_KEY
    )

    openai_client = OpenAIRealtimeClient(
        agent=voice_agent,
        channel="browser"
    )

    # 4. Initialize CallRecord
    await VoiceService.create_call_record(
        agent_id=agent_id,
        call_sid=web_call_sid,
        from_number="browser",
        to_number="agent",
        call_type="outbound",
        call_mode="web"
    )

    connection_start_time = asyncio.get_event_loop().time()
    call_end_time = connection_start_time  # Default in case of early failure
    agent_max_seconds = (agent_config.max_call_duration_minutes or 10) * 60
    max_duration_seconds = min(agent_max_seconds, remaining_seconds)

    try:
        await openai_client.connect()
        logger.info("[WEB CALL] Connected to OpenAI Realtime.")

        # Greeting
        if agent_config.greeting_message:
            await openai_client.send_event({
                "type": "response.create",
                "response": {
                    "instructions": f"Start by saying exactly: {agent_config.greeting_message}"
                }
            })
        else:
            await openai_client.send_event({"type": "response.create"})

        await websocket.send_json({"type": "status", "status": "connected"})

        # Spawn OpenAI -> Browser relay (unified in client.listen)
        openai_listener_task = asyncio.create_task(
            openai_client.listen(websocket, call_sid=web_call_sid)
        )

        # Browser -> OpenAI relay loop (transport layer)
        async def _relay_browser_to_openai():
            try:
                while True:
                    if (asyncio.get_event_loop().time() - connection_start_time) > max_duration_seconds:
                        break
                    
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "audio":
                        await openai_client.send_audio(data["audio"])
                    elif msg_type == "stop":
                        break
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.error(f"[WEB CALL] Browser relay error: {e}")

        browser_listener_task = asyncio.create_task(_relay_browser_to_openai())

        done, pending = await asyncio.wait(
            [openai_listener_task, browser_listener_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        if openai_listener_task in done:
            await websocket.send_json({"type": "session_end"})
        else:
            await asyncio.sleep(1.5)

        call_end_time = asyncio.get_event_loop().time()
        for task in pending:
            task.cancel()

    except Exception as e:
        logger.error(f"[WEB CALL] Error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": "An unexpected error occurred."})
        except:
            pass
    finally:
        transcript = openai_client.get_transcript()
        usage = openai_client.get_usage()
        await openai_client.close()

        duration_seconds = int(call_end_time - connection_start_time)
        await VoiceService.finalize_call(
            call_sid=web_call_sid,
            duration_seconds=duration_seconds,
            transcript=transcript,
            usage=usage,
            business_id=agent_config.business_id
        )
        logger.info(f"[WEB CALL] Session ended for {web_call_sid}")
