import logging
from agents.base import BaseAgent
from agents.prompts import VOICE_CONTEXT

logger = logging.getLogger(__name__)

class VoiceAgent(BaseAgent):
    """
    Agent specialized for Voice communication (Phone calls).
    Extends BaseAgent with voice-specific formatting and turn-taking hints.
    """

    def __init__(self, *args, **kwargs):
        # Extract voice-specific settings
        self.voice = kwargs.pop('voice', 'alloy')
        self.vad_threshold = kwargs.pop('vad_threshold', 0.5)
        self.silence_duration_ms = kwargs.pop('silence_duration_ms', 1000)
        
        # Ensure channel is set to 'voice'
        kwargs['channel'] = 'voice'
        super().__init__(*args, **kwargs)
        
        # Inject Voice specific context into the base prompt
        self.base_prompt_text += f"\n\n{VOICE_CONTEXT}"

    def get_system_instructions(self) -> str:
        """
        Returns the compiled system prompt specifically for Voice/Realtime sessions.
        Injects the Voice context and any other runtime instructions.
        """
        # This mirrors the logic in BaseAgent.run but returns the prompt instead of executing
        import datetime
        now = datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
        
        # We manually fill the template here for the Realtime API session initialization
        from agents.prompts import SYSTEM_PROMPT_TEMPLATE
        return SYSTEM_PROMPT_TEMPLATE.format(
            base_prompt=self.base_prompt_text,
            current_time=now,
            additional_context="" # Could be extended later
        )
