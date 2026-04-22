from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class AgentToolBase(BaseModel):
    name: str
    description: str
    tool_type: Optional[str] = "webhook"
    url: Optional[str] = None
    tool_target: Optional[str] = None
    method: Optional[str] = "POST"
    timeout_seconds: Optional[int] = 5
    json_schema: Optional[Dict[str, Any]] = {}

class AgentToolCreate(AgentToolBase):
    agent_id: int

class AgentToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tool_type: Optional[str] = None
    url: Optional[str] = None
    tool_target: Optional[str] = None
    method: Optional[str] = None
    timeout_seconds: Optional[int] = None
    json_schema: Optional[Dict[str, Any]] = None

class AgentToolResponse(AgentToolBase):
    id: int
    agent_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
