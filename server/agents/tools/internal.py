import logging
from typing import Optional, Callable
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

def create_internal_tools(
    twilio_client: Optional[any] = None, 
    call_sid: Optional[str] = None,
    business_id: Optional[str] = None
):
    """
    Factory function to create internal agent tools with injected dependencies.
    
    Args:
        twilio_client: An initialized Twilio REST client
        call_sid: The SID of the active call (for voice channel)
        business_id: Optional business ID for knowledge base queries
    """

    @tool
    def end_call() -> str:
        """
        Ends the current phone call immediately. 
        Use this when the customer wants to hang up or the conversation is finished.
        """
        if not twilio_client or not call_sid:
            return "Error: Call control is not available on this channel."
        
        try:
            # We don't want to block the loop, but since this is a final action,
            # a brief synchronous call is often acceptable in these wrappers.
            # In production, this would ideally be an async call.
            twilio_client.calls(call_sid).update(status="completed")
            logger.info(f"[TOOL] Call {call_sid} terminated by agent.")
            return "Call has been ended successfully."
        except Exception as e:
            logger.error(f"[TOOL] Failed to end call {call_sid}: {e}")
            return f"Error: Could not end the call. {str(e)}"

    @tool
    def transfer_call(target_number: str) -> str:
        """
        Transfers the current call to a specific phone number or department.
        
        Args:
            target_number: The destination phone number in E.164 format (e.g. +1234567890)
        """
        if not twilio_client or not call_sid:
            return "Error: Call transfer is not available on this channel."

        try:
            twiml = f'<Response><Dial>{target_number}</Dial></Response>'
            twilio_client.calls(call_sid).update(twiml=twiml)
            logger.info(f"[TOOL] Call {call_sid} transferred to {target_number}.")
            return f"Call is being transferred to {target_number}."
        except Exception as e:
            logger.error(f"[TOOL] Failed to transfer call {call_sid}: {e}")
            return f"Error: Could not transfer the call. {str(e)}"

    tools_list = [end_call, transfer_call]
    
    if business_id:
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field
        from rag.retriever import KnowledgeRetriever
        from core.database import AsyncSessionLocal
        import asyncio

        class KnowledgeBaseQuery(BaseModel):
            query: str = Field(description="The search query to look up in the knowledge base.")

        async def query_knowledge_base_func(query: str) -> str:
            """Search the business knowledge base for information."""
            try:
                async with AsyncSessionLocal() as db:
                    context = await KnowledgeRetriever.retrieve_with_scores(
                        query=query,
                        business_id=business_id,
                        db=db
                    )
                if not context:
                    return "No relevant information found in the knowledge base for the given query."
                return context
            except Exception as e:
                logger.error(f"[TOOL] Failed to query knowledge base: {e}")
                return "Error: Could not retrieve information from the knowledge base."

        def sync_query_knowledge_base_func(query: str) -> str:
            try:
                loop = asyncio.get_running_loop()
                return loop.create_task(query_knowledge_base_func(query))
            except RuntimeError:
                return asyncio.run(query_knowledge_base_func(query))

        kb_tool = StructuredTool.from_function(
            func=sync_query_knowledge_base_func,
            coroutine=query_knowledge_base_func,
            name="query_knowledge_base",
            description=(
                "CRITICAL: Use this tool ONLY to look up specific facts about the business "
                "DO NOT use this tool for casual conversation, greetings, pleasantries, or general knowledge. "
                "If the user asks a question about the business that you do not already know, then run this tool to get the context. "
                "If you get it, add it to your response. Else, handle gracefully."
            ),
            args_schema=KnowledgeBaseQuery,
        )
        tools_list.append(kb_tool)

    return tools_list
