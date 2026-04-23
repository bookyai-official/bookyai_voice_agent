from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class CallRecord(Base):
    __tablename__ = "voice_agent_callrecord"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("voice_agent_voiceagent.id"), nullable=False)
    call_sid = Column(String(100), unique=True, index=True, nullable=False)
    from_number = Column(String(50), nullable=True)
    to_number = Column(String(50), nullable=True)
    status = Column(String(50), default="in-progress")
    call_type = Column(String(20), nullable=True) # inbound / outbound
    call_mode = Column(String(20), nullable=True) # web / phone
    call_summary = Column(String, nullable=True)
    transcript = Column(JSON, default=list) # Will store list of {"role": "user/assistant", "text": "..."}
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    recording_url = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    agent = relationship("VoiceAgent", back_populates="calls")
