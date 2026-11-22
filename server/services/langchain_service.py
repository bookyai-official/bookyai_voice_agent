import logging
from typing import List, Any, Optional
from sqlalchemy.future import select
from core.config import settings
from core.database import AsyncSessionLocal
from agents.factory import AgentFactory
from models.conversation import Message
from services.chat_service import save_message
from services.lifetime_runtime import LifetimeRuntime, RuntimeDenied
from uuid import uuid4

logger = logging.getLogger(__name__)

async def _load_history_from_db(chat_id: int, exclude_message_id=None) -> List[Message]:
    """Helper to load history for a chat."""
    async with AsyncSessionLocal() as db:
        query = select(Message).where(Message.chat_id == chat_id)
        if exclude_message_id is not None:
            query = query.where(Message.id != exclude_message_id)
        result = await db.execute(query.order_by(Message.created_at))
        return result.scalars().all()

async def get_chat_response(
    agent_id: int,
    chat_id: int,
    user_message: str,
    additional_context: str = "",
    channel: str = "text",
    feature: str = 'webchat_agent',
    operation_key: str | None = None,
    persist_user_message: bool = True,
    persist_assistant_message: bool = True,
    current_message_id: int | None = None,
    billing_context: dict | None = None,
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
    logger.debug('Creating agent id=%s channel=%s', agent_id, channel)
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
    
    policy = await LifetimeRuntime.context(agent.business_id, purpose='text', feature=feature) if agent.runtime_policy else None
    if policy and (len(user_message) > 16000 or len(additional_context) > 8000):
        raise RuntimeDenied('This message is too long. Please shorten it.')
    if billing_context is not None:
        billing_context['precharged'] = bool(policy)
    operation = (operation_key or f'chat:{uuid4().hex}') if policy else None
    if policy:
        await LifetimeRuntime.reserve(agent.business_id, operation)
        # Charge before execution. Ambiguous failures must not create free unlimited provider retries.
        await LifetimeRuntime.settle(agent.business_id, operation, 1)

    # 2. Use chat_id as thread_id for persistence
    thread_id = str(chat_id)
    
    # 3. Load History from DB BEFORE saving the current message
    #    (prevents the current message from appearing in both history and input)
    history = await _load_history_from_db(chat_id, exclude_message_id=current_message_id)
    logger.debug('Loaded history for chat id=%s', chat_id)
    if hasattr(agent, "hydrate_history"):
        await agent.hydrate_history(thread_id, history)

    # 4. Save user message to DB (after loading history to avoid duplication)
    if persist_user_message:
        await save_message(chat_id, "user", user_message)
    
    # 5. Execute Agent (LangChain) with DB History
    response = await agent.ask(user_message, thread_id, additional_context, history=history)
    
    # 6. Save assistant response to DB
    if persist_assistant_message:
        await save_message(chat_id, "assistant", response)
    
    return response

# Alias for backward compatibility
get_sms_response = get_chat_response
