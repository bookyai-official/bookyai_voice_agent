import json
import logging
import asyncio
import math
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.config import settings
from models.agent import AIAgent
from models.call import CallRecord
from models.system import SystemSetting
from services.openai_realtime import OpenAIRealtimeClient
from services.openai_summary import generate_call_summary
from services.usage_service import UsageService
from agents.factory import AgentFactory

from services.voice_service import VoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

@router.websocket("/stream/{agent_id}")
async def twilio_media_stream(
    websocket: WebSocket, 
    agent_id: int, 
    lead_info: str = Query(None), 
    direction: str = Query("inbound")
):
    """
    Bidirectional stream between Twilio and OpenAI Realtime API.
    Uses unified VoiceAgent and VoiceService.
    """
    await websocket.accept()
    logger.info(f"[STREAM] New connection for Agent {agent_id} (Direction: {direction})")

    # 1. Fetch Config via Service
    agent_config, biz_config = await VoiceService.get_session_config(agent_id)
    if not agent_config or not agent_config.active:
        logger.warning("[STREAM] Agent not found or inactive. Closing.")
        await websocket.close()
        return

    # 2. Check Usage via Service
    remaining_seconds = await VoiceService.check_usage_limit(agent_config.business_id)
    if remaining_seconds <= 0:
        logger.warning(f"[STREAM] Business {agent_config.business_id} has 0 minutes remaining. Rejecting.")
        await websocket.close()
        return

    # 3. Initialize Agent
    voice_agent = await AgentFactory.create_voice_agent(
        agent_id=agent_id,
        openai_api_key=settings.OPENAI_API_KEY
    )
    
    if "outbound" in direction.lower() and lead_info:
        voice_agent.base_prompt_text += f"\n\nSPECIAL INSTRUCTIONS (Lead Information):\n{lead_info}"

    # 4. Initialize Realtime Client
    openai_client = OpenAIRealtimeClient(
        agent=voice_agent,
        channel="twilio"
    )
    
    stream_sid = None
    twilio_call_sid = None
    connection_start_time = asyncio.get_event_loop().time()
    
    agent_max_seconds = (agent_config.max_call_duration_minutes or 10) * 60
    max_duration_seconds = min(agent_max_seconds, remaining_seconds)

    try:
        await openai_client.connect()
        logger.info("[STREAM] Connected to OpenAI Realtime.")

        # Greeting logic
        if agent_config.greeting_message:
            await openai_client.send_event({
                "type": "response.create",
                "response": {
                    "instructions": f"Start by saying exactly: {agent_config.greeting_message}"
                }
            })
        else:
            await openai_client.send_event({"type": "response.create"})

        openai_listener_task = None

        while True:
            # Duration Check
            if (asyncio.get_event_loop().time() - connection_start_time) > max_duration_seconds:
                logger.warning("[STREAM] Duration limit reached.")
                break

            if openai_listener_task and openai_listener_task.done():
                break

            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "start":
                stream_sid = data["start"]["streamSid"]
                twilio_call_sid = data["start"].get("callSid")
                
                # Update tools with real Twilio client
                from twilio.rest import Client as TwilioClient
                if biz_config and biz_config.twilio_sid:
                    twilio_client = TwilioClient(biz_config.twilio_sid, biz_config.twilio_auth_token)
                    from agents.tools import get_tools
                    voice_agent.tools = get_tools(agent_config, twilio_client, twilio_call_sid)

                # Initialize CallRecord
                if twilio_call_sid:
                    await VoiceService.create_call_record(
                        agent_id=agent_id,
                        call_sid=twilio_call_sid,
                        from_number=data["start"].get("customParameters", {}).get("From", "unknown"),
                        to_number=data["start"].get("customParameters", {}).get("To", "agent"),
                        call_type=direction,
                        call_mode="voice"
                    )

                openai_listener_task = asyncio.create_task(
                    openai_client.listen(websocket, stream_sid, twilio_call_sid)
                )

            elif event_type == "media":
                await openai_client.send_audio(data["media"]["payload"])

            elif event_type == "stop":
                break

    except Exception as e:
        logger.exception(f"[STREAM] WebSocket error: {e}")
    finally:
        call_end_time = asyncio.get_event_loop().time()
        await asyncio.sleep(1.0) 
        
        transcript = openai_client.get_transcript()
        usage = openai_client.get_usage()
        await openai_client.close()
            
        if 'openai_listener_task' in locals() and openai_listener_task:
            openai_listener_task.cancel()

        if twilio_call_sid:
            duration_seconds = int(call_end_time - connection_start_time)
            await VoiceService.finalize_call(
                call_sid=twilio_call_sid,
                duration_seconds=duration_seconds,
                transcript=transcript,
                usage=usage,
                business_id=agent_config.business_id
            )

