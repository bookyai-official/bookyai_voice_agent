import json
import logging
import asyncio
import websockets
import datetime
from typing import Optional, List, Dict, Any
from core.config import settings
from twilio.rest import Client as TwilioClient
from agents.voice_agent import VoiceAgent

logger = logging.getLogger(__name__)

class OpenAIRealtimeClient:
    """
    Client for OpenAI Realtime API, now integrated with LangChain VoiceAgent.
    """
    def __init__(
        self, 
        agent: VoiceAgent,
        twilio_sid: Optional[str] = None, 
        twilio_token: Optional[str] = None,
        channel: str = "twilio"
    ):
        self.agent = agent
        self.twilio_sid = twilio_sid
        self.twilio_token = twilio_token
        self.channel = channel # "twilio" or "browser"
        
        self.ws = None
        self.transcript_log = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_tokens = 0
        
        # Realtime API URL
        self.url = f"wss://api.openai.com/v1/realtime?model={self.agent.model_name}"
        self.headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v2"
        }

    async def connect(self):
        """Connect to OpenAI Realtime WebSocket."""
        self.ws = await websockets.connect(self.url, additional_headers=self.headers)
        await self._initialize_session()

    async def _initialize_session(self):
        """Send the initial session configuration using VoiceAgent definitions."""
        audio_format = "g711_ulaw" if self.channel == "twilio" else "pcm16"
        
        instructions = self.agent.get_system_instructions()
        tool_schemas = self.agent.get_tool_schemas()

     

        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": instructions,
                "voice": getattr(self.agent, 'voice', 'alloy'),
                "temperature": getattr(self.agent, 'temperature', 0.8),
                "input_audio_format": audio_format,
                "output_audio_format": audio_format,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": getattr(self.agent, 'vad_threshold', 0.5),
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": getattr(self.agent, 'silence_duration_ms', 1000)
                },
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "tools": tool_schemas
            }
        }
        await self.send_event(session_update)
        logger.info(f"[OPENAI] Session initialized (Channel: {self.channel}, Format: {audio_format}, Voice: {session_update['session']['voice']})")

    async def send_event(self, event: dict):
        """Send a JSON payload to OpenAI."""
        if self.ws:
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

    async def listen(self, client_ws, stream_sid=None, call_sid=None):
        """
        Listen to events from OpenAI and relay them to the appropriate client (Twilio or Browser).
        Standardizes event mapping and tool execution logic.
        """
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                # 1. Handle Audio Relay
                if event_type == "response.audio.delta":
                    base64_audio = event.get("delta")
                    if base64_audio:
                        if self.channel == "twilio":
                            await client_ws.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": base64_audio}
                            })
                        else:
                            await client_ws.send_json({"type": "audio", "audio": base64_audio})

                # 2. Handle Audio Done
                elif event_type == "response.audio.done":
                    if self.channel == "browser":
                        await client_ws.send_json({"type": "audio_done"})

                # 3. Handle Interruption (VAD)
                elif event_type == "input_audio_buffer.speech_started":
                    if self.channel == "twilio":
                        await client_ws.send_json({
                            "event": "clear",
                            "stream_sid": stream_sid
                        })
                    else:
                        # For browser, we try to cancel the current response
                        try:
                            await self.send_event({"type": "response.cancel"})
                        except:
                            pass
                        await client_ws.send_json({"type": "speech_start"})

                elif event_type == "input_audio_buffer.speech_stopped":
                    if self.channel == "browser":
                        await client_ws.send_json({"type": "speech_stop"})

                # 4. Handle Tool Execution
                elif event_type == "response.function_call_arguments.done":
                    call_id = event.get("call_id")
                    tool_name = event.get("name")
                    arguments_json = event.get("arguments")
                    
                    if self.channel == "browser":
                        await client_ws.send_json({"type": "tool_call", "tool": tool_name})

                    logger.info(f"[VOICE AGENT] Executing tool: {tool_name}")
                    
                    # Find the tool in our agent's toolset
                    tool = next((t for t in self.agent.tools if t.name == tool_name), None)
                    
                    if tool:
                        try:
                            # Parse arguments and invoke tool (unified logic)
                            args = json.loads(arguments_json)
                            result_str = await tool.ainvoke(args)
                        except Exception as e:
                            logger.error(f"Error executing tool {tool_name}: {e}")
                            result_str = json.dumps({"error": f"Tool execution failed: {str(e)}"})
                    else:
                        result_str = json.dumps({"error": f"Tool {tool_name} not found."})

                    # Send response back to OpenAI
                    await self.send_event({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": str(result_str)
                        }
                    })
                    
                    # Trigger response generation
                    await self.send_event({"type": "response.create"})

                    # Handle termination/transfer
                    if "Call has been ended" in str(result_str) or "Call is being transferred" in str(result_str):
                        logger.info(f"[VOICE AGENT] Termination requested via {tool_name}. Closing.")
                        if self.channel == "browser":
                            await client_ws.send_json({"type": "transcript", "role": "system", "text": f"🛑 {result_str}"})
                        await asyncio.sleep(1)
                        break
                
                # 5. Transcription & Logging
                elif event_type == "response.audio_transcript.done":
                    transcript = event.get('transcript')
                    if transcript:
                        self.transcript_log.append({"role": "assistant", "text": transcript})
                        print(f"DEBUG: [VOICE] AGENT: {transcript}")
                        logger.info(f"Agent: {transcript}")
                        if self.channel == "browser":
                            await client_ws.send_json({"type": "transcript", "role": "assistant", "text": transcript})
                
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    user_text = event.get('transcript', '').strip()
                    if user_text:
                        self.transcript_log.append({"role": "user", "text": user_text})
                        print(f"DEBUG: [VOICE] USER: {user_text}")
                        logger.info(f"User: {user_text}")
                        if self.channel == "browser":
                            await client_ws.send_json({"type": "transcript", "role": "user", "text": user_text})

                # 6. Usage Tracking
                elif event_type == "response.done":
                    usage = event.get("response", {}).get("usage")
                    if usage:
                        self.input_tokens = usage.get("input_tokens", 0)
                        self.output_tokens = usage.get("output_tokens", 0)
                        self.total_tokens = usage.get("total_tokens", 0)
                        self.cached_tokens = usage.get("input_token_details", {}).get("cached_tokens", 0)
                        logger.info(f"[OPENAI] Usage: {self.total_tokens} tokens.")

                # 7. Errors
                elif event_type == "error":
                    logger.error(f"[OPENAI] Error event: {event.get('error')}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("OpenAI connection closed.")
        except Exception as e:
            logger.exception(f"Error in OpenAI listener loop: {e}")

    def get_transcript(self):
        return self.transcript_log

    def get_usage(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens
        }
