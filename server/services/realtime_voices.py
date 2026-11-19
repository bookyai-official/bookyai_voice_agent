"""Compatible built-in voices for the realtime call providers."""
from services.realtime_provider import get_realtime_provider


# Keep IDs aligned with ai_agent/voice_settings.py in the Django application.
OPENAI_VOICES = (
    'alloy', 'ash', 'ballad', 'coral', 'echo',
    'sage', 'shimmer', 'verse', 'marin', 'cedar',
)
GEMINI_VOICES = (
    'Zephyr', 'Puck', 'Charon', 'Kore',
    'Fenrir', 'Leda', 'Orus', 'Aoede',
    'Callirrhoe', 'Autonoe', 'Enceladus', 'Iapetus',
    'Umbriel', 'Algieba', 'Despina', 'Erinome',
    'Algenib', 'Rasalgethi', 'Laomedeia', 'Achernar',
    'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima',
    'Achird', 'Zubenelgenubi', 'Vindemiatrix', 'Sadachbia',
    'Sadaltager', 'Sulafat',
)


def resolve_realtime_voice(model_name, saved_voice):
    """Use the selected provider's canonical voice or its safe built-in default."""
    provider = get_realtime_provider(model_name)
    voices = GEMINI_VOICES if provider == 'gemini' else OPENAI_VOICES
    default = 'Kore' if provider == 'gemini' else 'alloy'
    canonical = {name.lower(): name for name in voices}
    return canonical.get((saved_voice or '').strip().lower(), default)
