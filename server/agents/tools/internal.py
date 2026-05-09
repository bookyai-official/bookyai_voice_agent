import logging
from typing import Optional, Callable
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

def create_internal_tools(
    twilio_client: Optional[any] = None, 
    call_sid: Optional[str] = None
):
    """
    Factory function to create internal agent tools with injected dependencies.
    
    Args:
        twilio_client: An initialized Twilio REST client
        call_sid: The SID of the active call (for voice channel)
    """

    @tool
    def end_call() -> str:
        """
        Ends the current phone call immediately. 
        Use this when the customer wants to hang up or the conversation is finished.
        """
        if not twilio_client or not call_sid:
            return "Error: Call control is not available on this channel."
        
        try:
            # We don't want to block the loop, but since this is a final action,
            # a brief synchronous call is often acceptable in these wrappers.
            # In production, this would ideally be an async call.
            twilio_client.calls(call_sid).update(status="completed")
            logger.info(f"[TOOL] Call {call_sid} terminated by agent.")
            return "Call has been ended successfully."
        except Exception as e:
            logger.error(f"[TOOL] Failed to end call {call_sid}: {e}")
            return f"Error: Could not end the call. {str(e)}"

    @tool
    def transfer_call(target_number: str) -> str:
        """
        Transfers the current call to a specific phone number or department.
        
        Args:
            target_number: The destination phone number in E.164 format (e.g. +1234567890)
        """
        if not twilio_client or not call_sid:
            return "Error: Call transfer is not available on this channel."

        try:
            twiml = f'<Response><Dial>{target_number}</Dial></Response>'
            twilio_client.calls(call_sid).update(twiml=twiml)
            logger.info(f"[TOOL] Call {call_sid} transferred to {target_number}.")
            return f"Call is being transferred to {target_number}."
        except Exception as e:
            logger.error(f"[TOOL] Failed to transfer call {call_sid}: {e}")
            return f"Error: Could not transfer the call. {str(e)}"

    return [end_call, transfer_call]
