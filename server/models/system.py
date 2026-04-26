from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from models.base import Base

class SystemSetting(Base):
    __tablename__ = "core_systemsetting"

    id = Column(Integer, primary_key=True, index=True)
    text_model = Column(String(100), default='gpt-4o-mini')
    realtime_llm_model = Column(String(100), default='gpt-realtime-2025-08-28')
    summary_model = Column(String(100), default='gpt-4o-mini')
    
    maintenance_mode = Column(Boolean, default=False)
    maintenance_message = Column(Text, nullable=True)
    
    company_name = Column(String(100), nullable=True)
    company_email = Column(String(254), nullable=True)
    company_phone = Column(String(20), nullable=True)
    facebook_link = Column(String(200), nullable=True)
    twitter_link = Column(String(200), nullable=True)
    instagram_link = Column(String(200), nullable=True)
    linkedin_link = Column(String(200), nullable=True)
    
    updated_at = Column(DateTime)
