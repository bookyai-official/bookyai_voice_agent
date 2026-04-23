import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from core.database import AsyncSessionLocal
from models.agent import VoiceAgent
from models.call import CallRecord
from services.openai_realtime import OpenAIRealtimeClient
from services.openai_summary import generate_call_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

async def get_agent_config(agent_id: int):
    """Fetch Agent configuration directly to avoid dependency injection complexities in WS."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(VoiceAgent).options(selectinload(VoiceAgent.tools)).where(VoiceAgent.id == agent_id)
        )
        return result.scalar_one_or_none()

@router.websocket("/stream/{agent_id}")
async def twilio_media_stream(websocket: WebSocket, agent_id: int):
    """
    Bidirectional stream between Twilio and OpenAI Realtime API.
    """
    await websocket.accept()
    logger.info(f"Accepted WebSocket connection for Agent {agent_id}")

    # 1. Load Agent Config
    agent_config = await get_agent_config(agent_id)
    if not agent_config or not agent_config.active:
        logger.warning("Agent not found or inactive. Closing connection.")
        await websocket.close()
        return

    # 2. Extract Tools 
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

    # 3. Initialize OpenAI Client
    # ... (rest of code)

    # 3. Initialize OpenAI Client
    openai_client = OpenAIRealtimeClient(
        system_prompt=agent_config.system_prompt,
        voice=agent_config.voice,
        tools=formatted_tools,
        tool_configs=tool_configs
    )
    
    stream_sid = None

    try:
        # Connect to OpenAI
        await openai_client.connect()
        logger.info("Connected to OpenAI Realtime.")

        # Create the listening task for OpenAI
        openai_listener_task = None

        # Listen to Twilio stream
        while True:
            # If the OpenAI listener finished (e.g. agent hung up), terminate Twilio loop
            if openai_listener_task and openai_listener_task.done():
                logger.info("[STREAM] OpenAI listener finished — terminating Twilio relay.")
                break

            try:
                # Use a small timeout to allow periodic task status checks
                message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                logger.info("Twilio disconnected.")
                break

            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "start":
                stream_sid = data["start"]["streamSid"]
                twilio_call_sid = data["start"].get("callSid")
                logger.info(f"Incoming stream started: {stream_sid} for Call {twilio_call_sid}")
                
                # Update DB status to in-progress
                if twilio_call_sid:
                    async with AsyncSessionLocal() as db:
                        res = await db.execute(select(CallRecord).where(CallRecord.call_sid == twilio_call_sid))
                        call_rec = res.scalar_one_or_none()
                        if call_rec:
                            call_rec.status = "in-progress"
                            await db.commit()

                # Now that we have stream_sid, spawn the OpenAI listening task
                openai_listener_task = asyncio.create_task(
                    openai_client.listen(websocket, stream_sid, twilio_call_sid)
                )

            elif event_type == "media":
                # Received audio frame from Twilio. Pass directly to OpenAI
                payload = data["media"]["payload"]
                await openai_client.send_audio(payload)

            elif event_type == "stop":
                logger.info("Stream stopped by Twilio.")
                break

    except WebSocketDisconnect:
        logger.info("Twilio disconnected.")
    except Exception as e:
        logger.error(f"WebSocket stream error: {e}")
    finally:
        # Give a small grace period for any pending transcriptions to arrive
        await asyncio.sleep(2.0)
        
        transcript = []
        if openai_client:
            transcript = openai_client.get_transcript()
            await openai_client.close()
            
        if 'openai_listener_task' in locals() and openai_listener_task:
            openai_listener_task.cancel()

        # Save Final Transcript, Usage, and Summary
        if 'twilio_call_sid' in locals() and twilio_call_sid:
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            if openai_client:
                usage = openai_client.get_usage()

            async with AsyncSessionLocal() as db:
                res = await db.execute(select(CallRecord).where(CallRecord.call_sid == twilio_call_sid))
                call_rec = res.scalar_one_or_none()
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
                    logger.info(f"[STREAM] Saved transcript & summary to CallRecord {twilio_call_sid}")
