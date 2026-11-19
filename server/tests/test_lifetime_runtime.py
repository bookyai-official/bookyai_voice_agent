import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.lifetime_runtime import LifetimeRuntime, RuntimeDenied
from services.usage_service import UsageService
from services.openai_realtime import OpenAIRealtimeClient
from services.langchain_service import get_chat_response
from rag.embeddings import EmbeddingProvider


POLICY = {'source': 'appsumo', 'active': True, 'funding': 'byok', 'api_key': 'sk-customer-key',
          'model': 'gpt-4o-mini', 'allowed_features': ['webchat_agent'],
          'remaining': {'sms': 3, 'minutes': 5}, 'limits': {'sms': 5, 'minutes': 10}}


class LifetimeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribers_do_not_use_new_bridge(self):
        with patch.object(LifetimeRuntime, 'has_license', AsyncMock(return_value=False)), patch.object(LifetimeRuntime, 'request', AsyncMock()) as request:
            self.assertIsNone(await LifetimeRuntime.context('business'))
            request.assert_not_called()

    async def test_license_bridge_failure_never_falls_back(self):
        with patch.object(LifetimeRuntime, 'has_license', AsyncMock(return_value=True)), patch.object(LifetimeRuntime, 'request', AsyncMock(side_effect=RuntimeDenied('Unavailable'))):
            with self.assertRaises(RuntimeDenied):
                await LifetimeRuntime.context('business', purpose='text')

    async def test_paid_subscription_takes_precedence_when_license_also_owned(self):
        with patch.object(LifetimeRuntime, 'has_license', AsyncMock(return_value=True)), patch.object(LifetimeRuntime, 'request', AsyncMock(return_value={'source': 'subscription', 'active': True})):
            self.assertIsNone(await LifetimeRuntime.context('business'))

    async def test_inactive_license_is_denied(self):
        with patch.object(LifetimeRuntime, 'has_license', AsyncMock(return_value=True)), patch.object(LifetimeRuntime, 'request', AsyncMock(return_value={'source': 'inactive', 'active': False})):
            with self.assertRaises(RuntimeDenied):
                await LifetimeRuntime.context('business')

    async def test_misconfigured_bridge_cannot_return_platform_key(self):
        with patch('services.lifetime_runtime.settings', SimpleNamespace(BOOKY_BILLING_BASE_URL='', AI_RUNTIME_TOKEN='')):
            with self.assertRaises(RuntimeDenied):
                await LifetimeRuntime.request('business')

    async def test_external_plain_http_bridge_is_refused(self):
        with patch('services.lifetime_runtime.settings', SimpleNamespace(BOOKY_BILLING_BASE_URL='http://billing.example', AI_RUNTIME_TOKEN='r'*40)):
            with self.assertRaises(RuntimeDenied):
                await LifetimeRuntime.request('business')

    async def test_lifetime_feature_checks_use_canonical_entitlement(self):
        with patch.object(LifetimeRuntime, 'context', AsyncMock(return_value=POLICY)):
            self.assertTrue(await UsageService.has_feature_access(None, 'business', 'webchat_agent'))
            self.assertFalse(await UsageService.has_feature_access(None, 'business', 'calling_agent'))

    async def test_zero_remaining_usage_is_denied(self):
        policy = {**POLICY, 'remaining': {'sms': 0}}
        with patch.object(LifetimeRuntime, 'context', AsyncMock(return_value=policy)):
            self.assertFalse(await UsageService.has_remaining_usage(None, 'business', 'sms'))

    async def test_lifetime_precharged_usage_is_not_debited_again(self):
        db = SimpleNamespace(execute=AsyncMock())
        with patch.object(LifetimeRuntime, 'context', AsyncMock(return_value=POLICY)):
            await UsageService.update_usage(db, 'business', 'sms', 1)
        db.execute.assert_not_called()

    async def test_realtime_uses_resolved_customer_key(self):
        agent = SimpleNamespace(model_name='gpt-realtime-test', resolved_api_key='customer-only')
        with patch('services.openai_realtime.settings', SimpleNamespace(OPENAI_API_KEY='platform-only')):
            client = OpenAIRealtimeClient(agent)
        self.assertEqual(client.headers['Authorization'], 'Bearer customer-only')

    async def test_embeddings_are_never_cached_across_businesses_or_key_rotation(self):
        first = {**POLICY, 'model': 'text-embedding-3-large'}
        second = {**first, 'api_key': 'different-customer-key'}
        with patch.object(LifetimeRuntime, 'context', AsyncMock(side_effect=[first, second])), patch.object(LifetimeRuntime, 'reserve', AsyncMock()), patch.object(LifetimeRuntime, 'settle', AsyncMock()), patch.object(EmbeddingProvider, '_create_embedder', Mock(side_effect=[object(), object()])) as create:
            a = await EmbeddingProvider.get_embedder(None, 'business-one')
            b = await EmbeddingProvider.get_embedder(None, 'business-two')
        self.assertIsNot(a, b)
        self.assertEqual(create.call_args_list[0].args[2], 'sk-customer-key')
        self.assertEqual(create.call_args_list[1].args[2], 'different-customer-key')

    async def test_embeddings_require_tenant_context(self):
        with self.assertRaises(RuntimeDenied):
            await EmbeddingProvider.get_embedder(None)

    async def test_chat_reserves_before_provider_execution(self):
        agent = SimpleNamespace(runtime_policy=POLICY, business_id='business', ask=AsyncMock(return_value='Hello'))
        with patch('services.langchain_service.AgentFactory.create_sms_agent', AsyncMock(return_value=agent)), patch('services.langchain_service._load_history_from_db', AsyncMock(return_value=[])), patch('services.langchain_service.save_message', AsyncMock()), patch.object(LifetimeRuntime, 'context', AsyncMock(return_value=POLICY)), patch.object(LifetimeRuntime, 'reserve', AsyncMock(side_effect=RuntimeDenied('No allowance'))), patch.object(LifetimeRuntime, 'settle', AsyncMock()):
            with self.assertRaises(RuntimeDenied):
                await get_chat_response(1, 2, 'Hello')
        agent.ask.assert_not_called()

    async def test_oversized_chat_does_not_call_provider(self):
        agent = SimpleNamespace(runtime_policy=POLICY, business_id='business', ask=AsyncMock())
        with patch('services.langchain_service.AgentFactory.create_sms_agent', AsyncMock(return_value=agent)), patch.object(LifetimeRuntime, 'context', AsyncMock(return_value=POLICY)):
            with self.assertRaises(RuntimeDenied):
                await get_chat_response(1, 2, 'x'*16001)
        agent.ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
