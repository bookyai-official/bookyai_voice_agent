from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, Float, event
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class VoiceAgent(Base):
    __tablename__ = "voice_agent_voiceagent"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=True) # ForeignKey to Django Business model
    name = Column(String(100), nullable=False)
    
    # Modular Prompt Fields
    personality_prompt = Column(Text, nullable=True, default="You are Sarah, a polite and professional AI assistant.")
    pricing_prompt = Column(Text, nullable=True, default="Quote prices based on business context.")
    business_prompt = Column(Text, nullable=True)
    script_prompt = Column(Text, nullable=True, default="Greet the customer, ask which service they need, check availability, and proceed with booking.")
    custom_instructions = Column(Text, nullable=True)
    
    system_prompt = Column(Text, nullable=False) # This will now be the compiled version
    voice = Column(String(50), default="alloy")
    greeting_message = Column(Text, nullable=True)
    temperature = Column(Float, default=0.8) 
    silence_duration_ms = Column(Integer, default=1000)
    vad_threshold = Column(Float, default=0.5)
    phone_number = Column(String(20), nullable=True) # Per-agent Twilio number
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tools = relationship("AgentTool", back_populates="agent", cascade="all, delete-orphan")
    calls = relationship("CallRecord", back_populates="agent", cascade="all, delete-orphan")

    def get_compiled_prompt(self):
        """
        Aggregates modular prompt fields into a single system prompt.
        Order: Persona -> Business -> Pricing -> Custom Rules -> Script
        """
        parts = []
        
        # 1. Persona & Tone
        parts.append("### Persona & Tone")
        parts.append(self.personality_prompt or "You are a helpful AI assistant.")
        
        # 2. Business Context
        if self.business_prompt:
            parts.append("### Business Information")
            parts.append(self.business_prompt)
            
        # 3. Services & Pricing
        parts.append("### Services & Pricing")
        parts.append(self.pricing_prompt or "Quote prices based on business context.")
        
        # 4. Special Instructions
        if self.custom_instructions:
            parts.append("### Special Rules & Instructions")
            parts.append(self.custom_instructions)
            
        # 5. Call Script & Flow (Final focus)
        parts.append("### Call Script & Flow")
        parts.append(self.script_prompt or "Greet the customer and ask how you can help.")
        
        return "\n\n".join(parts)

# Synchronization Logic: Ensure system_prompt is always up-to-date
@event.listens_for(VoiceAgent, 'before_insert')
@event.listens_for(VoiceAgent, 'before_update')
def update_system_prompt(mapper, connection, target):
    target.system_prompt = target.get_compiled_prompt()
