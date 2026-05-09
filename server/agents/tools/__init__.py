import logging
from typing import List, Optional, Any
from langchain_core.tools import BaseTool
from agents.tools.internal import create_internal_tools
from agents.tools.factory import ToolFactory

logger = logging.getLogger(__name__)

def get_tools(
    agent_config: Any, 
    twilio_client: Optional[Any] = None, 
    call_sid: Optional[str] = None
) -> List[BaseTool]:
    """
    Assembles the full list of tools (internal + external) for an agent.
    
    Args:
        agent_config: The AIAgent model instance (must have .tools loaded)
        twilio_client: Optional Twilio client for internal voice tools
        call_sid: Optional active call SID for internal voice tools
        
    Returns:
        List of LangChain tools.
    """
    tools = []
    
    # 1. Add Internal Tools (Voice control)
    # These are always available but will return errors if used on non-voice channels
    internal_tools = create_internal_tools(twilio_client, call_sid)
    tools.extend(internal_tools)
    
    # 2. Add External Tools from Database Config
    if hasattr(agent_config, "tools") and agent_config.tools:
        for t_config in agent_config.tools:
            try:
                # Map specific built-in types if they exist in DB as 'webhook' but are actually internal
                # This handles legacy data where 'call_end' might be stored as a 'webhook' type
                if t_config.tool_type == "call_end" or t_config.name == "end_call":
                    continue # Already added via internal_tools
                if t_config.tool_type == "call_transfer" or t_config.name == "transfer_call":
                    continue # Already added via internal_tools
                
                # Build dynamic external tool
                ext_tool = ToolFactory.create_external_tool(t_config)
                tools.append(ext_tool)
                
            except Exception as e:
                logger.error(f"Failed to load tool {t_config.name} for agent {agent_config.id}: {e}")

    return tools
