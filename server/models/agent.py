from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class VoiceAgent(Base):
    __tablename__ = "voice_agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    system_prompt = Column(Text, nullable=False)
    voice = Column(String(50), default="alloy")
    greeting_message = Column(Text, nullable=True)
    temperature = Column(Float, default=0.8) 
    silence_duration_ms = Column(Integer, default=1000)
    vad_threshold = Column(Float, default=0.5)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tools = relationship("AgentTool", back_populates="agent", cascade="all, delete-orphan")
    calls = relationship("CallRecord", back_populates="agent", cascade="all, delete-orphan")
