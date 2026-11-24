import json
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


async def execute_external_api(url: str, method: str, timeout: int,
                               payload: Dict[str, Any], idempotency_key=None) -> str:
    """Execute once; preserve success and safe field errors without guessing retry outcomes."""
    try:
        kwargs = {'timeout': float(timeout)}
        if idempotency_key:
            kwargs['headers'] = {'Idempotency-Key': idempotency_key}
        if method.upper() == 'GET':
            kwargs['params'] = payload
        else:
            kwargs['json'] = payload
        async with httpx.AsyncClient() as client:
            response = await client.request(method.upper(), url, **kwargs)
        if 200 <= response.status_code < 300:
            if not response.content:
                return json.dumps({'status': 'success', 'http_status': response.status_code})
            try:
                return json.dumps(response.json())
            except ValueError:
                return json.dumps({'status': 'success', 'raw_response': response.text})

        logger.warning('External tool request failed (http_status=%s).', response.status_code)
        result = {'status': 'error', 'http_status': response.status_code,
                  'message': 'The service could not complete the request.', 'retryable': False}
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get('code') in {
            'invalid_request', 'idempotency_conflict', 'booking_failed',
        }:
            result['code'] = body['code']
            result['message'] = body.get('message') or result['message']
            if isinstance(body.get('errors'), dict):
                result['errors'] = body['errors']
        if response.status_code >= 500:
            result['outcome_unknown'] = True
            result['message'] = 'The service reported an error. Verify the booking outcome before retrying; reuse the same booking request key.'
        return json.dumps(result)
    except (httpx.TimeoutException, httpx.TransportError):
        logger.warning('External tool transport failed; request outcome may be unknown.')
        return json.dumps({'status': 'error', 'code': 'outcome_unknown',
            'message': 'Request outcome is unknown. Verify the booking before retrying; reuse the same booking request key.',
            'outcome_unknown': True, 'retryable': False})
    except Exception as exc:
        logger.error('External tool execution failed (exception=%s).', type(exc).__name__)
        return json.dumps({'status': 'error', 'code': 'execution_failed',
            'message': 'Tool execution failed. Verify the outcome before retrying.', 'retryable': False})
