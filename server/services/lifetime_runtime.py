"""Private Django billing bridge. No customer key is stored in this process's global config."""
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal


class RuntimeDenied(Exception):
    def __init__(self, message, status_code=403):
        super().__init__(message)
        self.status_code = status_code


class LifetimeRuntime:
    @staticmethod
    async def has_license(business_id):
        async with AsyncSessionLocal() as db:
            result = await db.execute(text('SELECT id FROM subscription_lifetimelicense WHERE business_id = :business_id'),
                                      {'business_id': str(business_id)})
            return result.first() is not None

    @staticmethod
    async def request(business_id, action='context', **fields):
        base = settings.BOOKY_BILLING_BASE_URL.rstrip('/')
        parsed = urlparse(base)
        if (not base or len(settings.AI_RUNTIME_TOKEN) < 32 or
                (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', 'testserver')))):
            raise RuntimeDenied('The lifetime AI service connection is not configured. Ask your administrator to configure it and restart the AI service.', status_code=503)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(f'{base}/subscription/internal/ai-runtime/',
                    headers={'X-Booky-Runtime-Token': settings.AI_RUNTIME_TOKEN},
                    json={'business_id': str(business_id), 'action': action, **fields})
                if response.status_code == 401:
                    raise RuntimeDenied('The lifetime AI service credentials do not match. Ask your administrator to check the shared runtime token.', status_code=503)
                if 300 <= response.status_code < 400 or response.status_code == 404 or response.status_code >= 500:
                    raise RuntimeDenied('The lifetime license service is unavailable. Please retry or contact your administrator.', status_code=503)
                if response.status_code != 200:
                    raise RuntimeDenied('AI is unavailable. Check your lifetime license, API key, and usage allowance.')
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeDenied('Unable to connect to the lifetime license service. Please retry.', status_code=503) from None

    @classmethod
    async def context(cls, business_id, purpose=None, feature=None):
        if not await cls.has_license(business_id):
            return None  # Preserve existing subscription behavior.
        result = await cls.request(business_id, purpose=purpose, feature=feature)
        if result.get('source') == 'subscription':
            return None
        if result.get('source') != 'appsumo' or not result.get('active'):
            raise RuntimeDenied('Your lifetime license is inactive.')
        return result

    @classmethod
    async def reserve(cls, business_id, operation_key, usage_type='sms', units=1, partial=False):
        result = await cls.request(business_id, action='reserve', operation_key=operation_key,
                                   usage_type=usage_type, units=units, partial=partial)
        return result['reserved_units']

    @classmethod
    async def reserve_context(cls, business_id, operation_key, purpose='text', usage_type='sms', units=1, partial=False, feature=None):
        """Return credentials bound to the funding source actually debited."""
        return await cls.request(business_id, action='reserve', operation_key=operation_key,
                                 purpose=purpose, usage_type=usage_type, units=units,
                                 partial=partial, feature=feature)

    @classmethod
    async def settle(cls, business_id, operation_key, units):
        return await cls.request(business_id, action='settle', operation_key=operation_key, units=units)
