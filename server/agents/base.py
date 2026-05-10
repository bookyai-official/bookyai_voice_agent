import logging
import datetime
import warnings
from typing import List, Any, Dict, Optional, TYPE_CHECKING
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import BaseTool

from agents.prompts import SYSTEM_PROMPT_TEMPLATE
from agents.llm_utils import get_llm

if TYPE_CHECKING:
    from rag.retriever import KnowledgeRetriever

# Suppress noisy LangChain/LangGraph deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")
# Specific fix for the user's reported warning
try:
    from langchain_core._api import LangChainPendingDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
except ImportError:
    pass

logger = logging.getLogger(__name__)

class BaseAgent:
    """
    Unified Base Agent Core.
    Handles the common logic for both SMS and Voice channels.
    """

    def __init__(
        self,
        model_name: str,
        openai_api_key: str,
        system_prompt: str,
        tools: List[BaseTool],
        channel: str = "text",
        memory_k: int = 5,
        temperature: float = 0.7,
        business_id: Optional[int] = None,
        retriever: Optional["KnowledgeRetriever"] = None,
        **kwargs
    ):
        """
        Initialize the agent with configuration.

        Args:
            model_name: OpenAI model identifier (e.g., 'gpt-4o-mini')
            openai_api_key: API key for OpenAI
            system_prompt: Compiled system instructions from the database
            tools: List of LangChain tool instances
            channel: 'text' or 'voice' to handle formatting hints
            memory_k: Number of conversation turns to remember
            temperature: LLM temperature setting
            business_id: Optional business ID for RAG retrieval scoping
            retriever: Optional KnowledgeRetriever instance for RAG context injection
        """
        self.channel = channel
        self.tools = tools
        self.model_name = model_name
        self.business_id = business_id
        self._retriever = retriever
        
        # 1. Initialize LLM using the utility (supports multiple providers)
        self.llm = get_llm(
            model_name=model_name,
            temperature=temperature,
            openai_api_key=openai_api_key,
            **kwargs
        )

        # 2. Initialize Memory (Persistence)
        # We only use checkpointer for Voice/Realtime if needed, 
        # but for text-based we will pass history manually from the DB.
        self.checkpointer = InMemorySaver()

        # 3. Create the Agent using create_agent
        # For SMS/Chat, we will pass history manually in the invoke call
        self.agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer if channel == "voice" else None
        )

        # Store the base prompt text
        self.base_prompt_text = system_prompt

    async def hydrate_history(self, thread_id: str, history: List[Any]):
        """
        Note: This is now a no-op for text channels as we pass history directly in run().
        Keeping for interface compatibility.
        """
        pass

    async def ask(self, user_input: str, thread_id: str, additional_context: str = "", history: List[Any] = None) -> str:
        """Standard interface for getting a response."""
        return await self.run(user_input, thread_id, additional_context, history)

    async def run(self, user_input: str, thread_id: str, additional_context: str = "", history: List[Any] = None) -> str:
        """
        Execute the agent loop with a user message and DB-provided history.
        """
        now = datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
        
        # RAG retrieval: fetch relevant knowledge base context
        rag_context = await self._retrieve_rag_context(user_input)
        
        # Merge RAG context with any existing additional_context
        merged_context = self._merge_context(additional_context, rag_context)
        
        # Inject context into the input if provided
        full_input = user_input
        if merged_context:
            full_input = f"CONTEXT:\n{merged_context}\n\nUSER MESSAGE:\n{user_input}"

        
        # Convert DB history to LangChain messages
        lc_history = []
        if history:
            from langchain_core.messages import HumanMessage, AIMessage
            for msg in history:
                role = "USER" if msg.role == "user" else "AGENT"
                content = msg.content
                print(f"  [{role} (DB)]: {content[:100]}...")
                if msg.role == "user":
                    lc_history.append(HumanMessage(content=content))
                elif msg.role == "assistant":
                    lc_history.append(AIMessage(content=content))
        

        try:
            # Prepare input: System prompt is already in the agent, 
            # we just pass history + current message.
            input_data = {"messages": lc_history + [("user", full_input)]}
            
            config = {"configurable": {"thread_id": thread_id}}
            
            # Execute agent
            result = await self.agent.ainvoke(input_data, config=config)
            
            # Extract last message from result
            if "messages" in result and len(result["messages"]) > 0:
                response = result["messages"][-1].content
                print(f"DEBUG: [AGENT RESPONSE]: {response[:200]}...")
                return response
            
            return "I'm sorry, I couldn't generate a response."
        
        except Exception as e:
            logger.error(f"[BASE AGENT] Error during execution: {e}", exc_info=True)
            return "I apologize, but I encountered an error processing your request."

    # ── RAG Integration ─────────────────────────────────────────────────────

    async def _retrieve_rag_context(self, user_message: str) -> str:
        """
        Retrieve relevant knowledge base context for the user's message.

        Silently returns empty string when:
            - No retriever is configured (agent created without RAG)
            - No business_id is set on this agent
            - Retrieval fails for any reason

        Args:
            user_message: The current user input to search against.

        Returns:
            Formatted context string, or "" if no relevant context found.
        """
        if not self._retriever or not self.business_id:
            return ""

        try:
            from core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                context = await self._retriever.retrieve_with_scores(
                    query=user_message,
                    business_id=str(self.business_id),
                    db=db,
                    top_k=4,
                    score_threshold=0.7,
                )
            return context
        except Exception as e:
            logger.warning("[BASE AGENT] RAG retrieval failed: %s", e)
            return ""

    @staticmethod
    def _merge_context(additional_context: str, rag_context: str) -> str:
        """
        Merge explicit additional_context with retrieved RAG context.

        RAG context is placed under a clearly labelled section so the
        LLM can distinguish it from other runtime context.

        Args:
            additional_context: Existing context (e.g. lead info).
            rag_context:        Retrieved knowledge base chunks.

        Returns:
            Combined context string.
        """
        parts: List[str] = []

        if additional_context:
            parts.append(additional_context)

        if rag_context:
            rag_block = (
                "## Knowledge Base\n"
                "Use the following information to answer accurately.\n"
                "Only use this if it is relevant to the user's question.\n\n"
                f"{rag_context}"
            )
            parts.append(rag_block)

        return "\n\n".join(parts)

    # ── Tool Schemas ──────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Returns OpenAI-compatible tool schemas for use in Realtime API sessions.
        """
        from langchain_core.utils.function_calling import convert_to_openai_function
        return [
            {
                "type": "function",
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["parameters"]
            }
            for schema in [convert_to_openai_function(t) for t in self.tools]
        ]
