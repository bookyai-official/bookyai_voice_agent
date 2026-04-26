import json
import logging
import httpx
from core.config import settings
from core.database import AsyncSessionLocal
from sqlalchemy.future import select
from models.system import SystemSetting

logger = logging.getLogger(__name__)

async def generate_call_summary(transcript: list) -> str:
    """
    Generates a concise summary of the call transcript using OpenAI Chat Completion.
    """
    if not transcript:
        return "No transcript available for summary."

    if not settings.OPENAI_API_KEY:
        logger.error("OpenAI API Key is missing. Cannot generate summary.")
        return "Summary generation failed: Missing API Key."

    # Format transcript for the prompt
    formatted_transcript = ""
    for entry in transcript:
        role = entry.get("role", "unknown")
        text = entry.get("text", "")
        formatted_transcript += f"{role.upper()}: {text}\n"

    prompt = (
        "You are an assistant that summarizes voice call transcripts. "
        "Provide a concise summary of the following conversation between a user and an AI agent. "
        "Highlight key points, requests made, and any outcomes.\n\n"
        f"TRANSCRIPT:\n{formatted_transcript}\n\n"
        "SUMMARY:"
    )

    try:
        # Fetch dynamic model configuration
        async with AsyncSessionLocal() as db_session:
            system_setting = await db_session.execute(select(SystemSetting))
            system_setting = system_setting.scalar_one_or_none()
            current_model = system_setting.summary_model if system_setting and system_setting.summary_model else "gpt-4o-mini"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": current_model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that summarizes call transcripts."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.5
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            summary = data["choices"][0]["message"]["content"].strip()
            return summary
    except Exception as e:
        logger.error(f"Error generating call summary: {e}")
        return f"Summary generation failed: {str(e)}"
