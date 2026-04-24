from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from schemas.tool import AgentToolResponse
from schemas.call import CallRecordResponse

class VoiceAgentBase(BaseModel):
    name: str
    personality_prompt: Optional[str] = None
    pricing_prompt: Optional[str] = None
    business_prompt: Optional[str] = None
    script_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None
    system_prompt: Optional[str] = ""
    voice: Optional[str] = "alloy"
    greeting_message: Optional[str] = None
    temperature: Optional[float] = 0.8
    silence_duration_ms: Optional[int] = 1000
    vad_threshold: Optional[float] = 0.5
    phone_number: Optional[str] = None
    active: Optional[bool] = True

class VoiceAgentCreate(VoiceAgentBase):
    pass

class VoiceAgentUpdate(BaseModel):
    name: Optional[str] = None
    personality_prompt: Optional[str] = None
    pricing_prompt: Optional[str] = None
    business_prompt: Optional[str] = None
    script_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None
    system_prompt: Optional[str] = None
    voice: Optional[str] = None
    greeting_message: Optional[str] = None
    temperature: Optional[float] = None
    silence_duration_ms: Optional[int] = None
    vad_threshold: Optional[float] = None
    phone_number: Optional[str] = None
    active: Optional[bool] = None

class VoiceAgentResponse(VoiceAgentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    tools: List[AgentToolResponse] = []
    calls: List[CallRecordResponse] = []

    class Config:
        from_attributes = True
