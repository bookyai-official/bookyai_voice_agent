import logging
from typing import List, Any, Optional
from sqlalchemy.future import select
from core.config import settings
from core.database import AsyncSessionLocal
from agents.factory import AgentFactory
from models.conversation import Message
from services.chat_service import save_message

logger = logging.getLogger(__name__)

async def _load_history_from_db(chat_id: int) -> List[Message]:
    """Helper to load history for a chat."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at)
        )
        return result.scalars().all()

async def get_chat_response(
    agent_id: int,
    chat_id: int,
    user_message: str,
    additional_context: str = "",
    channel: str = "text"
) -> str:
    """
    Unified bridge service to get a response from a LangChain Agent.
    Handles message persistence and history loading for any text-based channel.
    
    Args:
        agent_id: ID of the agent
        chat_id: ID of the conversation
        user_message: Current user message
        additional_context: Runtime context (e.g. Lead Info)
        channel: 'text' or 'voice' (determines which agent class to use)
        
    Returns:
        The agent's text response.
    """
    # 1. Save user message to DB first
    await save_message(chat_id, "user", user_message)

    # 2. Create Agent via Factory
    if channel == "voice":
        agent = await AgentFactory.create_voice_agent(
            agent_id=agent_id,
            openai_api_key=settings.OPENAI_API_KEY
        )
    else:
        # Default to SMS/Text Agent
        agent = await AgentFactory.create_sms_agent(
            agent_id=agent_id,
            openai_api_key=settings.OPENAI_API_KEY
        )
    
    # 3. Use chat_id as thread_id for persistence
    thread_id = str(chat_id)
    
    # 4. Load History from DB and hydrate the Agent Checkpointer
    history = await _load_history_from_db(chat_id)
    if hasattr(agent, "hydrate_history"):
        await agent.hydrate_history(thread_id, history)
    
    # 5. Execute Agent (LangChain)
    response = await agent.ask(user_message, thread_id, additional_context)
    
    # 6. Save assistant response to DB
    await save_message(chat_id, "assistant", response)
    
    return response

# Alias for backward compatibility
get_sms_response = get_chat_response
