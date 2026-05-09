import httpx
import logging
import json
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def execute_external_api(
    url: str, 
    method: str, 
    timeout: int, 
    payload: Dict[str, Any]
) -> str:
    """
    Core executor for external API webhooks.
    
    Args:
        url: Target endpoint URL
        method: HTTP method (GET, POST, etc.)
        timeout: Request timeout in seconds
        payload: The arguments passed by the LLM
        
    Returns:
        JSON string response from the endpoint or an error message.
    """
    try:
        async with httpx.AsyncClient() as client:
            request_kwargs = {"timeout": float(timeout)}
            
            if method.upper() == "GET":
                request_kwargs["params"] = payload
                response = await client.get(url, **request_kwargs)
            else:
                request_kwargs["json"] = payload
                response = await client.post(url, **request_kwargs)
            
            if response.status_code == 200:
                try:
                    return json.dumps(response.json())
                except ValueError:
                    return json.dumps({"status": "success", "raw_response": response.text})
            else:
                logger.error(f"External API {url} returned {response.status_code}: {response.text}")
                return json.dumps({"error": f"API returned status code {response.status_code}"})

    except httpx.ReadTimeout:
        logger.error(f"External API {url} timed out.")
        return json.dumps({"error": "Request timed out."})
    except Exception as e:
        logger.exception(f"Unexpected error calling external API {url}")
        return json.dumps({"error": f"Internal execution error: {str(e)}"})
