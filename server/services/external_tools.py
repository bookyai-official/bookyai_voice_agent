import httpx
import logging
import json
from core.config import settings

logger = logging.getLogger(__name__)

async def execute_tool(url: str, method: str, timeout_seconds: int, arguments: str) -> str:
    """
    Executes an external tool using configured dynamic params.
    """
    try:
        # The arguments arrive as a JSON string from OpenAI
        args_dict = json.loads(arguments)
        
        async with httpx.AsyncClient() as client:
            request_kwargs = {"timeout": float(timeout_seconds)}
            if method.upper() == "GET":
                request_kwargs["params"] = args_dict
                response = await client.get(url, **request_kwargs)
            else:
                request_kwargs["json"] = args_dict
                response = await client.post(url, **request_kwargs)
            
            if response.status_code == 200:
                result = response.json()
                # Must return result as string so we can pass it back to OpenAI
                return json.dumps(result)
            else:
                logger.error(f"Tool at {url} returned {response.status_code}: {response.text}")
                return json.dumps({"error": "Failed to execute external api on backend."})

    except httpx.ReadTimeout:
        logger.error(f"Tool at {url} timed out.")
        return json.dumps({"error": "Tool execution timed out."})
    except json.JSONDecodeError:
        logger.error(f"Failed to decode arguments for tool at {url}: {arguments}")
        return json.dumps({"error": "Invalid arguments format."})
    except Exception as e:
        logger.exception(f"Unexpected error executing tool at '{url}'")
        return json.dumps({"error": f"Internal execution error: {str(e)}"})
