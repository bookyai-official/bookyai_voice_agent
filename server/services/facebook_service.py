import logging
import aiohttp
from typing import Optional

logger = logging.getLogger(__name__)

class FacebookService:
    """
    Service to interact with the Facebook Graph API for Messenger.
    """
    
    BASE_URL = "https://graph.facebook.com/v19.0"

    @staticmethod
    async def send_message(page_access_token: str, recipient_id: str, text: str) -> bool:
        """
        Send a text message to a recipient via the Facebook Send API (Messenger).
        """
        url = f"{FacebookService.BASE_URL}/me/messages?access_token={page_access_token}"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text}
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    if response.status == 200:
                        logger.info("[FB SERVICE] Message sent successfully to %s", recipient_id)
                        return True
                    else:
                        logger.error("[FB SERVICE] Failed to send message: %s", data)
                        return False
        except Exception as e:
            logger.error("[FB SERVICE] Error sending message: %s", str(e))
            return False

    @staticmethod
    async def send_instagram_message(page_access_token: str, recipient_id: str, text: str) -> bool:
        """
        Send a text message to an Instagram recipient via the Instagram Messaging API.
        """
        url = f"{FacebookService.BASE_URL}/me/messages?access_token={page_access_token}"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text}
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    if response.status == 200:
                        logger.info("[IG SERVICE] Message sent successfully to %s", recipient_id)
                        return True
                    else:
                        logger.error("[IG SERVICE] Failed to send message: %s", data)
                        return False
        except Exception as e:
            logger.error("[IG SERVICE] Error sending message: %s", str(e))
            return False


    @staticmethod
    async def get_page_info(page_access_token: str) -> Optional[dict]:
        """
        Fetch basic info about the Facebook Page.
        """
        url = f"{FacebookService.BASE_URL}/me?fields=id,name&access_token={page_access_token}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        data = await response.json()
                        logger.error("[FB SERVICE] Failed to get page info: %s", data)
                        return None
        except Exception as e:
            logger.error("[FB SERVICE] Error getting page info: %s", str(e))
            return None
