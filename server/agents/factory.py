import logging
from typing import Optional, Any, Tuple
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from models.business import BusinessConfiguration
from models.system import SystemSetting
from agents.sms_agent import SMSAgent
from agents.voice_agent import VoiceAgent
from agents.tools import get_tools
from rag.retriever import KnowledgeRetriever
from services.lifetime_runtime import LifetimeRuntime
from services.realtime_voices import resolve_realtime_voice
from services.realtime_provider import (
    RealtimeProviderError, get_realtime_client_class, get_realtime_provider,
)

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
            sys_settings = sys_result.scalar_one_or_none() or SystemSetting()
            text_model = sys_settings.ai_model('text')
            policy = await LifetimeRuntime.context(agent_config.business_id, purpose='text')
            if policy:
                openai_api_key, text_model = policy['api_key'], policy['model']

            # 3. Get Tools
            tools = get_tools(agent_config, twilio_client, call_sid)

            # 4. Instantiate SMSAgent with RAG retriever
            instance = SMSAgent(
                model_name=text_model,
                openai_api_key=openai_api_key,
                system_prompt=agent_config.get_compiled_prompt(),
                tools=tools,
                temperature=agent_config.temperature or 0.7,
                business_id=agent_config.business_id,
                retriever=KnowledgeRetriever,
                gemini_api_key=sys_settings.gemini_api_key if sys_settings else None,
                grok_api_key=sys_settings.grok_api_key if sys_settings else None,
                deepseek_api_key=sys_settings.deepseek_api_key if sys_settings else None,
                strict_credentials=bool(policy), max_tokens=1024 if policy else None,
            )
            instance.runtime_policy = policy
            instance.resolved_api_key = openai_api_key
            return instance

    @staticmethod
    async def get_voice_runtime_settings(
        business_id: str,
        session: AsyncSession,
    ) -> Tuple[SystemSetting, Optional[dict]]:
        """Load settings with the supplied DB session and reject unavailable voice providers."""
        result = await session.execute(select(SystemSetting).limit(1))
        sys_settings = result.scalar_one_or_none() or SystemSetting()
        policy = await LifetimeRuntime.context(
            business_id, purpose='realtime', feature='calling_agent'
        )
        realtime_model = policy['model'] if policy else sys_settings.ai_model('realtime')
        provider = get_realtime_provider(realtime_model)
        if provider == 'gemini':
            if policy:
                raise RealtimeProviderError(
                    'Lifetime AI currently supports OpenAI credentials only. Select an OpenAI call model.'
                )
            if not sys_settings.gemini_api_key or not sys_settings.gemini_api_key.strip():
                raise RealtimeProviderError('Configure the Gemini API key in System Settings.')
        get_realtime_client_class(realtime_model)
        return sys_settings, policy

    @staticmethod
    async def create_voice_agent(
        agent_id: int,
        openai_api_key: str,
        twilio_client: Optional[Any] = None,
        call_sid: Optional[str] = None,
        realtime_only: bool = False,
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

            # 2. Resolve the effective model and validate its realtime provider.
            sys_settings, policy = await AgentFactory.get_voice_runtime_settings(
                agent_config.business_id, session
            )
            realtime_model = sys_settings.ai_model('realtime')
            if policy:
                openai_api_key, realtime_model = policy['api_key'], policy['model']

            # 3. Get Tools
            tools = get_tools(agent_config, twilio_client, call_sid)

            # 4. Instantiate VoiceAgent with RAG retriever
            instance = VoiceAgent(
                model_name=realtime_model,
                openai_api_key=openai_api_key,
                system_prompt=agent_config.get_compiled_prompt(),
                tools=tools,
                temperature=agent_config.temperature or 0.8,
                voice=resolve_realtime_voice(realtime_model, agent_config.voice),
                vad_threshold=agent_config.vad_threshold or 0.5,
                silence_duration_ms=agent_config.silence_duration_ms or 1000,
                business_id=agent_config.business_id,
                retriever=KnowledgeRetriever,
                gemini_api_key=sys_settings.gemini_api_key if sys_settings else None,
                grok_api_key=sys_settings.grok_api_key if sys_settings else None,
                deepseek_api_key=sys_settings.deepseek_api_key if sys_settings else None,
                strict_credentials=bool(policy),
                realtime_only=realtime_only,
            )
            instance.runtime_policy = policy
            instance.resolved_api_key = (
                sys_settings.gemini_api_key.strip()
                if get_realtime_provider(realtime_model) == 'gemini' else openai_api_key
            )
            return instance
