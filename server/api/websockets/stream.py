from services.lifetime_runtime import LifetimeRuntime
import math
import uuid
import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from contextlib import suppress
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.config import settings
from models.agent import AIAgent
from models.call import CallRecord
from models.system import SystemSetting
from services.realtime_provider import RealtimeProviderError, create_realtime_client
from services.openai_summary import generate_call_summary
from services.usage_service import UsageService
from agents.factory import AgentFactory

from services.voice_service import VoiceService
from services.call_transcript import CallTranscriptWriter

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
    Bidirectional stream between Twilio and the selected realtime provider.
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

    # 3. Resolve the provider before reserving minutes or opening a session.
    try:
        voice_agent = await AgentFactory.create_voice_agent(
            agent_id=agent_id,
            openai_api_key=settings.OPENAI_API_KEY,
            realtime_only=True,
        )
        realtime_client = create_realtime_client(agent=voice_agent, channel="twilio")
    except RealtimeProviderError:
        await websocket.close(code=1011, reason="Configured voice provider is unavailable.")
        return
    
    if "outbound" in direction.lower() and lead_info:
        voice_agent.base_prompt_text += f"\n\nSPECIAL INSTRUCTIONS (Lead Information):\n{lead_info}"

    # 4. Initialize Realtime Client
    lifetime_operation = None
    lifetime_units = 0
    if voice_agent.runtime_policy:
        lifetime_operation = f'voice:{uuid.uuid4().hex}'
        requested_minutes = min(10, agent_config.max_call_duration_minutes or 10)
        lifetime_units = await LifetimeRuntime.reserve(agent_config.business_id, lifetime_operation, 'minutes', requested_minutes, partial=True)
        remaining_seconds = min(remaining_seconds, lifetime_units * 60)

    stream_sid = None
    twilio_call_sid = None
    connection_start_time = asyncio.get_event_loop().time()
    
    agent_max_seconds = (agent_config.max_call_duration_minutes or 10) * 60
    max_duration_seconds = min(agent_max_seconds, remaining_seconds)

    transcript_writer = None
    provider_listener_task = None
    session_connected = False
    session_started_at = None
    call_failed = False
    try:
        while True:
            # Duration Check
            if (asyncio.get_event_loop().time() - connection_start_time) > max_duration_seconds:
                logger.warning("[STREAM] Duration limit reached.")
                break

            if provider_listener_task and provider_listener_task.done():
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

                    transcript_writer = CallTranscriptWriter(twilio_call_sid)

                # Bind call-control tools before the provider receives its tool definitions.
                await realtime_client.connect()
                await realtime_client.start_conversation(agent_config.greeting_message)
                session_connected = True
                session_started_at = asyncio.get_event_loop().time()
                provider_listener_task = asyncio.create_task(
                    realtime_client.listen(
                        websocket, stream_sid, twilio_call_sid,
                        on_transcript=transcript_writer.submit if transcript_writer else None,
                    )
                )

            elif event_type == "media" and session_connected:
                await realtime_client.send_audio(data["media"]["payload"])

            elif event_type == "stop":
                break

    except Exception as e:
        call_failed = True
        logger.error('Voice stream failed; provider details withheld.' if lifetime_operation else f'[STREAM] WebSocket error: {e}', exc_info=not bool(lifetime_operation))
    finally:
        call_end_time = asyncio.get_event_loop().time()
        if provider_listener_task and not provider_listener_task.done():
            finish_input = getattr(realtime_client, 'finish_input', None)
            if finish_input:
                with suppress(Exception):
                    await asyncio.wait_for(finish_input(), timeout=3.5)
            else:
                await asyncio.sleep(1.0)
        if provider_listener_task:
            provider_listener_task.cancel()
            await asyncio.gather(provider_listener_task, return_exceptions=True)
        transcript = realtime_client.get_transcript()
        usage = realtime_client.get_usage()
        if transcript_writer:
            transcript_writer.submit(transcript, usage)
            with suppress(Exception):
                await transcript_writer.close()

        duration_seconds = int(call_end_time - session_started_at) if session_started_at else 0
        finalization_task = None
        if twilio_call_sid:
            # Start persistence before SDK/socket cleanup; a disconnect cannot cancel it.
            finalization_task = asyncio.create_task(VoiceService.finalize_call(
                call_sid=twilio_call_sid, duration_seconds=duration_seconds,
                transcript=transcript, usage=usage,
                business_id=agent_config.business_id, precharged=bool(lifetime_operation),
                failed=call_failed or not session_connected or getattr(realtime_client, 'failed', False),
            ))
        try:
            with suppress(Exception):
                await asyncio.wait_for(realtime_client.close(), timeout=5)
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.close()
            if lifetime_operation:
                try:
                    await LifetimeRuntime.settle(
                        agent_config.business_id, lifetime_operation,
                        min(lifetime_units, math.ceil(max(0, duration_seconds) / 60)),
                    )
                except Exception:
                    print('[VOICE] Unable to settle lifetime voice reservation; reserved usage retained.', flush=True)
        finally:
            if finalization_task:
                await asyncio.shield(finalization_task)
