from twilio.rest import Client
from core.config import settings
import logging

logger = logging.getLogger(__name__)

def make_outbound_call(to_number: str, agent_id: int, host_domain: str):
    """
    Triggers an outbound call using Twilio REST API.
    The call will connect and execute TwiML returned by the provided webhook URL.
    """
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        logger.error("Twilio credentials are not set.")
        raise ValueError("Missing Twilio Configuration")

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    
    # We point the webhook to our generic incoming call handler, but we can pass agent_id as a query param
    webhook_url = f"https://{host_domain}/api/calls/incoming?agent_id={agent_id}"

    try:
        call = client.calls.create(
            to=to_number,
            from_=settings.TWILIO_PHONE_NUMBER,
            url=webhook_url,
            method="POST",
            record=True
        )
        return call.sid
    except Exception as e:
        logger.error(f"Failed to initiate Twilio call: {e}")
        raise
