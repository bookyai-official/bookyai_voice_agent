"""Durable Meta ingress and worker regressions, with isolated SQLite storage."""
import asyncio
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.routes import meta as ingress
from api.routes import facebook as compatibility
from models.meta import MetaWebhookEvent as Event, MessengerIntegration, InstagramIntegration, MetaConversationLease, now
from models.conversation import Chat, Message
from models.agent import AIAgent
from models.subscription import SubscriptionPlan, Subscription, UsageTracker, CreditBalance
from services import meta_graph, meta_security
from services.chat_service import get_or_create_chat, ChatServiceError
from workers import meta_messages as worker

KEY=Fernet.generate_key().decode()
SETTINGS=SimpleNamespace(FB_APP_ID='100',FB_APP_SECRET='test-secret',META_WEBHOOK_VERIFY_TOKEN='v'*40,
                         FB_VERIFY_TOKEN='',META_CREDENTIAL_ENCRYPTION_KEYS=KEY,META_GRAPH_API_VERSION='v27.0')


def body(channel='instagram',mid='mid-1',account='102',sender='999',**message):
    return {'object':'instagram' if channel=='instagram' else 'page','entry':[{'id':account,'messaging':[{
        'sender':{'id':sender},'recipient':{'id':account},'timestamp':int(now().timestamp()*1000),
        'message':{'mid':mid,'text':'Hello',**message}}]}]}


class MetaRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.engine=create_async_engine('sqlite+aiosqlite:///'+str(Path(self.temp.name)/'meta.sqlite'))
        self.factory=async_sessionmaker(self.engine,expire_on_commit=False)
        tables=[MessengerIntegration.__table__,InstagramIntegration.__table__,Event.__table__,MetaConversationLease.__table__,
                Chat.__table__,Message.__table__,AIAgent.__table__,SubscriptionPlan.__table__,Subscription.__table__,UsageTracker.__table__,CreditBalance.__table__]
        async with self.engine.begin() as db:
            for table in tables: await db.run_sync(table.create)
        self.patches=[patch.object(ingress,'AsyncSessionLocal',self.factory),patch.object(worker,'AsyncSessionLocal',self.factory),
                      patch.object(ingress,'settings',SETTINGS),patch.object(worker,'settings',SETTINGS),patch.object(meta_security,'settings',SETTINGS),patch.object(meta_graph,'settings',SETTINGS)]
        for item in self.patches:item.start()
        self.app=FastAPI();self.app.include_router(ingress.router,prefix='/api');self.app.include_router(compatibility.router,prefix='/api')
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://runtime.example')
        async with self.factory.begin() as db:
            db.add_all([InstagramIntegration(business_id='workspace',app_id='100',account_id='102',status='connected',revision='r1',encrypted_token=meta_security.encrypt('ig-token')),
                        MessengerIntegration(business_id='workspace',app_id='100',account_id='101',status='connected',revision='r2',encrypted_token=meta_security.encrypt('page-token')),
                        AIAgent(business_id='workspace',name='Agent',system_prompt='Help',active=True),
                        SubscriptionPlan(id=1,name='Plan',usage_limits={'sms':10}),
                        Subscription(id=1,business_id='workspace',plan_id=1,status='active'),
                        UsageTracker(subscription_id=1,sms_used=0)])

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):item.stop()
        await self.engine.dispose();self.temp.cleanup()

    async def post(self,payload=None,path='/api/instagram/webhook',signature=True):
        data=json.dumps(payload or body(),separators=(',',':')).encode()
        headers={'X-Hub-Signature-256':'sha256='+hmac.new(SETTINGS.FB_APP_SECRET.encode(),data,hashlib.sha256).hexdigest()} if signature else {}
        return await self.client.post(path,content=data,headers=headers)

    async def rows(self,model):
        async with self.factory() as db:return (await db.execute(select(model).order_by(model.id))).scalars().all()

    async def accept_claim(self,payload=None):
        self.assertEqual((await self.post(payload)).status_code,200)
        result=await worker.claim();self.assertIsNotNone(result)
        return result

    async def ai_patches(self):
        # Imported lazily in production; mock only external AI, billing policy and transport.
        from services import langchain_service
        from services.usage_service import UsageService
        from services.lifetime_runtime import LifetimeRuntime
        return [patch.object(langchain_service,'get_chat_response',AsyncMock(return_value='Reply')),
                patch.object(UsageService,'has_feature_access',AsyncMock(return_value=True)),
                patch.object(UsageService,'get_remaining_usage',AsyncMock(return_value=10)),
                patch.object(LifetimeRuntime,'context',AsyncMock(return_value=None)),
                patch.object(worker,'send_message',AsyncMock(return_value=meta_graph.SendOutcome('sent','out-1')))]

    async def run_with_ai(self,claimed,send=None,generate=None):
        patches=await self.ai_patches()
        mocks=[p.start() for p in patches]
        if send:mocks[-1].side_effect=send
        if generate:mocks[0].side_effect=generate
        try:await worker.run_claim(claimed)
        finally:
            for p in reversed(patches):p.stop()
        return mocks

    async def test_verified_handshake_no_weak_default(self):
        response=await self.client.get('/api/instagram/webhook',params={'hub.mode':'subscribe','hub.verify_token':'v'*40,'hub.challenge':'challenge'})
        self.assertEqual((response.status_code,response.text),(200,'challenge'))
        self.assertEqual((await self.client.get('/api/instagram/webhook',params={'hub.mode':'subscribe','hub.verify_token':'admin'})).status_code,403)
        for primary, fallback in [('short-token', ''), ('', 'short-token')]:
            with self.subTest(primary=bool(primary)), patch.object(ingress,'settings',SimpleNamespace(META_WEBHOOK_VERIFY_TOKEN=primary,FB_VERIFY_TOKEN=fallback)):
                response=await self.client.get('/api/instagram/webhook',params={'hub.mode':'subscribe','hub.verify_token':'short-token','hub.challenge':'challenge'})
                self.assertEqual((response.status_code,response.text),(200,'challenge'))
                response=await self.client.get('/api/instagram/webhook',params={'hub.mode':'subscribe','hub.verify_token':'wrong-token','hub.challenge':'challenge'})
                self.assertEqual(response.status_code,403)
        with patch.object(ingress,'settings',SimpleNamespace(META_WEBHOOK_VERIFY_TOKEN='',FB_VERIFY_TOKEN='')):
            self.assertEqual((await self.client.get('/api/instagram/webhook')).status_code,503)

    async def test_unsigned_wrong_channel_and_malformed_rejected(self):
        self.assertEqual((await self.post(signature=False)).status_code,403)
        self.assertEqual((await self.post(body(channel='messenger',account='101'))).status_code,400)
        malformed=body();malformed['entry'][0]['messaging'][0]['recipient']['id']='101'
        self.assertEqual((await self.post(malformed)).status_code,400)
        self.assertEqual(len(await self.rows(Event)),0)

    async def test_duplicate_batch_is_durable_encrypted_and_no_ai_at_ingress(self):
        payload=body();payload['entry'][0]['messaging']*=2
        self.assertEqual((await self.post(payload)).status_code,200)
        self.assertEqual((await self.post(payload)).status_code,200)
        rows=await self.rows(Event)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].status,'pending')
        self.assertNotIn('Hello',rows[0].encrypted_payload)
        self.assertEqual(len(await self.rows(Message)),0)
        record=(await self.rows(InstagramIntegration))[0];self.assertIsNotNone(record.last_received_at)

    async def test_compatibility_endpoint_accepts_signed_both_objects(self):
        for channel,account in [('messenger','101'),('instagram','102')]:
            self.assertEqual((await self.post(body(channel=channel,account=account),path='/api/facebook/webhook')).status_code,200)
        self.assertEqual(len(await self.rows(Event)),2)

    async def test_unknown_echo_and_nonmessage_events_are_ignored(self):
        self.assertEqual((await self.post(body(account='888'))).status_code,200)
        self.assertEqual((await self.post(body(is_echo=True))).status_code,200)
        self.assertEqual(len(await self.rows(Event)),0)

    async def test_invalid_batch_not_partially_accepted_and_storage_failure_not_acked(self):
        payload=body();payload['entry'].append({'id':'broken'})
        self.assertEqual((await self.post(payload)).status_code,400)
        self.assertEqual(len(await self.rows(Event)),0)
        from sqlalchemy.exc import OperationalError
        with patch.object(ingress,'persist_events',AsyncMock(side_effect=OperationalError('x',{},Exception()))):
            self.assertEqual((await self.post()).status_code,503)

    async def test_expired_connection_not_queued(self):
        async with self.factory.begin() as db:
            await db.execute(update(InstagramIntegration).values(token_expires_at=now()-timedelta(seconds=1)))
        self.assertEqual((await self.post()).status_code,200)
        self.assertEqual(len(await self.rows(Event)),0)
        self.assertEqual((await self.rows(InstagramIntegration))[0].status,'reauth_required')

    async def test_claim_serializes_same_conversation_without_blocking_other_channel(self):
        first=await self.accept_claim()
        await self.post(body(mid='mid-2'))
        self.assertIsNone(await worker.claim())
        await self.post(body(channel='messenger',account='101'),path='/api/messenger/webhook')
        other=await worker.claim();self.assertIsNotNone(other);self.assertNotEqual(first[2],other[2])

    async def test_interrupted_generation_or_send_never_retried(self):
        for stage,expected in [('generating','failed'),('sending','uncertain')]:
            claimed=await self.accept_claim(body(mid=stage))
            async with self.factory.begin() as db:
                await db.execute(update(Event).where(Event.id==claimed[0]).values(status=stage,lease_until=now()-timedelta(seconds=1)))
                await db.execute(update(MetaConversationLease).values(expires_at=now()-timedelta(seconds=1)))
            self.assertIsNone(await worker.claim())
            self.assertEqual((await self.rows(Event))[-1].status,expected)

    async def test_processing_crash_can_recover_without_duplicate_inbound(self):
        claimed=await self.accept_claim()
        await worker.prepare_inbound(claimed[0],claimed[1])
        async with self.factory.begin() as db:
            await db.execute(update(Event).values(lease_until=now()-timedelta(seconds=1)))
            await db.execute(update(MetaConversationLease).values(expires_at=now()-timedelta(seconds=1)))
        resumed=await worker.claim();self.assertIsNotNone(resumed)
        await worker.prepare_inbound(resumed[0],resumed[1])
        self.assertEqual(len(await self.rows(Message)),1)
        with self.assertRaises(worker.LeaseLost):await worker.prepare_inbound(claimed[0],claimed[1])

    async def test_replaced_connection_cancels_old_event(self):
        claimed=await self.accept_claim()
        async with self.factory.begin() as db:await db.execute(update(InstagramIntegration).values(revision='new'))
        mocks=await self.run_with_ai(claimed)
        self.assertEqual((await self.rows(Event))[0].status,'cancelled')
        mocks[0].assert_not_called();mocks[-1].assert_not_called()

    async def test_success_is_saved_and_billed_once(self):
        claimed=await self.accept_claim();mocks=await self.run_with_ai(claimed)
        event=(await self.rows(Event))[0]
        self.assertEqual((event.status,event.provider_message_id,event.usage_charged),('completed','out-1',True))
        self.assertEqual((await self.rows(UsageTracker))[0].sms_used,1)
        self.assertEqual([m.role for m in await self.rows(Message)],['user','assistant'])
        self.assertEqual(event.encrypted_payload,'')
        self.assertEqual(mocks[0].call_args.kwargs['current_message_id'],event.inbound_message_id)
        self.assertFalse(mocks[0].call_args.kwargs['persist_user_message'])
        mocks[-1].assert_awaited_once_with('instagram','102','ig-token','999','Reply')
        self.assertIsNone(await worker.claim())

    async def test_safe_retry_reuses_reply_without_ai_or_double_billing(self):
        claimed=await self.accept_claim()
        mocks=await self.run_with_ai(claimed,send=[meta_graph.SendOutcome('retry',code='rate_limited')])
        self.assertEqual((await self.rows(Event))[0].status,'prepared')
        self.assertEqual((await self.rows(UsageTracker))[0].sms_used,0)
        async with self.factory.begin() as db:await db.execute(update(Event).values(available_at=now()))
        resumed=await worker.claim();mocks=await self.run_with_ai(resumed)
        mocks[0].assert_not_called()
        self.assertEqual((await self.rows(UsageTracker))[0].sms_used,1)
        self.assertEqual(len(await self.rows(Message)),2)

    async def test_unknown_send_never_retried_and_no_sent_history(self):
        claimed=await self.accept_claim()
        await self.run_with_ai(claimed,send=[meta_graph.SendOutcome('uncertain',code='timeout')])
        self.assertEqual((await self.rows(Event))[0].status,'uncertain')
        self.assertIsNone(await worker.claim())
        self.assertEqual(len(await self.rows(Message)),1)
        self.assertEqual((await self.rows(UsageTracker))[0].sms_used,0)

    async def test_generation_error_never_repeats_tools(self):
        claimed=await self.accept_claim()
        mocks=await self.run_with_ai(claimed,generate=RuntimeError('private prompt'))
        self.assertEqual((await self.rows(Event))[0].last_error_code,'generation_failed')
        mocks[-1].assert_not_called();self.assertIsNone(await worker.claim())

    async def test_disconnect_during_generation_prevents_send(self):
        claimed=await self.accept_claim()
        async def generate(**kwargs):
            async with self.factory.begin() as db:await db.execute(update(InstagramIntegration).values(status='disconnected'))
            return 'Reply'
        mocks=await self.run_with_ai(claimed,generate=generate)
        mocks[-1].assert_not_called()
        self.assertEqual((await self.rows(Event))[0].status,'cancelled')

    async def test_durable_delivery_resumes_accounting_after_disconnect_without_resend(self):
        claimed=await self.accept_claim();event=await worker.prepare_inbound(claimed[0],claimed[1])
        async with self.factory.begin() as db:
            await db.execute(update(Event).values(status='delivered',provider_message_id='out-1',encrypted_reply=meta_security.encrypt('Reply')))
            await db.execute(update(InstagramIntegration).values(status='disconnected'))
        mocks=await self.run_with_ai(claimed)
        mocks[0].assert_not_called();mocks[-1].assert_not_called()
        self.assertEqual((await self.rows(UsageTracker))[0].sms_used,1)
        self.assertEqual((await self.rows(Event))[0].status,'completed')

    async def test_expired_messaging_window_preserves_inbound_without_reply(self):
        payload=body();payload['entry'][0]['messaging'][0]['timestamp']=int((now()-timedelta(days=2)).timestamp()*1000)
        claimed=await self.accept_claim(payload);mocks=await self.run_with_ai(claimed)
        self.assertEqual((await self.rows(Event))[0].last_error_code,'messaging_window_expired')
        self.assertEqual(len(await self.rows(Message)),1)
        mocks[0].assert_not_called();mocks[-1].assert_not_called()

    async def test_attachments_saved_without_fetch_or_ai(self):
        claimed=await self.accept_claim(body(text='',attachments=[{'type':'image','payload':{'url':'http://untrusted/'}}]))
        mocks=await self.run_with_ai(claimed)
        self.assertEqual((await self.rows(Message))[0].attachments[0]['type'],'image')
        mocks[0].assert_not_called();mocks[-1].assert_not_called()

    async def test_same_sender_scoped_to_different_recipient_accounts(self):
        claimed=await self.accept_claim();await worker.prepare_inbound(claimed[0],claimed[1])
        async with self.factory.begin() as db:await db.execute(update(InstagramIntegration).values(account_id='103',revision='r3'))
        second=await self.accept_claim(body(account='103',mid='other-account'))
        await worker.prepare_inbound(second[0],second[1])
        chats=await self.rows(Chat)
        self.assertEqual(len(chats),2);self.assertNotEqual(chats[0].meta_account_id,chats[1].meta_account_id)
        with self.assertRaises(ChatServiceError):await get_or_create_chat('workspace',ig_sid='999')


class MetaSendTests(unittest.IsolatedAsyncioTestCase):
    async def outcome(self,response=None,error=None):
        client=AsyncMock();client.post.side_effect=error
        client.post.return_value=response
        context=Mock();context.__aenter__=AsyncMock(return_value=client);context.__aexit__=AsyncMock(return_value=False)
        with patch.object(meta_graph,'settings',SETTINGS),patch.object(meta_graph.httpx,'AsyncClient',return_value=context):
            result=await meta_graph.send_message('instagram','102','secret','999','Reply')
        return result,client

    async def test_correct_explicit_endpoint_bearer_and_receipt(self):
        result,client=await self.outcome(httpx.Response(200,json={'message_id':'receipt'}))
        self.assertEqual(result.status,'sent')
        self.assertEqual(client.post.call_args.args[0],'https://graph.facebook.com/v27.0/102/messages')
        self.assertEqual(client.post.call_args.kwargs['headers'],{'Authorization':'Bearer secret'})

    async def test_missing_receipt_and_read_timeout_are_uncertain(self):
        for response,error in [(httpx.Response(200,json={}),None),(None,httpx.ReadTimeout('secret')),(httpx.Response(503,json={'error':{}}),None)]:
            result,_=await self.outcome(response,error)
            self.assertEqual(result.status,'uncertain')

    async def test_connect_failure_and_rate_limit_are_safe_retry(self):
        for response,error in [(None,httpx.ConnectError('secret')),(httpx.Response(429,json={'error':{'code':4}},headers={'Retry-After':'90'}),None)]:
            result,_=await self.outcome(response,error)
            self.assertEqual(result.status,'retry')

    async def test_auth_error_requires_reconnect(self):
        result,_=await self.outcome(httpx.Response(400,json={'error':{'code':190}}))
        self.assertEqual(result.status,'reauth')
