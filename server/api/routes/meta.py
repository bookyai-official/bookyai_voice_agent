"""Verify, normalize and durably accept Meta events; never run AI in the request."""
import hashlib
import hmac
import json
import re
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.config import settings
from core.database import AsyncSessionLocal
from models.meta import CHANNEL_MODELS, MetaWebhookEvent, now
from services.meta_security import MetaSecurityError, digest, encrypt_payload, utc


router = APIRouter(tags=['Meta messaging'])
MAX_BODY_BYTES = 1024 * 1024


def signature_valid(body, signature, secret):
    if not secret or not re.fullmatch(r'sha256=[a-fA-F0-9]{64}', signature or ''):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:].lower(), expected)


def normalized_events(payload, expected_channel=None):
    if not isinstance(payload, dict):
        raise ValueError('Invalid payload')
    channel = {'page': 'messenger', 'instagram': 'instagram'}.get(payload.get('object'))
    if not channel or (expected_channel and channel != expected_channel):
        raise ValueError('Wrong webhook object')
    entries = payload.get('entry', [])
    if not isinstance(entries, list):
        raise ValueError('Invalid entries')
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid entry')
        account_id = str(entry.get('id') or '')
        if not account_id.isdecimal() or len(account_id) > 255:
            raise ValueError('Invalid account')
        messaging = entry.get('messaging', [])
        if not isinstance(messaging, list):
            raise ValueError('Invalid messaging')
        for event in messaging:
            if not isinstance(event, dict):
                raise ValueError('Invalid event')
            message = event.get('message')
            if not isinstance(message, dict) or message.get('is_echo') or message.get('is_deleted'):
                continue
            sender = str((event.get('sender') or {}).get('id') or '')
            recipient = str((event.get('recipient') or {}).get('id') or '')
            if not sender.isdecimal() or len(sender) > 100 or recipient != account_id or sender == account_id:
                raise ValueError('Invalid message identity')
            mid = message.get('mid')
            if not isinstance(mid, str) or not 1 <= len(mid) <= 1000:
                raise ValueError('Missing message identity')
            text = message.get('text') or ''
            attachments = message.get('attachments') or []
            if not isinstance(text, str) or len(text) > 64000 or not isinstance(attachments, list):
                raise ValueError('Invalid content')
            if not text and not attachments:
                continue
            # Attachment URLs are stored as untrusted metadata and never fetched.
            metadata = [item for item in attachments[:20] if isinstance(item, dict)]
            timestamp = event.get('timestamp')
            if timestamp is not None and (not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp <= 0):
                raise ValueError('Invalid timestamp')
            yield channel, account_id, sender, mid, {
                'text': text, 'attachments': metadata, 'timestamp': timestamp,
            }


async def persist_events(payload, expected_channel=None):
    # Fully validate before writing so malformed batches cannot be partly accepted.
    events = list(normalized_events(payload, expected_channel))
    app_id = settings.FB_APP_ID
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for channel, account_id, sender, mid, content in events:
                model = CHANNEL_MODELS[channel]
                integration = (await db.execute(select(model).where(
                    model.app_id == app_id, model.account_id == account_id,
                    model.status == 'connected',
                ).with_for_update())).scalar_one_or_none()
                if not integration:
                    continue
                if any(value and utc(value) <= now() for value in (integration.token_expires_at, integration.data_access_expires_at)):
                    integration.status, integration.last_error_code = 'reauth_required', 'token_expired'
                    continue
                event_key = digest([app_id, channel, account_id, sender, mid, 'message'])
                if (await db.execute(select(MetaWebhookEvent.id).where(MetaWebhookEvent.event_key == event_key))).first():
                    continue
                item = MetaWebhookEvent(
                    event_key=event_key, conversation_key=digest([app_id, channel, account_id, sender]),
                    business_id=integration.business_id, channel=channel, app_id=app_id,
                    account_id=account_id, sender_id=sender, connection_revision=integration.revision,
                    encrypted_payload=encrypt_payload(content),
                )
                try:
                    async with db.begin_nested():
                        db.add(item)
                        await db.flush()
                except IntegrityError:
                    continue  # Another ingress worker already accepted the event.
                integration.last_received_at = now()
                integration.webhook_status = 'subscribed'
                integration.updated_at = now()


async def verification(request):
    token = settings.META_WEBHOOK_VERIFY_TOKEN or settings.FB_VERIFY_TOKEN
    query = request.query_params
    supplied = query.get('hub.verify_token', '')
    if not token or len(token) < 32:
        return Response('Webhook verification is not configured.', status_code=503)
    if query.get('hub.mode') != 'subscribe' or not hmac.compare_digest(supplied, token):
        return Response('Verification failed.', status_code=403)
    challenge = query.get('hub.challenge', '')
    if not challenge or len(challenge) > 512:
        return Response('Invalid verification challenge.', status_code=400)
    return Response(challenge, media_type='text/plain')


async def receive(request, expected_channel=None):
    if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
        return Response('Webhook authentication is not configured.', status_code=503)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return Response('Payload too large.', status_code=413)
    if not signature_valid(bytes(body), request.headers.get('x-hub-signature-256'), settings.FB_APP_SECRET):
        return Response('Invalid signature.', status_code=403)
    try:
        payload = json.loads(body)
        await persist_events(payload, expected_channel)
    except (ValueError, TypeError, KeyError, AttributeError):
        return Response('Invalid webhook payload.', status_code=400)
    except (SQLAlchemyError, MetaSecurityError):
        # Acknowledge only after durable commit; Meta can retry a failed write.
        return Response('Unable to accept event. Please retry.', status_code=503)
    return Response('EVENT_RECEIVED', media_type='text/plain')


@router.api_route('/messenger/webhook', methods=['GET', 'POST'])
async def messenger_webhook(request: Request):
    return await verification(request) if request.method == 'GET' else await receive(request, 'messenger')


@router.api_route('/instagram/webhook', methods=['GET', 'POST'])
async def instagram_webhook(request: Request):
    return await verification(request) if request.method == 'GET' else await receive(request, 'instagram')
