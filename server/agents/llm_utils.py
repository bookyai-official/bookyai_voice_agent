import logging
from typing import Any
from langchain_openai import ChatOpenAI
from core.config import settings

logger = logging.getLogger(__name__)

def get_llm(model_name: str, temperature: float = 0.7, **kwargs) -> Any:
    """
    Returns a LangChain Chat Model instance based on the model name.
    Supported providers: OpenAI, Google (Gemini), DeepSeek, xAI (Grok).
    """
    
    # Extract API keys from kwargs or settings
    openai_key = kwargs.get("openai_api_key") or settings.OPENAI_API_KEY
    gemini_key = kwargs.get("gemini_api_key")
    grok_key = kwargs.get("grok_api_key")
    deepseek_key = kwargs.get("deepseek_api_key")

    model_lower = model_name.lower()

    # 1. Google Gemini
    if "gemini" in model_lower:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=gemini_key,
                temperature=temperature
            )
        except ImportError:
            logger.warning("langchain-google-genai not installed. Falling back to OpenAI if possible.")
    
    # 2. DeepSeek (Using OpenAI compatible client)
    if "deepseek" in model_lower:
        return ChatOpenAI(
            model=model_name,
            openai_api_key=deepseek_key or openai_key,
            base_url="https://api.deepseek.com",
            temperature=temperature
        )

    # 3. xAI Grok (Using OpenAI compatible client)
    if "grok" in model_lower:
        return ChatOpenAI(
            model=model_name,
            openai_api_key=grok_key or openai_key,
            base_url="https://api.x.ai/v1",
            temperature=temperature
        )

    # 4. Default to OpenAI
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        openai_api_key=openai_key
    )
