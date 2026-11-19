"""Gemini Live transport for Booky's phone and browser voice calls."""
import asyncio
import json
import re
from contextlib import suppress
from typing import TYPE_CHECKING, Optional

from google import genai
from google.genai import errors, types
from websockets.exceptions import ConnectionClosed
from starlette.websockets import WebSocketDisconnect

from services.realtime_audio import RealtimeAudioConverter
from services.realtime_provider import RealtimeProviderError
from services.realtime_voices import resolve_realtime_voice

if TYPE_CHECKING:
    from agents.voice_agent import VoiceAgent


class GeminiLiveClient:
    """Adapt Gemini sessions to the same call interface as OpenAIRealtimeClient."""

    def __init__(self, agent: 'VoiceAgent', channel: str = 'twilio'):
        """Use only the agent's resolved Gemini credential and per-call state."""
        self.agent = agent
        self.channel = channel
        self.audio = RealtimeAudioConverter(channel)
        self.failed = False
        self._closed = False
        self._ending = False
        self._draining = False
        self._drain_complete = asyncio.Event()
        self._on_transcript = None
        self._client = None
        self._session = None
        self._connection = None
        self._send_lock = asyncio.Lock()
        self._tool_lock = asyncio.Lock()
        self._tool_tasks = {}
        self._started_tools = set()
        self._cancelled_tools = set()
        self._tool_results = {}
        self._transcript = []
        self._pending_transcript = {'user': None, 'assistant': None}
        self._usage = dict(input_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0)
        self._resume_handle = None
        self._resumable = False
        self._go_away = False
        self._reconnecting = False
        self._resume_count = 0
        self._client_ws = None
        self._stream_sid = None

    def _session_config(self):
        """Build native audio, transcript and tool configuration for this agent."""
        voice = resolve_realtime_voice(
            self.agent.model_name, getattr(self.agent, 'voice', None)
        )
        declarations = [
            types.FunctionDeclaration(
                name=schema['name'], description=schema.get('description', ''),
                parameters_json_schema=schema.get('parameters', {'type': 'object'}),
            )
            for schema in self.agent.get_tool_schemas()
        ]
        return types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            system_instruction=self.agent.get_system_instructions(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    silence_duration_ms=max(100, min(2000, self.agent.silence_duration_ms)),
                ),
                activity_handling='START_OF_ACTIVITY_INTERRUPTS',
            ),
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle,
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
        )

    async def _open_session(self):
        """Open one SDK-managed WebSocket with a bounded setup timeout."""
        self._connection = self._client.aio.live.connect(
            model=self.agent.model_name, config=self._session_config()
        )
        self._session = await asyncio.wait_for(self._connection.__aenter__(), timeout=15)

    async def connect(self):
        """Connect using the selected model without exposing upstream error details."""
        if not self.agent.resolved_api_key:
            raise RealtimeProviderError('Configure the Gemini API key in System Settings.')
        try:
            self._client = genai.Client(
                api_key=self.agent.resolved_api_key,
                vertexai=False,
                http_options=types.HttpOptions(api_version='v1beta'),
            )
            await self._open_session()
        except Exception:
            self.failed = True
            raise RealtimeProviderError(
                'Gemini Live could not connect. Check the Gemini key, Live model access and quota.'
            ) from None

    @staticmethod
    def _is_transient_error(error) -> bool:
        """Recognize connection loss and temporary failures without retrying validation errors."""
        if isinstance(error, ConnectionClosed):
            code = error.rcvd.code if error.rcvd else 1006
        else:
            code = getattr(error, 'code', None)
        return code in (500, 502, 503, 504, 1000, 1001, 1006, 1011, 1012, 1013)

    async def _resume_locked(self):
        """Renew a planned connection using Gemini's most recent resumable checkpoint."""
        tools_pending = any(not task.done() for task in self._tool_tasks.values())
        if not self._go_away or not self._resumable or not self._resume_handle or tools_pending:
            raise RealtimeProviderError('Gemini Live disconnected without a resumable session.')
        if self._resume_count >= 3:
            raise RealtimeProviderError('Gemini Live exceeded its call reconnection limit.')
        self._resume_count += 1
        self._resumable = False
        self._go_away = False
        self._reconnecting = True
        try:
            if self._connection:
                with suppress(Exception):
                    await self._connection.__aexit__(None, None, None)
            # The Developer API's handle resumption does not support transparent
            # message acknowledgements in the pinned SDK. Never replay audio,
            # greetings or tool actions with unknown delivery status.
            await self._open_session()
        finally:
            self._reconnecting = False

    async def _send(self, method: str, payload: dict):
        """Serialize sends against planned reconnects and sanitize upstream errors."""
        async with self._send_lock:
            if self._closed or not self._session:
                raise RealtimeProviderError('The Gemini Live session is closed.')
            try:
                await getattr(self._session, method)(**payload)
            except Exception:
                if self._ending or self._closed or self._draining:
                    return
                self.failed = True
                raise RealtimeProviderError('Gemini Live could not receive the call audio or tool result.') from None

    async def start_conversation(self, greeting_message: Optional[str] = None):
        """Prompt Gemini to speak the configured greeting once at call startup."""
        prompt = (
            f'Greet the caller by saying: {greeting_message}' if greeting_message
            else 'Start the call now. Greet the caller briefly and ask how you can help.'
        )
        payload = {
            'turns': types.Content(role='user', parts=[types.Part(text=prompt)]),
            'turn_complete': True,
        }
        await self._send('send_client_content', payload)

    async def send_audio(self, base64_audio: str):
        """Convert the next client audio chunk and send it to Gemini's automatic VAD."""
        pcm = self.audio.decode_input(base64_audio)
        if pcm:
            await self._send(
                'send_realtime_input',
                {'audio': types.Blob(data=pcm, mime_type='audio/pcm;rate=16000')},
            )

    async def finish_input(self):
        """Flush trailing user audio while keeping the receiver alive briefly for transcripts."""
        self._draining = True
        self._drain_complete.clear()
        if self._closed or self._ending or not self._session:
            return
        try:
            await asyncio.wait_for(
                self._send('send_realtime_input', {'audio_stream_end': True}), timeout=1,
            )
            await asyncio.wait_for(self._drain_complete.wait(), timeout=2)
        except (asyncio.TimeoutError, RealtimeProviderError):
            pass

    async def _browser_event(self, event: dict):
        """Keep recording transcripts even when browser playback has disconnected."""
        if self.channel == 'browser' and self._client_ws and not self._draining:
            try:
                await self._client_ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError, OSError):
                self._client_ws = None

    async def _flush_transcript(self, role: str):
        """Publish an assembled utterance once while retaining partial text in storage."""
        entry = self._pending_transcript[role]
        self._pending_transcript[role] = None
        if entry:
            entry['text'] = entry['text'].strip()
            if entry['text']:
                if self._on_transcript:
                    self._on_transcript(self.get_transcript(), self.get_usage())
                await self._browser_event({'type': 'transcript', **entry})

    async def _add_transcription(self, role: str, transcription):
        """Accumulate transcription fragments without stripping inter-fragment spaces."""
        if transcription.text:
            new_utterance = self._pending_transcript[role] is None
            if new_utterance:
                entry = {'role': role, 'text': ''}
                self._transcript.append(entry)
                self._pending_transcript[role] = entry
            # Store text before any playback/UI await can fail or be cancelled.
            self._pending_transcript[role]['text'] += transcription.text
            if new_utterance and role == 'user':
                await self._browser_event({'type': 'speech_start'})
        if transcription.finished:
            await self._flush_transcript(role)
            if role == 'user':
                await self._browser_event({'type': 'speech_stop'})

    async def _interrupt(self):
        """Clear queued playback on both transports when Gemini detects barge-in."""
        self.audio.reset_output()
        if self.channel == 'twilio' and not self._draining:
            await self._client_ws.send_json({'event': 'clear', 'streamSid': self._stream_sid})
        else:
            await self._browser_event({'type': 'speech_start'})
        await self._flush_transcript('assistant')

    async def _relay_content(self, content):
        """Process every audio and transcription part, including combined server events."""
        if content.input_transcription:
            await self._add_transcription('user', content.input_transcription)
        if content.output_transcription:
            await self._add_transcription('assistant', content.output_transcription)
        if content.interrupted:
            await self._interrupt()
        if content.model_turn and not content.interrupted and not self._draining:
            for part in content.model_turn.parts or []:
                blob = part.inline_data
                if not blob or not blob.data or getattr(part, 'thought', False):
                    continue
                mime_type = blob.mime_type or 'audio/pcm;rate=24000'
                if not mime_type.startswith('audio/pcm'):
                    raise RealtimeProviderError('Gemini Live returned an unsupported audio format.')
                match = re.search(r'(?:^|;)\s*rate=(\d+)', mime_type)
                sample_rate = int(match.group(1)) if match else 24000
                if not 8000 <= sample_rate <= 96000:
                    raise RealtimeProviderError('Gemini Live returned an unsupported audio rate.')
                audio = self.audio.encode_output(blob.data, sample_rate)
                if audio:
                    await self._browser_event({'type': 'speech_stop'})
                    if self.channel == 'twilio':
                        await self._client_ws.send_json({
                            'event': 'media', 'streamSid': self._stream_sid,
                            'media': {'payload': audio},
                        })
                    else:
                        await self._browser_event({'type': 'audio', 'audio': audio})
        if content.turn_complete:
            self._drain_complete.set()
            await self._flush_transcript('user')
            await self._flush_transcript('assistant')
            await self._browser_event({'type': 'speech_stop'})
            await self._browser_event({'type': 'audio_done'})
            self.audio.reset_output()

    def _track_usage(self, metadata):
        """Sum Gemini's response usage, including thinking tokens in output usage."""
        prompt = metadata.prompt_token_count or 0
        output = (metadata.response_token_count or 0) + (metadata.thoughts_token_count or 0)
        self._usage['input_tokens'] += prompt
        self._usage['output_tokens'] += output
        self._usage['cached_tokens'] += metadata.cached_content_token_count or 0
        self._usage['total_tokens'] += metadata.total_token_count or (prompt + output)

    def _update_resumption(self, update):
        """Retain only checkpoints the server explicitly marks as resumable."""
        self._resumable = bool(update.resumable and update.new_handle)
        if self._resumable:
            self._resume_handle = update.new_handle

    async def _run_tool(self, call):
        """Execute a tool once per ID; serial execution preserves booking action order."""
        try:
            async with self._tool_lock:
                if self._closed or self._draining or call.id in self._cancelled_tools:
                    return
                self._started_tools.add(call.id)
                await self._browser_event({'type': 'tool_call', 'tool': call.name})
                tool = next((tool for tool in self.agent.tools if tool.name == call.name), None)
                if call.id in self._tool_results:
                    result = self._tool_results[call.id]
                elif tool is None:
                    result = {'error': 'The requested tool is unavailable.'}
                else:
                    try:
                        value = await asyncio.wait_for(tool.ainvoke(call.args or {}), timeout=30)
                        if isinstance(value, str):
                            with suppress(ValueError):
                                value = json.loads(value)
                        result = value if isinstance(value, dict) else {'result': value}
                        # Ensure the result is safe to serialize on the live connection.
                        json.dumps(result)
                    except asyncio.TimeoutError:
                        result = {'error': 'Tool timed out. Verify the outcome before retrying.'}
                    except Exception:
                        result = {'error': 'Tool execution failed. Verify the outcome before retrying.'}
                self._tool_results[call.id] = result
                if self._closed or self._draining or call.id in self._cancelled_tools:
                    return
                response = types.FunctionResponse(id=call.id, name=call.name, response=result)
                payload = {'function_responses': [response]}
                result_text = json.dumps(result)
                if (
                    call.name in ('end_call', 'transfer_call')
                    and ('Call has been ended' in result_text or 'Call is being transferred' in result_text)
                ):
                    self._ending = True
                    async with self._send_lock:
                        with suppress(Exception):
                            await self._session.send_tool_response(**payload)
                    await self._session.close()
                else:
                    await self._send('send_tool_response', payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._ending:
                self.failed = True
            with suppress(Exception):
                await self._session.close()
        finally:
            self._started_tools.discard(call.id)

    def _schedule_tools(self, tool_call):
        """Dispatch tools in background tasks so audio and interruption events keep flowing."""
        if self._draining:
            return
        for call in tool_call.function_calls or []:
            if not call.id or not call.name:
                raise RealtimeProviderError('Gemini Live returned an invalid tool call.')
            existing = self._tool_tasks.get(call.id)
            if existing and not existing.done():
                continue
            if len(self._tool_tasks) >= 256 and call.id not in self._tool_tasks:
                raise RealtimeProviderError('The call exceeded its tool execution limit.')
            self._tool_tasks[call.id] = asyncio.create_task(self._run_tool(call))

    def _cancel_tools(self, cancellation):
        """Cancel queued calls; allow started business operations to finish without retry."""
        for call_id in cancellation.ids or []:
            self._cancelled_tools.add(call_id)
            task = self._tool_tasks.get(call_id)
            if task and call_id not in self._started_tools:
                task.cancel()

    async def _receive_loop(self):
        """Continue receiving across turn boundaries and planned connection renewals."""
        while not self._closed and not self._ending and not self.failed:
            async with self._send_lock:
                session = self._session
            try:
                received = False
                async for message in session.receive():
                    received = True
                    if self._reconnecting or session is not self._session:
                        break
                    if message.usage_metadata:
                        self._track_usage(message.usage_metadata)
                    if message.session_resumption_update:
                        self._update_resumption(message.session_resumption_update)
                    if message.tool_call_cancellation:
                        self._cancel_tools(message.tool_call_cancellation)
                    if message.server_content:
                        await self._relay_content(message.server_content)
                    if self._reconnecting or session is not self._session:
                        break
                    if message.tool_call:
                        self._schedule_tools(message.tool_call)
                    if message.go_away:
                        self._go_away = True
                    tools_pending = any(not task.done() for task in self._tool_tasks.values())
                    if self._go_away and self._resumable and not tools_pending:
                        async with self._send_lock:
                            if session is self._session:
                                await self._resume_locked()
                        break
                if self._closed or self._ending:
                    return
                if not received and session is self._session:
                    raise RealtimeProviderError('Gemini Live stopped responding.')
            except (ConnectionClosed, errors.APIError) as error:
                if self._closed or self._ending or self.failed:
                    return
                if not self._is_transient_error(error):
                    raise RealtimeProviderError('Gemini Live rejected the call session.') from None
                async with self._send_lock:
                    if session is self._session:
                        await self._resume_locked()

    async def listen(self, client_ws, stream_sid=None, call_sid=None, on_transcript=None):
        """Relay provider events using Booky's existing phone or browser protocol."""
        self._client_ws = client_ws
        self._stream_sid = stream_sid
        self._on_transcript = on_transcript
        try:
            await self._receive_loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._draining:
                self.failed = True
        finally:
            with suppress(Exception):
                await self._flush_transcript('user')
                await self._flush_transcript('assistant')
                if self.failed:
                    await self._browser_event({
                        'type': 'error',
                        'message': 'Gemini Live disconnected. Please start a new call.',
                    })

    async def close(self):
        """Close sockets and settle running tools without abandoning queued tasks."""
        self._closed = True
        tasks = list(self._tool_tasks.items())
        for call_id, task in tasks:
            if call_id not in self._started_tools:
                task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        if self._connection:
            with suppress(Exception):
                await self._connection.__aexit__(None, None, None)
            self._connection = None
        if self._client:
            with suppress(Exception):
                await self._client.aio.aclose()
            with suppress(Exception):
                self._client.close()
            self._client = None
        self._session = None

    def get_transcript(self):
        """Return all captured utterances, including final partial transcription."""
        return [dict(entry, text=entry['text'].strip()) for entry in self._transcript if entry['text'].strip()]

    def get_usage(self):
        """Return normalized call-wide token counts for the existing usage recorder."""
        return dict(self._usage)
