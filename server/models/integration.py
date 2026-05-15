from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class FacebookIntegration(Base):
    """
    Stores Facebook Page OAuth tokens and settings for a Business.
    Mirrors the Django model in integration app.
    """
    __tablename__ = "accounts_facebookintegration"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(String(100), ForeignKey("business_businessconfiguration.business_id", ondelete="CASCADE"), unique=True)
    fb_user_id = Column(String(255), nullable=True)
    page_id = Column(String(255), nullable=True, index=True)
    page_name = Column(String(255), nullable=True)
    page_access_token = Column(Text, nullable=True)
    user_access_token = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_subscribed = Column(Boolean, default=False)

    # Instagram Integration
    instagram_business_account_id = Column(String(255), nullable=True)
    is_instagram_active = Column(Boolean, default=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<FacebookIntegration(page_name='{self.page_name}', business_id={self.business_id})>"
