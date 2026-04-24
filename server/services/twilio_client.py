from twilio.rest import Client
from core.config import settings
import logging

logger = logging.getLogger(__name__)

def make_outbound_call(to_number: str, from_number: str, agent_id: int, host_domain: str, twilio_sid: str, twilio_token: str, lead_info: str = None):
    """
    Triggers an outbound call using Twilio REST API.
    The call will connect and execute TwiML returned by the provided webhook URL.
    """
    client = Client(twilio_sid, twilio_token)
    
    # We point the webhook to our generic incoming call handler, but we can pass agent_id as a query param
    webhook_url = f"https://{host_domain}/api/calls/incoming?agent_id={agent_id}"
    if lead_info:
        from urllib.parse import quote
        webhook_url += f"&lead_info={quote(lead_info)}"

    try:
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=webhook_url,
            method="POST",
            record=True
        )
        return call.sid
    except Exception as e:
        logger.error(f"Failed to initiate Twilio call: {e}")
        raise
