"""Durable Meta inbox worker. Run separately: python -m workers.meta_messages."""
import asyncio
import contextlib
import json
import logging
import random
import signal
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.config import settings
from core.database import AsyncSessionLocal, engine
# Standalone workers do not import main.py, which normally registers these
# relationship targets before SQLAlchemy first configures its mappers.
import models.agent
import models.call
import models.tool
from models.conversation import Chat, Message
from models.meta import CHANNEL_MODELS, MetaConversationLease, MetaWebhookEvent as Event, now
from services.meta_graph import send_message
from services.meta_security import MetaSecurityError, decrypt, encrypt, utc


logger = logging.getLogger('workers.meta_messages')
LEASE_SECONDS = 180
MAX_ATTEMPTS = 5
UNFINISHED = ('pending', 'processing', 'generating', 'prepared', 'sending', 'delivered')


class LeaseLost(Exception):
    pass


async def owned(db, event_id, owner):
    row = (await db.execute(select(Event).where(
        Event.id == event_id, Event.lease_owner == owner,
        Event.status.in_(UNFINISHED), Event.lease_until > now(),
    ).with_for_update())).scalar_one_or_none()
    if not row:
        raise LeaseLost()
    return row


async def connection(db, event):
    if event.app_id != settings.FB_APP_ID:
        return None
    model = CHANNEL_MODELS[event.channel]
    row = (await db.execute(select(model).where(
        model.business_id == event.business_id, model.app_id == event.app_id,
        model.account_id == event.account_id, model.revision == event.connection_revision,
        model.status == 'connected',
    ))).scalar_one_or_none()
    if row and any(value and utc(value) <= now() for value in (row.token_expires_at, row.data_access_expires_at)):
        row.status, row.last_error_code = 'reauth_required', 'token_expired'
        return None
    return row


async def claim():
    owner = uuid4().hex
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Recovery never repeats generation/tools or a possibly sent reply.
            for stage, final, code in (
                ('processing', 'pending', 'lease_expired'),
                ('generating', 'failed', 'generation_interrupted'),
                ('sending', 'uncertain', 'send_interrupted'),
            ):
                values = {'status': final, 'lease_owner': '', 'lease_until': None,
                          'last_error_code': code, 'updated_at': now()}
                if final in ('failed', 'uncertain'):
                    values.update(encrypted_payload='', encrypted_reply='')
                await db.execute(update(Event).where(Event.status == stage, Event.lease_until < now()).values(**values))
            # A prepared reply or durable send receipt can safely resume without
            # generation or another send, respectively.
            await db.execute(update(Event).where(
                Event.status.in_(['prepared', 'delivered']), Event.lease_until < now(),
            ).values(lease_owner='', lease_until=None))
            candidates = (await db.execute(select(Event).where(
                Event.status.in_(['pending', 'prepared', 'delivered']), Event.available_at <= now(),
                or_(Event.lease_until.is_(None), Event.lease_until < now()),
            ).order_by(Event.created_at, Event.id).with_for_update(skip_locked=True).limit(30))).scalars().all()
            for event in candidates:
                older = (await db.execute(select(Event.id).where(
                    Event.conversation_key == event.conversation_key, Event.id < event.id,
                    Event.status.in_(UNFINISHED),
                ).limit(1))).first()
                if older:
                    continue
                lease = await db.get(MetaConversationLease, event.conversation_key, with_for_update=True)
                if lease and utc(lease.expires_at) > now():
                    continue
                if not lease:
                    try:
                        async with db.begin_nested():
                            lease = MetaConversationLease(conversation_key=event.conversation_key)
                            db.add(lease)
                            await db.flush()
                    except IntegrityError:
                        continue
                if event.attempts >= MAX_ATTEMPTS and not event.provider_message_id:
                    event.status, event.last_error_code = 'failed', 'attempts_exhausted'
                    event.encrypted_payload, event.encrypted_reply = '', ''
                    continue
                lease.owner, lease.expires_at = owner, now() + timedelta(seconds=LEASE_SECONDS)
                event.lease_owner, event.lease_until = owner, lease.expires_at
                event.attempts += 1
                if event.status == 'pending':
                    event.status = 'processing'
                event.updated_at = now()
                return event.id, owner, event.conversation_key
    return None


async def heartbeat(event_id, owner, conversation_key):
    while True:
        await asyncio.sleep(30)
        try:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    until = now() + timedelta(seconds=LEASE_SECONDS)
                    changed = await db.execute(update(Event).where(
                        Event.id == event_id, Event.lease_owner == owner, Event.status.in_(UNFINISHED),
                        Event.lease_until > now(),
                    ).values(lease_until=until))
                    if not changed.rowcount:
                        return
                    await db.execute(update(MetaConversationLease).where(
                        MetaConversationLease.conversation_key == conversation_key,
                        MetaConversationLease.owner == owner,
                    ).values(expires_at=until))
        except SQLAlchemyError:
            return  # The lease will expire; every further stage checks ownership.


async def finish(event_id, owner, status, code=''):
    async with AsyncSessionLocal() as db:
        async with db.begin():
            event = await owned(db, event_id, owner)
            event.status, event.last_error_code = status, code
            event.encrypted_payload, event.encrypted_reply = '', ''
            event.lease_owner, event.lease_until, event.updated_at = '', None, now()
    logger.info('Meta event %s finished: status=%s reason=%s.', event_id, status, code or 'none')


async def retry(event_id, owner, code, delay=30):
    async with AsyncSessionLocal() as db:
        async with db.begin():
            event = await owned(db, event_id, owner)
            if event.attempts >= MAX_ATTEMPTS:
                event.status = 'failed'
                event.encrypted_payload, event.encrypted_reply = '', ''
            else:
                event.status = 'delivered' if event.provider_message_id else 'prepared' if event.encrypted_reply else 'pending'
                event.available_at = now() + timedelta(seconds=min(3600, max(delay, 2 ** event.attempts)) + random.uniform(0, 3))
            event.last_error_code, event.updated_at = code, now()
            event.lease_owner, event.lease_until = '', None
    logger.warning('Meta event %s retry decision: status=%s reason=%s attempts=%s.', event_id, event.status, code, event.attempts)


async def prepare_inbound(event_id, owner):
    async with AsyncSessionLocal() as db:
        async with db.begin():
            event = await owned(db, event_id, owner)
            if event.provider_message_id:
                return event  # A recorded delivery still needs accounting after disconnect.
            record = await connection(db, event)
            if not record:
                return None
            if event.provider_message_id or event.encrypted_reply:
                return event
            payload = json.loads(decrypt(event.encrypted_payload))
            if event.inbound_message_id:
                return event
            kind = 'messenger_page' if event.channel == 'messenger' else 'instagram_unified'
            sender_field = Chat.fb_psid if event.channel == 'messenger' else Chat.ig_sid
            chat = (await db.execute(select(Chat).where(
                Chat.business_id == event.business_id, Chat.meta_app_id == event.app_id,
                Chat.meta_account_id == event.account_id, Chat.meta_identity_kind == kind,
                sender_field == event.sender_id, Chat.is_active.is_(True),
            ))).scalar_one_or_none()
            if not chat:
                chat = Chat(business_id=event.business_id, meta_app_id=event.app_id,
                            meta_account_id=event.account_id, meta_identity_kind=kind,
                            **({'fb_psid': event.sender_id} if event.channel == 'messenger' else {'ig_sid': event.sender_id}))
                db.add(chat)
                await db.flush()
            message = Message(chat_id=chat.id, role='user', content=payload.get('text') or 'Attachment received.',
                              attachments=payload.get('attachments') or [])
            db.add(message)
            await db.flush()
            event.chat_id, event.inbound_message_id = chat.id, message.id
            return event


def response_window_open(event):
    payload = json.loads(decrypt(event.encrypted_payload))
    received = utc(event.created_at)
    timestamp = payload.get('timestamp')
    if timestamp:
        try:
            received = min(received, datetime.fromtimestamp(timestamp / 1000, timezone.utc))
        except (ValueError, OverflowError, OSError):
            return False
    # Leave a margin for network and provider clocks within Meta's 24-hour window.
    return now() - received < timedelta(hours=23, minutes=55)


async def reserve_generation(event_id, owner, agent, policy):
    from services.usage_service import UsageService
    from services.billing_scope import billing_workspace_ids, lock_billing_account
    async with AsyncSessionLocal() as db:
        async with db.begin():
            event = await owned(db, event_id, owner)
            if not await connection(db, event):
                return False
            # Serialize quota reservations across both Meta channels for the
            # workspace. The short transaction ends before any AI execution.
            await lock_billing_account(db, event.business_id)
            if not policy:
                covered_ids = await billing_workspace_ids(db, event.business_id)
                remaining = await UsageService.get_remaining_usage(db, event.business_id, 'sms')
                reserved = (await db.execute(select(func.count(Event.id)).where(
                    Event.business_id.in_(covered_ids), Event.id != event.id,
                    Event.status.in_(['generating', 'prepared', 'sending', 'delivered']),
                    Event.usage_charged.is_(False), Event.usage_precharged.is_(False),
                ))).scalar_one()
                if remaining <= reserved:
                    return False
            event.status, event.usage_precharged = 'generating', bool(policy)
            event.updated_at = now()
    return True


async def finalize_delivery(event_id, owner):
    """Charge once and save the sent reply in the same database transaction."""
    from models.subscription import Subscription, UsageTracker, CreditBalance, SubscriptionPlan
    from services.billing_scope import lock_billing_account
    from services.usage_service import UsageService
    async with AsyncSessionLocal() as db:
        async with db.begin():
            event = await owned(db, event_id, owner)
            if not event.provider_message_id:
                raise LeaseLost()
            if not event.usage_charged and not event.usage_precharged:
                billing_id = await lock_billing_account(db, event.business_id)
                subscription, current_tracker = await UsageService.get_active_usage_tracker(db, event.business_id)
                if subscription:
                    tracker = (await db.execute(select(UsageTracker).where(
                        UsageTracker.id == current_tracker.id,
                    ).with_for_update())).scalar_one_or_none() if current_tracker else None
                    plan = await db.get(SubscriptionPlan, subscription.plan_id)
                    limit = (plan.usage_limits or {}).get('sms', 0) if plan else 0
                    if tracker and (limit is None or tracker.sms_used < limit):
                        tracker.sms_used += 1
                    else:
                        balance = (await db.execute(select(CreditBalance).where(
                            CreditBalance.business_id == billing_id,
                        ).with_for_update())).scalar_one_or_none()
                        credits = dict(balance.additional_limits or {}) if balance else {}
                        if balance and credits.get('sms', 0) > 0:
                            credits['sms'] -= 1
                            balance.additional_limits = credits
                        elif tracker:
                            tracker.sms_used += 1
            if event.chat_id and await db.get(Chat, event.chat_id):
                db.add(Message(chat_id=event.chat_id, role='assistant', content=decrypt(event.encrypted_reply)))
            event.usage_charged, event.status = True, 'completed'
            event.encrypted_payload, event.encrypted_reply = '', ''
            event.lease_owner, event.lease_until, event.updated_at = '', None, now()
    logger.info('Meta event %s completed: reply delivered and saved.', event_id)


async def process(event_id, owner):
    from models.agent import AIAgent
    from services.usage_service import UsageService
    from services.lifetime_runtime import LifetimeRuntime, RuntimeDenied

    event = await prepare_inbound(event_id, owner)
    if event is None:
        await finish(event_id, owner, 'cancelled', 'connection_unavailable')
        return
    if event.provider_message_id:
        await finalize_delivery(event_id, owner)
        return
    if not response_window_open(event):
        await finish(event_id, owner, 'completed', 'messaging_window_expired')
        return
    if not event.encrypted_reply:
        payload = json.loads(decrypt(event.encrypted_payload))
        user_text = payload.get('text') or ''
        async with AsyncSessionLocal() as db:
            chat = await db.get(Chat, event.chat_id)
            agent = (await db.execute(select(AIAgent).where(
                AIAgent.business_id == event.business_id, AIAgent.active.is_(True),
            ).order_by(AIAgent.id).limit(1))).scalar_one_or_none()
            feature = 'fb_messenger_agent' if event.channel == 'messenger' else 'instagram_agent'
            if (not user_text or len(user_text) > 16000 or not chat or not chat.enable_ai or not agent):
                await finish(event_id, owner, 'completed', 'ai_not_applicable')
                return
            if not await UsageService.has_feature_access(db, event.business_id, feature):
                await finish(event_id, owner, 'completed', 'feature_unavailable')
                return
            policy = await LifetimeRuntime.context(event.business_id, purpose='text', feature=feature)
        if not await reserve_generation(event_id, owner, agent, policy):
            await finish(event_id, owner, 'completed', 'usage_or_connection_unavailable')
            return
        billing = {}
        try:
            logger.info('Meta event %s generating reply: channel=%s agent_id=%s.', event_id, event.channel, agent.id)
            from services.langchain_service import get_chat_response
            response = await get_chat_response(
                agent_id=agent.id, chat_id=event.chat_id, user_message=user_text,
                channel='text', feature=feature, operation_key=f'meta:{event.event_key}',
                persist_user_message=False, persist_assistant_message=False,
                current_message_id=event.inbound_message_id, billing_context=billing,
            )
            if not isinstance(response, str) or not response.strip():
                raise ValueError()
            if len(response) > 1000:
                response = response[:997] + '...'
        except Exception as exc:
            logger.error('Meta event %s generation failed: error_type=%s.', event_id, type(exc).__name__)
            # Agent tools may already have acted; do not repeat generation.
            await finish(event_id, owner, 'failed', 'generation_failed')
            return
        async with AsyncSessionLocal() as db:
            async with db.begin():
                current = await owned(db, event_id, owner)
                current.encrypted_reply = encrypt(response)
                current.usage_precharged = bool(billing.get('precharged'))
                current.status, current.updated_at = 'prepared', now()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            current = await owned(db, event_id, owner)
            record = await connection(db, current)
            chat = await db.get(Chat, current.chat_id) if current.chat_id else None
            if not record or not chat or not chat.enable_ai or not response_window_open(current):
                current.status, current.last_error_code = 'cancelled', 'connection_or_chat_disabled'
                current.encrypted_payload, current.encrypted_reply = '', ''
                logger.info('Meta event %s cancelled before sending: connection or chat disabled, or messaging window expired.', event_id)
                return
            token, reply = decrypt(record.encrypted_token), decrypt(current.encrypted_reply)
            current.status, current.updated_at = 'sending', now()
    outcome = await send_message(event.channel, event.account_id, token, event.sender_id, reply)
    logger.info('Meta event %s send outcome: status=%s code=%s.', event_id, outcome.status, outcome.code or 'none')
    if outcome.status == 'sent':
        async with AsyncSessionLocal() as db:
            async with db.begin():
                current = await owned(db, event_id, owner)
                current.provider_message_id, current.status = outcome.message_id, 'delivered'
        await finalize_delivery(event_id, owner)
    elif outcome.status == 'retry':
        await retry(event_id, owner, outcome.code, outcome.retry_after)
    elif outcome.status == 'reauth':
        async with AsyncSessionLocal() as db:
            async with db.begin():
                model = CHANNEL_MODELS[event.channel]
                await db.execute(update(model).where(
                    model.business_id == event.business_id, model.revision == event.connection_revision,
                ).values(status='reauth_required', last_error_code=outcome.code))
        await finish(event_id, owner, 'cancelled', 'reauth_required')
    else:
        await finish(event_id, owner, 'uncertain' if outcome.status == 'uncertain' else 'failed', outcome.code)


async def run_claim(claimed):
    event_id, owner, key = claimed
    logger.info('Meta event %s claimed by worker.', event_id)
    task = asyncio.create_task(heartbeat(event_id, owner, key))
    try:
        await process(event_id, owner)
    except LeaseLost:
        logger.warning('Meta event %s stopped: worker lease lost.', event_id)
    except (SQLAlchemyError, MetaSecurityError) as exc:
        logger.warning('Meta event %s stopped after a storage/credential error: error_type=%s sqlstate=%s; lease recovery will classify its stage.', event_id, type(exc).__name__, getattr(getattr(exc, 'orig', None), 'sqlstate', None))
    except Exception as exc:
        # No exception strings or payloads: provider/library errors can contain
        # tokens or customer content. The event ID is sufficient for diagnosis.
        logger.error('Meta event %s failed before completion: error_type=%s.', event_id, type(exc).__name__)
        with contextlib.suppress(LeaseLost, SQLAlchemyError):
            await finish(event_id, owner, 'failed', 'processing_failed')
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        async with AsyncSessionLocal() as db:
            async with db.begin():
                await db.execute(update(MetaConversationLease).where(
                    MetaConversationLease.conversation_key == key, MetaConversationLease.owner == owner,
                ).values(owner='', expires_at=now()))


async def serve():
    from services.meta_security import cipher
    cipher()  # Fail startup rather than accepting an unreadable queue.
    if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
        raise RuntimeError('Configure the shared Meta app credentials before starting the worker.')
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async def consumer():
        while not stop.is_set():
            try:
                item = await claim()
                if item:
                    await run_claim(item)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        pass
            except SQLAlchemyError as exc:
                logger.warning('Meta worker database operation failed: error_type=%s sqlstate=%s; retrying.', type(exc).__name__, getattr(getattr(exc, 'orig', None), 'sqlstate', None))
                await asyncio.sleep(2)
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('The production Meta worker requires PostgreSQL for cross-process claims and quota locks.')
    concurrency = max(1, min(settings.META_WORKER_CONCURRENCY, 32))
    logger.info('Meta messaging worker started: consumers=%s. Polling the database queue.', concurrency)
    try:
        await asyncio.gather(*(consumer() for _ in range(concurrency)))
    finally:
        logger.info('Meta messaging worker stopping.')
        await engine.dispose()


if __name__ == '__main__':
    from core.logging_config import setup_logging
    setup_logging()
    asyncio.run(serve())
