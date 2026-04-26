import json
import logging
import asyncio
import time
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import uuid
from models.call import CallRecord
from core.database import AsyncSessionLocal
from models.agent import AIAgent
from core.config import settings
from services.external_tools import execute_tool
from services.openai_summary import generate_call_summary
from models.system import SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

# Separator for readable log blocks
_SEP = "─" * 60


def _log_section(title: str, body: str = ""):
    """Emit a clearly separated log block."""
    lines = [f"\n{_SEP}", f"  {title}", _SEP]
    if body:
        lines.append(body)
    logger.info("\n".join(lines))


async def _get_agent_and_config(agent_id: int):
    """Fetch AIAgent and its Business configuration."""
    from models.business import BusinessConfiguration
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AIAgent, BusinessConfiguration)
            .outerjoin(BusinessConfiguration, AIAgent.business_id == BusinessConfiguration.business_id)
            .options(selectinload(AIAgent.tools))
            .where(AIAgent.id == agent_id)
        )
        return result.first()


@router.websocket("/webcall/{agent_id}")
async def web_call_stream(websocket: WebSocket, agent_id: int):
    """
    Browser-based bidirectional WebSocket for real-time agent testing.
    Accepts PCM16 audio from the browser (24kHz) and streams PCM16 audio back.
    """
    await websocket.accept()

    row = await _get_agent_and_config(agent_id)
    if not row:
        logger.warning(f"[WEB CALL] Agent {agent_id} not found — rejecting connection.")
        await websocket.send_json({"type": "error", "message": "Agent not found."})
        await websocket.close()
        return
    
    agent_config, biz_config = row
    if not agent_config.active:
        logger.warning(f"[WEB CALL] Agent {agent_id} inactive — rejecting connection.")
        await websocket.send_json({"type": "error", "message": "Agent inactive."})
        await websocket.close()
        return

    tool_names = [t.name for t in agent_config.tools]
    # Generate a unique SID for the web call
    web_call_sid = f"wc_{uuid.uuid4().hex[:16]}"
    
    # Fetch SystemSetting
    async with AsyncSessionLocal() as db_session:
        system_setting = await db_session.execute(select(SystemSetting))
        system_setting = system_setting.scalar_one_or_none()
        current_realtime_model = system_setting.realtime_llm_model if system_setting and system_setting.realtime_llm_model else "gpt-realtime-2025-08-28"

    _log_section(
        f"WEB CALL STARTED — Agent '{agent_config.name}' (id={agent_id})",
        f"  SID       : {web_call_sid}\n"
        f"  Voice     : {agent_config.voice or 'alloy'}\n"
        f"  Tools     : {', '.join(tool_names) if tool_names else 'None'}\n"
        f"  Model     : {current_realtime_model}"
    )

    # Create initial CallRecord
    async with AsyncSessionLocal() as db:
        new_call = CallRecord(
            agent_id=agent_id,
            call_sid=web_call_sid,
            status="in-progress",
            from_number="browser",
            to_number="agent",
            call_type="outbound",
            call_mode="web"
        )
        db.add(new_call)
        await db.commit()

    # Build tool config for the session
    formatted_tools = []
    tool_configs = {}
    for t in agent_config.tools:
        formatted_tools.append({
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.json_schema
        })
        tool_configs[t.name] = {
            "type": t.tool_type or "webhook",
            "url": t.url,
            "target": t.tool_target,
            "method": t.method,
            "timeout_seconds": t.timeout_seconds
        }
        logger.debug(f"[WEB CALL] Tool registered: {t.name} (type={t.tool_type})")

    openai_ws = None
    openai_listener_task = None
    session_start = time.monotonic()
    audio_chunks_sent = 0

    try:
        url = f"wss://api.openai.com/v1/realtime?model={current_realtime_model}"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        logger.info(f"[WEB CALL] Connecting to OpenAI Realtime (Agent {agent_id}) using model {current_realtime_model}...")
        openai_ws = await websockets.connect(
            url, 
            additional_headers=headers,
            open_timeout=20  # Increased timeout for handshake
        )
        logger.info(f"[WEB CALL] Connected to OpenAI Realtime successfully.")

        # Session config
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": f"YOU MUST ONLY SPEAK IN ENGLISH. DO NOT USE ANY OTHER LANGUAGE. {agent_config.system_prompt}",
                "voice": agent_config.voice or "alloy",
                "temperature": agent_config.temperature if agent_config.temperature is not None else 0.8,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": agent_config.vad_threshold if agent_config.vad_threshold is not None else 0.9,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": agent_config.silence_duration_ms if agent_config.silence_duration_ms is not None else 1000
                },
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "tools": formatted_tools
            }
        }
        await openai_ws.send(json.dumps(session_update))
        logger.info(f"[WEB CALL] Session configured (temp={agent_config.temperature}, vad={agent_config.vad_threshold}, silence={agent_config.silence_duration_ms}ms)")

        # Handle Greeting Message if provided
        if agent_config.greeting_message:
            logger.info(f"[WEB CALL] Sending greeting message: {agent_config.greeting_message}")
            await openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": agent_config.greeting_message
                        }
                    ]
                }
            }))

        # Make the agent speak first
        await openai_ws.send(json.dumps({"type": "response.create"}))
        logger.info(f"[WEB CALL] Initial response.create sent.")

        await websocket.send_json({"type": "status", "status": "connected"})

        transcript = []
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
        # Spawn background task: OpenAI → Browser relay
        openai_listener_task = asyncio.create_task(
            _relay_openai_to_browser(
                openai_ws, 
                websocket, 
                tool_configs, 
                agent_id, 
                transcript, 
                usage,
                twilio_sid=biz_config.twilio_sid if biz_config else None,
                twilio_token=biz_config.twilio_auth_token if biz_config else None
            )
        )

        # Browser → OpenAI relay loop
        async def _relay_browser_to_openai():
            nonlocal audio_chunks_sent
            try:
                while True:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "audio":
                        audio_chunks_sent += 1
                        if audio_chunks_sent == 1:
                            logger.info(f"[WEB CALL] Receiving microphone audio from browser (Agent {agent_id})")
                        await openai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": data["audio"]
                        }))
                    elif msg_type == "stop":
                        logger.info(f"[WEB CALL] Stop requested by browser (Agent {agent_id})")
                        break
            except WebSocketDisconnect:
                # Handled by finally or outer catch
                pass
            except Exception as e:
                logger.error(f"[WEB CALL] Browser relay error: {e}")

        browser_listener_task = asyncio.create_task(_relay_browser_to_openai())

        # Wait for either the OpenAI relay (agent ends call) or Browser relay (user stops) to finish
        done, pending = await asyncio.wait(
            [openai_listener_task, browser_listener_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # If agent terminated via tool, notify browser to reset UI
        if openai_listener_task in done:
            try:
                await websocket.send_json({"type": "session_end"})
            except:
                pass
        else:
            # If browser stopped first, wait a bit for any pending OpenAI events (like final transcription)
            await asyncio.sleep(2.0)

        # Cleanup pending task
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info(f"[WEB CALL] Browser disconnected (Agent {agent_id})")
    except Exception as e:
        logger.error(f"[WEB CALL] Unexpected error (Agent {agent_id}): {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": "An unexpected error occurred."})
        except Exception:
            pass
    finally:
        if openai_listener_task:
            openai_listener_task.cancel()
        if openai_ws:
            await openai_ws.close()

        elapsed = time.monotonic() - session_start
        _log_section(
            f"WEB CALL ENDED — Agent '{agent_config.name}' (id={agent_id})",
            f"  Duration         : {elapsed:.1f}s\n"
            f"  Audio chunks sent: {audio_chunks_sent}"
        )

        # Save Final Transcript, Usage, and Summary
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CallRecord).where(CallRecord.call_sid == web_call_sid))
            call_rec = result.scalar_one_or_none()
            if call_rec:
                # Generate Summary via OpenAI
                summary = await generate_call_summary(transcript)
                
                call_rec.status = "completed"
                call_rec.transcript = transcript
                call_rec.call_summary = summary
                call_rec.input_tokens = usage.get("input_tokens", 0)
                call_rec.output_tokens = usage.get("output_tokens", 0)
                call_rec.total_tokens = usage.get("total_tokens", 0)
                call_rec.cached_tokens = usage.get("cached_tokens", 0)
                await db.commit()
                logger.info(f"[WEB CALL] Saved transcript & summary to CallRecord {web_call_sid}")


async def _relay_openai_to_browser(
    openai_ws, 
    browser_ws, 
    tool_configs: dict, 
    agent_id: int, 
    transcript: list, 
    usage: dict,
    twilio_sid: str = None,
    twilio_token: str = None
):
    """Listen to OpenAI Realtime events and forward them to the browser."""
    try:
        async for raw_message in openai_ws:
            event = json.loads(raw_message)
            event_type = event.get("type")

            # Audio delta — stream raw PCM16 to browser
            if event_type == "response.audio.delta":
                delta = event.get("delta")
                if delta:
                    await browser_ws.send_json({"type": "audio", "audio": delta})

            # Audio stream complete
            elif event_type == "response.audio.done":
                await browser_ws.send_json({"type": "audio_done"})

            # User transcription (Whisper)
            elif event_type.startswith("conversation.item.input_audio_transcription."):
                if event_type == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "").strip()
                    if text:
                        logger.info(f"[WEB CALL] [Agent {agent_id}] USER  : {text}")
                        transcript.append({"role": "user", "text": text})
                        await browser_ws.send_json({"type": "transcript", "role": "user", "text": text})
                    else:
                        logger.debug(f"[WEB CALL] [Agent {agent_id}] Empty user transcript received.")
                elif event_type == "conversation.item.input_audio_transcription.failed":
                    error = event.get("error", {})
                    logger.error(f"[WEB CALL] [Agent {agent_id}] User transcription failed: {error}")

            # Agent transcription
            elif event_type == "response.audio_transcript.done":
                text = event.get("transcript", "").strip()
                if text:
                    logger.info(f"[WEB CALL] [Agent {agent_id}] AGENT : {text}")
                    transcript.append({"role": "assistant", "text": text})
                    await browser_ws.send_json({"type": "transcript", "role": "assistant", "text": text})

            # Tool call
            elif event_type == "response.function_call_arguments.done":
                call_id = event.get("call_id")
                tool_name = event.get("name")
                arguments = event.get("arguments", "{}")

                _log_section(
                    f"TOOL CALL — '{tool_name}' (Agent {agent_id})",
                    f"  Call ID  : {call_id}\n"
                    f"  Arguments: {arguments}"
                )

                await browser_ws.send_json({"type": "tool_call", "tool": tool_name})

                tool_config = tool_configs.get(tool_name, {})
                t_type = tool_config.get("type", "webhook")
                tool_url = tool_config.get("url")
                tool_target = tool_config.get("target")
                method = tool_config.get("method", "POST")
                timeout = tool_config.get("timeout_seconds", 5)

                result_str = "{}"
                should_close = False

                if t_type == "call_end":
                    logger.info(f"[TOOL] Call End triggered by tool '{tool_name}'")
                    result_str = json.dumps({"status": "success", "message": "Call ended"})
                    await browser_ws.send_json({"type": "transcript", "role": "system", "text": "🛑 Call ended by agent"})
                    should_close = True

                elif t_type == "call_transfer":
                    logger.info(f"[TOOL] Call Transfer triggered to {tool_target}")
                    result_str = json.dumps({"status": "success", "message": f"Transferring to {tool_target}"})
                    await browser_ws.send_json({"type": "transcript", "role": "system", "text": f"📞 Transferring call to {tool_target}..."})
                    should_close = True

                elif not tool_url:
                    logger.error(f"[TOOL] No URL configured for tool '{tool_name}' — skipping execution")
                    result_str = json.dumps({"error": f"No URL configured for tool '{tool_name}'"})
                else:
                    logger.info(f"[TOOL] Executing: {method} {tool_url} (timeout={timeout}s)")
                    t_start = time.monotonic()
                    result_str = await execute_tool(tool_url, method, timeout, arguments)
                    elapsed_ms = (time.monotonic() - t_start) * 1000
                    logger.info(
                        f"[TOOL] '{tool_name}' completed in {elapsed_ms:.0f}ms\n"
                        f"       Result: {result_str[:300]}{'...' if len(result_str) > 300 else ''}"
                    )

                await openai_ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result_str
                    }
                }))
                await openai_ws.send(json.dumps({"type": "response.create"}))
                logger.info(f"[TOOL] Tool result sent back to OpenAI for call_id={call_id}")
                
                if should_close:
                    logger.info(f"[WEB CALL] Terminating session due to tool action.")
                    break

            # VAD events
            elif event_type == "input_audio_buffer.speech_started":
                logger.info(f"[WEB CALL] [Agent {agent_id}] VAD: Speech started — cancelling current response.")
                # Cancel any in-progress response from OpenAI to prevent overlapping audio
                await openai_ws.send(json.dumps({"type": "response.cancel"}))
                await browser_ws.send_json({"type": "speech_start"})

            elif event_type == "input_audio_buffer.speech_stopped":
                logger.info(f"[WEB CALL] [Agent {agent_id}] VAD: Speech stopped — processing...")
                await browser_ws.send_json({"type": "speech_stop"})

            # Session errors from OpenAI
            elif event_type == "error":
                err_msg = event.get("error", {})
                logger.error(f"[WEB CALL] OpenAI error event (Agent {agent_id}): {err_msg}")

            # Usage Tracking
            elif event_type == "response.done":
                res_usage = event.get("response", {}).get("usage")
                if res_usage:
                    usage["input_tokens"] = res_usage.get("input_tokens", 0)
                    usage["output_tokens"] = res_usage.get("output_tokens", 0)
                    usage["total_tokens"] = res_usage.get("total_tokens", 0)
                    usage["cached_tokens"] = res_usage.get("input_token_details", {}).get("cached_tokens", 0)
                    logger.info(f"[WEB CALL] Usage Update: Total={usage['total_tokens']}, Cached={usage['cached_tokens']}")

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[WEB CALL] OpenAI connection closed (Agent {agent_id})")
    except Exception as e:
        logger.error(f"[WEB CALL] Relay error (Agent {agent_id}): {e}", exc_info=True)
