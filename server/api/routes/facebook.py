"""Compatibility webhook URL; uses the same signed, durable ingress."""
from fastapi import APIRouter, Request
from api.routes.meta import receive, verification

router = APIRouter(prefix='/facebook', tags=['Meta compatibility'])


@router.api_route('/webhook', methods=['GET', 'POST'])
async def facebook_webhook(request: Request):
    return await verification(request) if request.method == 'GET' else await receive(request)
