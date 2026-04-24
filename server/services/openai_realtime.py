import json
import logging
import asyncio
import websockets
from core.config import settings
from twilio.rest import Client as TwilioClient
from services.external_tools import execute_tool

logger = logging.getLogger(__name__)

# The exact model to use for Realtime. (Could also be gpt-4o-realtime-preview-2024-10-01)
REALTIME_MODEL = "gpt-realtime-2025-08-28"

class OpenAIRealtimeClient:
    def __init__(self, system_prompt: str, voice: str, tools: list, tool_configs: dict):
        self.system_prompt = system_prompt
        self.voice = voice or "alloy"
        self.tools = tools or []
        self.tool_configs = tool_configs or {}
        self.ws = None
        self.transcript_log = [] # To accumulate the conversation
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_tokens = 0
        self.url = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }

    async def connect(self):
        """Connect to OpenAI Realtime WebSocket."""
        self.ws = await websockets.connect(self.url, additional_headers=self.headers)
        await self._initialize_session()

    async def _initialize_session(self):
        """Send the initial session configuration."""
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": f"YOU MUST ONLY SPEAK IN ENGLISH. DO NOT USE ANY OTHER LANGUAGE. {self.system_prompt}",
                "voice": self.voice,
                "input_audio_format": "g711_ulaw",  # Same as Twilio
                "output_audio_format": "g711_ulaw", # Same as Twilio
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.8,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": 1000
                },
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "tools": self.tools
            }
        }
        await self.send_event(session_update)
        # Make the agent speak first
        await self.send_event({"type": "response.create"})
        logger.info("[OPENAI] Session initialized and response requested.")

    async def send_event(self, event: dict):
        """Send a JSON payload to OpenAI."""
        if self.ws:
            # logger.debug(f"Sending to OpenAI: {event['type']}")
            await self.ws.send(json.dumps(event))

    async def send_audio(self, base64_audio: str):
        """Send audio delta from Twilio straight into OpenAI."""
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64_audio
        }
        await self.send_event(event)

    async def close(self):
        """Close connection."""
        if self.ws:
            await self.ws.close()

    async def listen(self, twilio_ws, stream_sid, twilio_call_sid=None):
        """
        Listen to events from OpenAI and push media to Twilio.
        Also intercepts and processes function calls.
        """
        twilio_client = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            twilio_client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")
                
                # Log all non-media events for debugging
                logger.info(f"[OPENAI] Event: {event_type}")

                # Handle audio output (stream direct to Twilio)
                if event_type == "response.audio.delta":
                    base64_audio = event.get("delta")
                    if base64_audio:
                        twilio_media_event = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": base64_audio
                            }
                        }
                        await twilio_ws.send_json(twilio_media_event)

                # Need to handle interruptions (Clear buffer on Twilio)
                elif event_type == "input_audio_buffer.speech_started":
                    clear_event = {
                        "event": "clear",
                        "streamSid": stream_sid
                    }
                    await twilio_ws.send_json(clear_event)

                # Handle Function Call logic
                elif event_type == "response.function_call_arguments.done":
                    call_id = event.get("call_id")
                    tool_name = event.get("name")
                    arguments = event.get("arguments")
                    
                    # Get the specific configuration for this tool from DB structure
                    tool_config = self.tool_configs.get(tool_name, {})
                    t_type = tool_config.get("type", "webhook")
                    url = tool_config.get("url")
                    target = tool_config.get("target")
                    method = tool_config.get("method", "POST")
                    timeout = tool_config.get("timeout_seconds", 5)
                    
                    should_close = False
                    result_str = "{}"

                    if t_type == "call_end":
                        logger.info(f"[TOOL] Ending call {twilio_call_sid}")
                        if twilio_client and twilio_call_sid:
                            try:
                                # Wrap synchronous Twilio call in a thread to avoid blocking the async loop
                                await asyncio.to_thread(
                                    twilio_client.calls(twilio_call_sid).update, 
                                    status='completed'
                                )
                            except Exception as te:
                                logger.error(f"Twilio Hangup Error: {te}")
                        result_str = json.dumps({"status": "success", "message": "Call hung up"})
                        should_close = True

                    elif t_type == "call_transfer":
                        logger.info(f"[TOOL] Transferring call {twilio_call_sid} to {target}")
                        if twilio_client and twilio_call_sid and target:
                            try:
                                await asyncio.to_thread(
                                    twilio_client.calls(twilio_call_sid).update,
                                    twiml=f'<Response><Dial>{target}</Dial></Response>'
                                )
                            except Exception as te:
                                logger.error(f"Twilio Transfer Error: {te}")
                        result_str = json.dumps({"status": "success", "message": f"Transferred to {target}"})
                        should_close = True

                    elif url:
                        # Execute tool using dynamic database config
                        result_str = await execute_tool(url, method, timeout, arguments)
                    else:
                        result_str = json.dumps({"error": f"Tool configuration missing for {tool_name}"})
                    
                    # Send response back to OpenAI
                    tool_response_event = {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_str
                        }
                    }
                    await self.send_event(tool_response_event)
                    
                    # Trigger an immediate response generation after tool context is added
                    await self.send_event({"type": "response.create"})

                    if should_close:
                        logger.info("[TOOL] Breaking OpenAI listener loop due to call termination/transfer.")
                        break
                    
                # Handle Assistant Transcription
                elif event_type == "response.audio_transcript.done":
                    transcript = event.get('transcript')
                    if transcript:
                        self.transcript_log.append({"role": "assistant", "text": transcript})
                        logger.info(f"Agent Transcript: {transcript}")
                
                # Handle User Transcription (Async)
                elif event_type.startswith("conversation.item.input_audio_transcription."):
                    if event_type == "conversation.item.input_audio_transcription.completed":
                        user_text = event.get('transcript', '').strip()
                        if user_text:
                            self.transcript_log.append({"role": "user", "text": user_text})
                            logger.info(f"[OPENAI] User Transcript (Final): {user_text}")
                    elif event_type == "conversation.item.input_audio_transcription.failed":
                        logger.error(f"[OPENAI] User transcription failed: {event.get('error')}")

                # Handle Usage Tracking
                elif event_type == "response.done":
                    usage = event.get("response", {}).get("usage")
                    if usage:
                        self.input_tokens += usage.get("input_tokens", 0)
                        self.output_tokens += usage.get("output_tokens", 0)
                        self.total_tokens += usage.get("total_tokens", 0)
                        self.cached_tokens += usage.get("input_token_details", {}).get("cached_tokens", 0)
                        logger.info(f"[OPENAI] Usage Update: Total={self.total_tokens}, Cached={self.cached_tokens}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("OpenAI connection closed.")
        except Exception as e:
            logger.error(f"Error in OpenAI listener loop: {e}")

    def get_transcript(self):
        """Returns the accumulated conversation log."""
        return self.transcript_log

    def get_usage(self):
        """Returns the accumulated token usage."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens
        }
