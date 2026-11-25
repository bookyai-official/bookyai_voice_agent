from services.lifetime_runtime import LifetimeRuntime, RuntimeDenied
import math
import uuid
import json
import logging
import asyncio
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from contextlib import suppress
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.config import settings
from models.agent import AIAgent
from services.realtime_provider import RealtimeProviderError, create_realtime_client
from agents.factory import AgentFactory
from services.voice_service import VoiceService
from services.call_transcript import CallTranscriptWriter

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
    client_timezone = websocket.query_params.get('client_timezone') or None
    if client_timezone:
        try:
            if len(client_timezone) > 64:
                raise ValueError('Invalid client timezone')
            ZoneInfo(client_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            await websocket.send_json({'type': 'error', 'message': 'Invalid browser timezone metadata.'})
            await websocket.close(code=1008)
            return


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
    try:
        voice_agent = await AgentFactory.create_voice_agent(
            agent_id=agent_id,
            openai_api_key=settings.OPENAI_API_KEY,
            realtime_only=True,
            client_timezone=client_timezone,
        )
        realtime_client = create_realtime_client(agent=voice_agent, channel="browser")
    except RealtimeProviderError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        return

    lifetime_operation = None
    lifetime_units = 0
    if voice_agent.runtime_policy:
        lifetime_operation = f'voice:{uuid.uuid4().hex}'
        requested_minutes = min(10, agent_config.max_call_duration_minutes or 10)
        try:
            reserved = await LifetimeRuntime.reserve_context(agent_config.business_id, lifetime_operation,
                purpose='realtime', usage_type='minutes', units=requested_minutes, partial=True, feature='calling_agent')
        except RuntimeDenied as exc:
            await websocket.send_json({'type': 'error', 'message': str(exc)})
            await websocket.close(code=1008)
            return
        lifetime_units = reserved['reserved_units']
        try:
            voice_agent = await AgentFactory.create_voice_agent(agent_id=agent_id,
                openai_api_key=reserved['api_key'], realtime_only=True, client_timezone=client_timezone,
                runtime_policy={**voice_agent.runtime_policy, **reserved})
            realtime_client = create_realtime_client(agent=voice_agent, channel='browser')
        except Exception:
            await LifetimeRuntime.settle(agent_config.business_id, lifetime_operation, 0)
            await websocket.send_json({'type': 'error', 'message': 'Unable to prepare call.'})
            await websocket.close(code=1011)
            return
        remaining_seconds = min(remaining_seconds, lifetime_units * 60)

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

    transcript_writer = CallTranscriptWriter(web_call_sid)
    provider_listener_task = None
    browser_listener_task = None
    session_connected = False
    session_started_at = None
    call_failed = False
    try:
        await realtime_client.connect()
        logger.info("[WEB CALL] Connected to the selected realtime provider.")

        await realtime_client.start_conversation(agent_config.greeting_message)
        session_connected = True
        session_started_at = asyncio.get_event_loop().time()

        await websocket.send_json({"type": "status", "status": "connected"})

        # Spawn provider -> Browser relay (unified in client.listen)
        provider_listener_task = asyncio.create_task(
            realtime_client.listen(
                websocket, call_sid=web_call_sid, on_transcript=transcript_writer.submit,
            )
        )

        # Browser -> provider relay loop (transport layer)
        async def _relay_browser_to_provider():
            nonlocal call_failed
            try:
                while True:
                    if (asyncio.get_event_loop().time() - connection_start_time) > max_duration_seconds:
                        break
                    
                    try:
                        message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "audio":
                        await realtime_client.send_audio(data["audio"])
                    elif msg_type == "stop":
                        break
            except WebSocketDisconnect:
                pass
            except Exception:
                call_failed = True
                with suppress(WebSocketDisconnect, RuntimeError):
                    await websocket.send_json({
                        'type': 'error', 'message': 'Call audio could not be sent. Please start a new call.'
                    })

        browser_listener_task = asyncio.create_task(_relay_browser_to_provider())

        done, _ = await asyncio.wait(
            [provider_listener_task, browser_listener_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        if provider_listener_task in done:
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.send_json({"type": "session_end"})

    except Exception as e:
        call_failed = True
        logger.error('Web call failed; provider details withheld.' if lifetime_operation else f'[WEB CALL] Error: {e}', exc_info=not bool(lifetime_operation))
        try:
            message = str(e) if isinstance(e, RealtimeProviderError) else 'An unexpected error occurred.'
            await websocket.send_json({"type": "error", "message": message})
        except:
            pass
    finally:
        call_end_time = asyncio.get_event_loop().time()
        if browser_listener_task:
            browser_listener_task.cancel()
            await asyncio.gather(browser_listener_task, return_exceptions=True)
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
        if web_call_sid:
            # Start persistence before SDK/socket cleanup; a disconnect cannot cancel it.
            finalization_task = asyncio.create_task(VoiceService.finalize_call(
                call_sid=web_call_sid, duration_seconds=duration_seconds,
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
