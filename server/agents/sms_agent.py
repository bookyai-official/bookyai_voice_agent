import logging
from typing import List, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage
from agents.base import BaseAgent
from agents.prompts import SMS_CONTEXT

logger = logging.getLogger(__name__)

class SMSAgent(BaseAgent):
    """
    Agent specialized for SMS communication.
    Extends BaseAgent with SMS-specific constraints and memory management.
    """

    def __init__(self, *args, **kwargs):
        # Ensure channel is set to 'text' for SMS
        kwargs['channel'] = 'text'
        super().__init__(*args, **kwargs)
        
        # Inject SMS specific context into the base prompt
        self.base_prompt_text += f"\n\n{SMS_CONTEXT}"

    async def ask(self, user_message: str, thread_id: str, additional_context: str = "", history: List[Any] = None) -> str:
        """
        Higher-level method to get a response, applying SMS-specific post-processing.
        """
        response_text = await self.run(user_message, thread_id, additional_context, history)
        
        # Post-processing: Ensure SMS length limits or formatting
        processed_text = response_text.strip()
        
        if len(processed_text) > 1600: # Soft cap at 10 segments
            logger.warning(f"[SMS AGENT] Response is very long ({len(processed_text)} chars). Trimming.")
            processed_text = processed_text[:1597] + "..."
            
        return processed_text
