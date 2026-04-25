from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class AgentTool(Base):
    __tablename__ = "voice_agent_agenttool"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("voice_agent_aiagent.id", ondelete="CASCADE"), nullable=False)
    
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    tool_type = Column(String(50), default="webhook") # webhook, call_end, call_transfer
    url = Column(String(255), nullable=True)
    tool_target = Column(String(255), nullable=True) # Phone number for transfer
    method = Column(String(10), default="POST")
    timeout_seconds = Column(Integer, default=5)
    
    # Stores the actual parameters format: { "type": "object", "properties": {...} }
    json_schema = Column(JSON, default=dict) 
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    agent = relationship("AIAgent", back_populates="tools")
