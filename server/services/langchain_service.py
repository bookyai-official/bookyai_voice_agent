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
    # 1. Create Agent via Factory
    print(f"[LANGCHAIN DEBUG] Creating agent for Agent ID {agent_id} (Channel: {channel})...")
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
    
    # 2. Use chat_id as thread_id for persistence
    thread_id = str(chat_id)
    
    # 3. Load History from DB BEFORE saving the current message
    #    (prevents the current message from appearing in both history and input)
    history = await _load_history_from_db(chat_id)
    print(f"[LANGCHAIN DEBUG] Loaded {len(history)} messages from history for Chat ID {chat_id}")
    if hasattr(agent, "hydrate_history"):
        await agent.hydrate_history(thread_id, history)

    # 4. Save user message to DB (after loading history to avoid duplication)
    await save_message(chat_id, "user", user_message)
    
    # 5. Execute Agent (LangChain) with DB History
    print(f"[LANGCHAIN DEBUG] Invoking agent for Chat ID {chat_id} with user message: {user_message[:50]}...")
    response = await agent.ask(user_message, thread_id, additional_context, history=history)
    print(f"[LANGCHAIN DEBUG] Agent Response for Chat {chat_id}: {response[:50]}...")
    
    # 6. Save assistant response to DB
    await save_message(chat_id, "assistant", response)
    
    return response

# Alias for backward compatibility
get_sms_response = get_chat_response
