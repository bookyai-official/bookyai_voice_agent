from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

class CallRecordBase(BaseModel):
    agent_id: int
    call_sid: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    status: str
    call_type: Optional[str] = None
    call_mode: Optional[str] = None
    call_summary: Optional[str] = None
    transcript: List[Any] = []
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    recording_url: Optional[str] = None

class CallRecordResponse(CallRecordBase):
    id: int
    agent_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
