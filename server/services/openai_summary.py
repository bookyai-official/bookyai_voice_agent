import logging
import datetime
from typing import List, Dict
from sqlalchemy.future import select
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from core.config import settings
from core.database import AsyncSessionLocal
from models.system import SystemSetting

logger = logging.getLogger(__name__)

async def generate_call_summary(transcript: List[Dict[str, str]]) -> str:
    """
    Generates a concise summary of the call transcript using LangChain and ChatOpenAI.
    """
    if not transcript:
        return "No transcript available for summary."

    if not settings.OPENAI_API_KEY:
        logger.error("OpenAI API Key is missing. Cannot generate summary.")
        return "Summary generation failed: Missing API Key."

    # 1. Format transcript for the prompt
    formatted_transcript = ""
    for entry in transcript:
        role = entry.get("role", "unknown")
        text = entry.get("text", "")
        formatted_transcript += f"{role.upper()}: {text}\n"

    # 2. Fetch dynamic model configuration
    async with AsyncSessionLocal() as db_session:
        system_setting = await db_session.execute(select(SystemSetting))
        system_setting = system_setting.scalar_one_or_none()
        current_model = system_setting.summary_model if system_setting and system_setting.summary_model else "gpt-4o-mini"

    # 3. Initialize LangChain Chat Model
    chat_model = ChatOpenAI(
        model=current_model,
        openai_api_key=settings.OPENAI_API_KEY,
        max_tokens=300,
        temperature=0.5
    )

    system_content = f"Current Date and Time: {datetime.datetime.now().strftime('%A, %B %d, %Y, %I:%M %p')}. You are a helpful assistant that summarizes call transcripts."
    user_content = (
        "You are an assistant that summarizes voice call transcripts. "
        "Provide a concise summary of the following conversation between a user and an AI agent. "
        "Highlight key points, requests made, and any outcomes.\n\n"
        f"TRANSCRIPT:\n{formatted_transcript}\n\n"
        "SUMMARY:"
    )

    try:
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content)
        ]
        
        response = await chat_model.ainvoke(messages)
        return response.content.strip()

    except Exception as e:
        logger.error(f"Error generating call summary via LangChain: {e}")
        return f"Summary generation failed: {str(e)}"
