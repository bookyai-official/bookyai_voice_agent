"""Select a realtime voice transport from the configured model name."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.voice_agent import VoiceAgent


class RealtimeProviderError(ValueError):
    """The configured voice model has no available realtime handler."""


def get_realtime_provider(model_name: str) -> str:
    """Return the provider for a supported model family, rejecting unknown models."""
    normalized = (model_name or '').strip().lower()
    if normalized.startswith('gemini-'):
        if '-live' not in normalized and '-native-audio' not in normalized:
            raise RealtimeProviderError('Select a Gemini Live audio model for voice calls.')
        return 'gemini'
    for family in ('gpt-realtime', 'gpt-4o-realtime', 'gpt-4o-mini-realtime'):
        if normalized == family or normalized.startswith((f'{family}-', f'{family}.')):
            return 'openai'
    raise RealtimeProviderError(
        'Unsupported realtime voice model. Select an OpenAI Realtime or Gemini Live model.'
    )


def get_realtime_client_class(model_name: str):
    """Return an implemented handler, or fail before creating a provider session."""
    provider = get_realtime_provider(model_name)
    if provider == 'gemini':
        try:
            from services.gemini_live import GeminiLiveClient
        except ImportError:
            raise RealtimeProviderError(
                'Gemini Live dependencies are unavailable. Install the voice server requirements.'
            ) from None
        return GeminiLiveClient
    from services.openai_realtime import OpenAIRealtimeClient

    return OpenAIRealtimeClient


def create_realtime_client(agent: 'VoiceAgent', channel: str = 'twilio'):
    """Build the selected transport with the agent's resolved model and credentials."""
    client_class = get_realtime_client_class(agent.model_name)
    return client_class(agent=agent, channel=channel)
