import logging
import datetime
from typing import List, Any, Dict, Optional
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import BaseTool

from agents.prompts import SYSTEM_PROMPT_TEMPLATE

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
        temperature: float = 0.7
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
        """
        self.channel = channel
        self.tools = tools
        self.model_name = model_name
        
        # 1. Initialize LLM
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=openai_api_key
        )

        # 2. Initialize Memory (Persistence)
        self.checkpointer = MemorySaver()

        # 3. Create the Agent using create_agent from skill
        self.agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer
        )

        # Store the base prompt text for manual compilation if needed (e.g. for voice)
        self.base_prompt_text = system_prompt

    async def run(self, user_input: str, thread_id: str, additional_context: str = "") -> str:
        """
        Execute the agent loop with a user message.

        Args:
            user_input: The message from the customer
            thread_id: Unique identifier for the conversation session
            additional_context: Any runtime hints (e.g., Lead Info)

        Returns:
            The assistant's text response
        """
        now = datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
        
        # Inject context into the input if provided
        full_input = user_input
        if additional_context:
            full_input = f"CONTEXT:\n{additional_context}\n\nUSER MESSAGE:\n{user_input}"

        try:
            # Execute agent via invoke (LangGraph pattern)
            config = {"configurable": {"thread_id": thread_id}}
            result = await self.agent.ainvoke(
                {"messages": [("user", full_input)]},
                config=config
            )
            
            # Extract last message from result
            if "messages" in result and len(result["messages"]) > 0:
                return result["messages"][-1].content
            
            return "I'm sorry, I couldn't generate a response."
        
        except Exception as e:
            logger.error(f"[BASE AGENT] Error during execution: {e}", exc_info=True)
            return "I apologize, but I encountered an error processing your request."

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
