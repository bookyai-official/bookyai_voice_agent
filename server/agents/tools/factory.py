import logging
from typing import Dict, Any, Type, Optional
from pydantic import create_model, BaseModel, Field
from langchain_core.tools import StructuredTool
from agents.tools.external import execute_external_api

logger = logging.getLogger(__name__)

class ToolFactory:
    """
    Factory to dynamically create LangChain tools from database configurations.
    """

    @staticmethod
    def create_external_tool(tool_config: Any) -> StructuredTool:
        """
        Builds a LangChain StructuredTool from an AgentTool model instance.
        
        Args:
            tool_config: An instance of the AgentTool model
            
        Returns:
            A configured StructuredTool ready for LangChain
        """
        name = tool_config.name
        description = tool_config.description
        url = tool_config.url
        method = tool_config.method or "POST"
        timeout = tool_config.timeout_seconds or 5
        
        # 1. Dynamically create a Pydantic model for the tool's input schema
        # tool_config.json_schema typically looks like: { "type": "object", "properties": { "arg1": {...} } }
        properties = tool_config.json_schema.get("properties", {})
        required = tool_config.json_schema.get("required", [])
        
        fields = {}
        for prop_name, prop_details in properties.items():
            prop_type = prop_details.get("type", "string")
            # Default to str, but we could expand this mapping
            python_type = str
            if prop_type == "integer":
                python_type = int
            elif prop_type == "number":
                python_type = float
            elif prop_type == "boolean":
                python_type = bool
                
            field_desc = prop_details.get("description", "")
            is_required = prop_name in required
            
            fields[prop_name] = (
                python_type if is_required else Optional[python_type],
                Field(default=... if is_required else None, description=field_desc)
            )

        # Create the dynamic Pydantic model
        InputSchema = create_model(f"{name}Input", **fields)

        # 2. Define the execution wrapper
        async def tool_wrapper(**kwargs) -> str:
            return await execute_external_api(
                url=url,
                method=method,
                timeout=timeout,
                payload=kwargs
            )

        # 3. Build and return the StructuredTool
        return StructuredTool.from_function(
            name=name,
            description=description,
            func=None, # We use coroutine instead
            coroutine=tool_wrapper,
            args_schema=InputSchema
        )
