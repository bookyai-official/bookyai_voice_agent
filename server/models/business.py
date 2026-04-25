from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from models.base import Base

class BusinessConfiguration(Base):
    __tablename__ = "business_businessconfiguration"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, unique=True, nullable=False)
    
    # Voice/Twilio Configuration
    voice_enabled = Column(Boolean, default=True)
    twilio_phone_number = Column(String(20), nullable=True)
    twilio_sid = Column(String(255), nullable=True)
    twilio_auth_token = Column(String(255), nullable=True)
    
    # Other fields mentioned by user (optional for FastAPI but good for parity)
    ai_model_preference = Column(String(20), default='openai')
    staff_pay_percentage = Column(Numeric(5, 2), default=0.00)
    recurring_bookings_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
