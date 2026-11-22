"""Compatibility facade. New callers must supply an explicit connected account."""
from services.meta_graph import send_message


class FacebookService:
    @staticmethod
    async def send_message(page_access_token, recipient_id, text, page_id=None):
        if not page_id:
            return False
        return (await send_message('messenger', page_id, page_access_token, recipient_id, text)).status == 'sent'

    @staticmethod
    async def send_instagram_message(page_access_token, recipient_id, text, instagram_account_id=None):
        if not instagram_account_id:
            return False
        return (await send_message('instagram', instagram_account_id, page_access_token, recipient_id, text)).status == 'sent'
