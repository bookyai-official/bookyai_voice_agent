import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_function

from agents.tools.factory import ToolFactory
from agents.tools.external import execute_external_api
from services import openai_summary


def config(**changes):
    values = dict(name='bookAppointment', description='Book a demo',
        url='https://example.invalid/bookings/api/create-booking/', method='POST', timeout_seconds=5,
        json_schema={'type': 'object', 'properties': {
            'booking_type': {'type': 'string', 'enum': ['regular', 'urgent']},
            'custom_fields': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'required': ['count']},
            'service_items': {'type': 'array', 'items': {'type': 'string'}},
        }, 'required': ['custom_fields']})
    values.update(changes)
    return SimpleNamespace(**values)


class ToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_is_preserved_and_objects_are_forwarded_without_null_defaults(self):
        source = config()
        tool = ToolFactory.create_external_tool(source)
        actual = convert_to_openai_function(tool)['parameters']
        self.assertEqual(actual['properties']['custom_fields'], source.json_schema['properties']['custom_fields'])
        self.assertEqual(actual['properties']['service_items'], source.json_schema['properties']['service_items'])
        self.assertIn('location_type', actual['properties'])
        payload = {'custom_fields': {'count': 0}, 'service_items': ['extra']}
        with patch('agents.tools.factory.execute_external_api', AsyncMock(return_value='{}')) as execute:
            await tool.ainvoke(payload)
        self.assertEqual(execute.call_args.kwargs['payload'], payload)
        self.assertNotIn('booking_type', execute.call_args.kwargs['payload'])

    async def test_invalid_nested_and_enum_values_never_reach_http(self):
        tool = ToolFactory.create_external_tool(config())
        for payload in ({'custom_fields': '{}'}, {'custom_fields': {}},
                        {'custom_fields': {'count': 1}, 'booking_type': None},
                        {'custom_fields': {'count': 1}, 'booking_type': 'unsupported'},
                        {'custom_fields': {'count': '1'}},
                        {'custom_fields': {'count': 1}, 'service_items': [1]}):
            with self.subTest(payload=payload), patch('agents.tools.factory.execute_external_api', AsyncMock()) as execute:
                result = json.loads(await tool.ainvoke(payload))
                self.assertEqual(result['code'], 'invalid_request')
                execute.assert_not_called()

    async def test_booking_key_is_stable_across_tool_calls_and_optional_changes(self):
        tool_config = config(json_schema={'type': 'object'})
        tool = ToolFactory.create_external_tool(tool_config, operation_scope='business:call-one')
        second_tool = ToolFactory.create_external_tool(tool_config, operation_scope='business:call-one')
        payload = dict(business_id='biz', service_id='demo', booking_date='2026-11-25',
                       start_time='10:00', client_email='test@example.com')
        with patch('agents.tools.factory.execute_external_api', AsyncMock(return_value='{}')) as execute:
            await tool.ainvoke(payload)
            await second_tool.ainvoke({**payload, 'notes': 'retry'})
            await tool.ainvoke({**payload, 'start_time': '11:00'})
        keys = [call.kwargs['idempotency_key'] for call in execute.call_args_list]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])


class ExternalExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, response=None, error=None, method='POST'):
        self.requests = []
        def handler(request):
            self.requests.append(request)
            if error:
                raise error
            return response
        original_client = httpx.AsyncClient
        with patch('agents.tools.external.httpx.AsyncClient',
                   lambda: original_client(transport=httpx.MockTransport(handler))):
            return json.loads(await execute_external_api('https://example.invalid/bookings/', method, 5, {}, 'stable-key'))

    async def test_201_preserves_booking_id_and_sends_retry_key(self):
        result = await self.request(httpx.Response(201, json={'status': 'success', 'booking_id': 'demo'}))
        self.assertEqual(result['booking_id'], 'demo')
        self.assertEqual(self.requests[0].headers['Idempotency-Key'], 'stable-key')

    async def test_204_and_put_method(self):
        result = await self.request(httpx.Response(204), method='PUT')
        self.assertEqual(result['http_status'], 204)
        self.assertEqual(self.requests[0].method, 'PUT')

    async def test_safe_field_errors_reach_model(self):
        result = await self.request(httpx.Response(400, json={'code': 'invalid_request',
            'message': 'Invalid booking information.', 'errors': {'custom_fields': ['Must be an object.']}}))
        self.assertIn('custom_fields', result['errors'])
        self.assertFalse(result['retryable'])

    async def test_raw_database_errors_are_not_returned(self):
        result = await self.request(httpx.Response(400, json={'message': 'database secret customer@example.com'}))
        self.assertNotIn('secret', json.dumps(result))

    async def test_timeout_reports_unknown_outcome(self):
        result = await self.request(error=httpx.ReadTimeout('sensitive details'))
        self.assertTrue(result['outcome_unknown'])
        self.assertNotIn('sensitive', json.dumps(result))


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def summarize(self, message=None, initialization_error=None):
        settings = SimpleNamespace(ai_model=lambda purpose: 'test-model', gemini_api_key=None,
                                   grok_api_key=None, deepseek_api_key=None)
        db = AsyncMock()
        db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=settings))
        session = AsyncMock()
        session.__aenter__.return_value = db
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=message))
        with patch.object(openai_summary, 'AsyncSessionLocal', return_value=session), \
             patch.object(openai_summary, 'get_llm', return_value=model, side_effect=initialization_error):
            return await openai_summary.generate_call_summary([{'role': 'user', 'text': 'Hello'}])

    async def test_string_and_block_outputs(self):
        for content in (' Summary. ', [{'type': 'reasoning', 'summary': []}, {'type': 'text', 'text': ' Summary. '}]):
            self.assertEqual(await self.summarize(AIMessage(content=content)), 'Summary.')

    async def test_empty_output_has_safe_fallback(self):
        self.assertIn('transcript has been saved', await self.summarize(AIMessage(content=[])))

    async def test_model_initialization_failure_has_safe_fallback(self):
        result = await self.summarize(initialization_error=ValueError('secret-key'))
        self.assertNotIn('secret-key', result)
        self.assertIn('transcript has been saved', result)

    async def test_policy_lookup_failure_has_safe_fallback(self):
        with patch.object(openai_summary.LifetimeRuntime, 'context', AsyncMock(side_effect=RuntimeError('secret'))):
            result = await openai_summary.generate_call_summary([{'role': 'user', 'text': 'Hi'}], business_id='biz')
        self.assertIn('transcript has been saved', result)


if __name__ == '__main__':
    unittest.main()


class LocationToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_booking_schema_gets_location_fields_without_obsolete_addresses(self):
        source = config(json_schema={'type': 'object', 'properties': {'address': {'type': 'string'}}, 'required': ['address']})
        tool = ToolFactory.create_external_tool(source)
        schema = convert_to_openai_function(tool)['parameters']
        self.assertNotIn('address', schema['properties'])
        self.assertNotIn('address', schema['required'])
        self.assertIn('country_code', schema['properties']['service_address']['required'])
        with patch('agents.tools.factory.execute_external_api', AsyncMock(return_value='{}')) as execute:
            await tool.ainvoke({'location_type': 'onsite', 'service_address': {'line1': 'A property', 'country_code': 'PK'}})
            execute.assert_awaited_once()

    async def test_existing_agent_receives_live_options_tool_and_rules(self):
        from agents.tools import get_tools
        from agents.base import BaseAgent
        tool_config = config(tool_type='webhook')
        agent_config = SimpleNamespace(id=1, business_id='biz', tools=[tool_config])
        with patch('agents.tools.create_internal_tools', return_value=[]):
            tools = get_tools(agent_config, call_sid='call-one')
        self.assertEqual([tool.name for tool in tools].count('get_service_location_options'), 1)
        agent = BaseAgent(model_name='test', openai_api_key='test', system_prompt='Old script: collect address.',
                          tools=tools, realtime_only=True)
        self.assertIn('override generic address-collection scripts', agent.base_prompt_text)
        self.assertIn('virtual: do not collect a physical address', agent.base_prompt_text)

    async def test_meeting_url_is_not_an_agent_supplied_parameter(self):
        schema = convert_to_openai_function(ToolFactory.create_external_tool(config()))['parameters']
        self.assertNotIn('meeting_url', schema['properties'])


class ClientTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_timezone_is_bound_consistently_to_both_booking_tools(self):
        for name, endpoint in (('bookAppointment', 'create-booking'), ('check_availability', 'availability')):
            with self.subTest(name=name):
                source = config(name=name, url=f'https://example.invalid/bookings/api/{endpoint}/',
                                json_schema={'type': 'object', 'properties': {}})
                tool = ToolFactory.create_external_tool(source, client_timezone='Asia/Karachi')
                with patch('agents.tools.factory.execute_external_api', AsyncMock(return_value='{}')) as execute:
                    await tool.ainvoke({'timezone': 'America/New_York'})
                self.assertEqual(execute.call_args.kwargs['payload']['timezone'], 'Asia/Karachi')

    async def test_telephone_availability_accepts_known_client_locality(self):
        source = config(name='check_availability', url='https://example.invalid/bookings/api/availability/',
                        json_schema={'type': 'object', 'properties': {}, 'additionalProperties': False})
        tool = ToolFactory.create_external_tool(source)
        with patch('agents.tools.factory.execute_external_api', AsyncMock(return_value='{}')) as execute:
            await tool.ainvoke({'client_location': 'Karachi, Pakistan'})
        self.assertEqual(execute.call_args.kwargs['payload']['client_location'], 'Karachi, Pakistan')

    async def test_live_rules_do_not_ask_for_location_or_timezone_selection(self):
        from agents.location import LOCATION_AGENT_RULES
        self.assertIn('exactly one appointment location type', LOCATION_AGENT_RULES)
        self.assertIn('Do not ask the customer to select a timezone', LOCATION_AGENT_RULES)
        self.assertNotIn("ask for the customer's timezone", LOCATION_AGENT_RULES)
