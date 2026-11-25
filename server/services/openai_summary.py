import logging
import datetime
from typing import List, Dict
from sqlalchemy.future import select
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_utils import get_llm

from core.config import settings
from core.database import AsyncSessionLocal
from models.system import SystemSetting
from services.lifetime_runtime import LifetimeRuntime
from uuid import uuid4

logger = logging.getLogger(__name__)

async def generate_call_summary(transcript: List[Dict[str, str]], business_id=None) -> str:
    """
    Generates a concise summary of the call transcript using LangChain and ChatOpenAI.
    """
    if not transcript:
        return "No transcript available for summary."

    policy = None
    try:
        policy = await LifetimeRuntime.context(business_id, purpose='summary', feature='calling_agent') if business_id is not None else None
        # The configured summary model selects its own credential in get_llm.
        # Gemini summaries must not require a platform OpenAI key.

        # 1. Format transcript for the prompt
        formatted_transcript = ""
        for entry in transcript:
            role = entry.get("role", "unknown")
            text = entry.get("text", "")
            formatted_transcript += f"{role.upper()}: {text}\n"

        # 2. Fetch dynamic model configuration
        async with AsyncSessionLocal() as db_session:
            system_setting = await db_session.execute(select(SystemSetting))
            system_setting = system_setting.scalar_one_or_none() or SystemSetting()
            current_model = system_setting.ai_model('summary')

        # 3. Initialize LLM via utility (supports multiple providers)
        if policy:
            operation = f'summary:{uuid4().hex}'
            reserved = await LifetimeRuntime.reserve_context(business_id, operation, purpose='summary', feature='calling_agent')
            policy.update(reserved)
            await LifetimeRuntime.settle(business_id, operation, 1)
            formatted_transcript = formatted_transcript[:40000]
        chat_model = get_llm(
            model_name=policy['model'] if policy else current_model,
            temperature=0.5,
            openai_api_key=policy['api_key'] if policy else settings.OPENAI_API_KEY,
            strict_credentials=bool(policy),
            gemini_api_key=system_setting.gemini_api_key if system_setting else None,
            grok_api_key=system_setting.grok_api_key if system_setting else None,
            deepseek_api_key=system_setting.deepseek_api_key if system_setting else None,
            max_tokens=300
        )

        system_content = f"Current Date and Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%A, %B %d, %Y, %I:%M %p UTC')}. You are a helpful assistant that summarizes call transcripts."
        user_content = (
            "You are an assistant that summarizes voice call transcripts. "
            "Provide a concise summary of the following conversation between a user and an AI agent. "
            "Highlight key points, requests made, and any outcomes.\n\n"
            f"TRANSCRIPT:\n{formatted_transcript}\n\n"
            "SUMMARY:"
        )

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content)
        ]
        
        response = await chat_model.ainvoke(messages)
        summary = str(response.text).strip()
        if not summary:
            raise ValueError('The summary model returned no text.')
        return summary

    except Exception as e:
        if policy:
            logger.error('Lifetime summary generation failed; provider details withheld.')
            return 'Summary unavailable. Check AI settings and usage allowance.'
        logger.error('Call summary generation failed (exception=%s).', type(e).__name__)
        return 'Summary unavailable. The call transcript has been saved.'
