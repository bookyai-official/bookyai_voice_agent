"""Create tools without changing their configured JSON Schema contract."""
import hashlib
import json
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from jsonschema.validators import validator_for
from referencing import Registry
from langchain_core.tools import StructuredTool
from agents.tools.external import execute_external_api
from agents.location import upgrade_location_schema


class ToolFactory:
    @staticmethod
    def create_external_tool(tool_config: Any, operation_scope=None, client_timezone=None) -> StructuredTool:
        name = tool_config.name
        schema = deepcopy(tool_config.json_schema or {'type': 'object', 'properties': {}})
        endpoint = urlsplit(tool_config.url or '').path.rstrip('/')
        if name == 'bookAppointment' and endpoint == '/bookings/api/create-booking':
            schema = upgrade_location_schema(schema)
        elif name == 'check_availability' and endpoint == '/bookings/api/availability':
            fields = schema.setdefault('properties', {})
            fields.update({key: value for key, value in upgrade_location_schema({})['properties'].items()
                           if key in ('timezone', 'location_type', 'business_location_id', 'client_location', 'service_address')})
            fields.pop('customer_address', None)
        if schema.get('type', 'object') != 'object':
            raise ValueError('Tool input schema must describe an object.')
        # An empty registry rejects remote references instead of fetching arbitrary URLs.
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(schema, registry=Registry())
        scope = operation_scope or uuid4().hex
        is_booking = (name == 'bookAppointment' and
                      urlsplit(tool_config.url or '').path.rstrip('/') == '/bookings/api/create-booking')

        timed_booking_tool = endpoint in (
            '/bookings/api/create-booking', '/bookings/api/availability', '/bookings/api/reschedule-booking')
        if client_timezone:
            from zoneinfo import ZoneInfo
            ZoneInfo(client_timezone)  # Reject malformed session metadata before creating tools.

        async def tool_wrapper(**kwargs) -> str:
            if client_timezone and timed_booking_tool:
                kwargs['timezone'] = client_timezone
            errors = {}
            for error in validator.iter_errors(kwargs):
                path = '.'.join(str(part) for part in error.absolute_path) or 'arguments'
                # Do not echo argument values (which can contain personal information).
                if error.validator == 'required' and isinstance(error.instance, dict):
                    for field in error.validator_value:
                        if field not in error.instance:
                            field_path = f'{path}.{field}' if path != 'arguments' else field
                            errors[field_path] = ['This field is required.']
                else:
                    errors.setdefault(path, []).append(f'Invalid value for the configured {error.validator} constraint.')
            if errors:
                return json.dumps({'status': 'error', 'code': 'invalid_request',
                    'message': 'Correct the identified fields before trying again.', 'errors': errors,
                    'retryable': False})
            key = None
            if is_booking:
                # Stable across model retries, including changes to notes or optional fields.
                identity = {field: str(kwargs.get(field) or '').strip()
                            for field in ('business_id', 'service_id', 'booking_date', 'start_time', 'client_email')}
                identity['start_time'] = identity['start_time'][:5]
                identity['client_email'] = identity['client_email'].lower()
                key = hashlib.sha256(json.dumps([scope, identity], sort_keys=True).encode()).hexdigest()
            return await execute_external_api(
                url=tool_config.url, method=tool_config.method or 'POST',
                timeout=tool_config.timeout_seconds or 5, payload=kwargs,
                idempotency_key=key,
            )

        return StructuredTool.from_function(
            name=name, description=tool_config.description,
            coroutine=tool_wrapper, args_schema=schema,
        )
