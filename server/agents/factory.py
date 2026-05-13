import logging
from typing import Optional, Any
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from models.business import BusinessConfiguration
from models.system import SystemSetting
from agents.sms_agent import SMSAgent
from agents.voice_agent import VoiceAgent
from agents.tools import get_tools
from rag.retriever import KnowledgeRetriever

logger = logging.getLogger(__name__)

class AgentFactory:
    """
    Factory to create and configure specific agents for different channels.
    """

    @staticmethod
    async def create_sms_agent(
        agent_id: int, 
        openai_api_key: str,
        twilio_client: Optional[Any] = None,
        call_sid: Optional[str] = None
    ) -> SMSAgent:
        """
        Loads agent configuration from DB and returns a configured SMSAgent.
        """
        async with AsyncSessionLocal() as session:
            # 1. Fetch Agent and Tools
            result = await session.execute(
                select(AIAgent)
                .options(selectinload(AIAgent.tools))
                .where(AIAgent.id == agent_id)
            )
            agent_config = result.scalar_one_or_none()
            
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found.")

            # 2. Fetch System Settings for Model Names
            sys_result = await session.execute(select(SystemSetting).limit(1))
            sys_settings = sys_result.scalar_one_or_none()
            text_model = sys_settings.text_model if sys_settings else "gpt-5.4-mini"

            # 3. Get Tools
            tools = get_tools(agent_config, twilio_client, call_sid)

            # 4. Instantiate SMSAgent with RAG retriever
            return SMSAgent(
                model_name=text_model,
                openai_api_key=openai_api_key,
                system_prompt=agent_config.get_compiled_prompt(),
                tools=tools,
                temperature=agent_config.temperature or 0.7,
                business_id=agent_config.business_id,
                retriever=KnowledgeRetriever,
                gemini_api_key=sys_settings.gemini_api_key if sys_settings else None,
                grok_api_key=sys_settings.grok_api_key if sys_settings else None,
                deepseek_api_key=sys_settings.deepseek_api_key if sys_settings else None
            )

    @staticmethod
    async def create_voice_agent(
        agent_id: int,
        openai_api_key: str,
        twilio_client: Optional[Any] = None,
        call_sid: Optional[str] = None
    ) -> VoiceAgent:
        """
        Loads agent configuration from DB and returns a configured VoiceAgent.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AIAgent)
                .options(selectinload(AIAgent.tools))
                .where(AIAgent.id == agent_id)
            )
            agent_config = result.scalar_one_or_none()
            
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found.")

            # 2. Fetch System Settings for Model Names
            sys_result = await session.execute(select(SystemSetting).limit(1))
            sys_settings = sys_result.scalar_one_or_none()
            realtime_model = sys_settings.realtime_llm_model if sys_settings else "gpt-realtime-2025-08-28"

            # 3. Get Tools
            tools = get_tools(agent_config, twilio_client, call_sid)

            # 4. Instantiate VoiceAgent with RAG retriever
            return VoiceAgent(
                model_name=realtime_model,
                openai_api_key=openai_api_key,
                system_prompt=agent_config.get_compiled_prompt(),
                tools=tools,
                temperature=agent_config.temperature or 0.8,
                voice=agent_config.voice or "alloy",
                vad_threshold=agent_config.vad_threshold or 0.5,
                silence_duration_ms=agent_config.silence_duration_ms or 1000,
                business_id=agent_config.business_id,
                retriever=KnowledgeRetriever,
                gemini_api_key=sys_settings.gemini_api_key if sys_settings else None,
                grok_api_key=sys_settings.grok_api_key if sys_settings else None,
                deepseek_api_key=sys_settings.deepseek_api_key if sys_settings else None
            )
