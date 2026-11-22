"""Explicit account endpoints and classified send outcomes, without secret logging."""
from dataclasses import dataclass
import re

import httpx
from core.config import settings


@dataclass(frozen=True)
class SendOutcome:
    status: str
    message_id: str = ''
    code: str = ''
    retry_after: int = 30


async def send_message(channel, account_id, token, recipient_id, text):
    if (channel not in ('messenger', 'instagram') or not str(account_id).isdecimal()
            or not str(recipient_id).isdecimal() or not token
            or not re.fullmatch(r'v\d+\.\d+', settings.META_GRAPH_API_VERSION)):
        return SendOutcome('failed', code='invalid_send_configuration')
    payload = {'recipient': {'id': recipient_id}, 'message': {'text': text}}
    if channel == 'messenger':
        payload['messaging_type'] = 'RESPONSE'
    url = f'https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{account_id}/messages'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
            response = await client.post(url, headers={'Authorization': f'Bearer {token}'}, json=payload)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return SendOutcome('retry', code='connect_failed')
    except httpx.HTTPError:
        # The request may already have been accepted. Never blindly resend it.
        return SendOutcome('uncertain', code='send_outcome_unknown')
    try:
        data = response.json()
    except ValueError:
        if response.is_success or response.status_code >= 500:
            return SendOutcome('uncertain', code='invalid_provider_response')
        data = {}
    if response.is_success:
        mid = data.get('message_id') if isinstance(data, dict) else None
        return SendOutcome('sent', message_id=mid) if isinstance(mid, str) and mid else SendOutcome('uncertain', code='missing_send_receipt')
    error = data.get('error', {}) if isinstance(data, dict) else {}
    raw_code = error.get('code') if isinstance(error, dict) else None
    code = str(raw_code) if isinstance(raw_code, int) else 'provider_error'
    if raw_code in (190, 10, 200) or response.status_code == 401:
        return SendOutcome('reauth', code=code)
    if response.status_code == 429 or raw_code in (4, 17, 32, 613, 80001, 80002):
        retry = response.headers.get('Retry-After', '')
        return SendOutcome('retry', code=code, retry_after=min(3600, max(1, int(retry))) if retry.isdecimal() else 30)
    if response.status_code >= 500:
        return SendOutcome('uncertain', code='provider_send_error')
    return SendOutcome('failed', code=code)
