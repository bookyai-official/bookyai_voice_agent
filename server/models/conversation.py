"""
SQLAlchemy models for Chat and Message — mirrors Django's ai_agent app.

Chat: Represents a conversation session (identified by phone_number or session_key).
Message: Individual messages within a chat (user, assistant, system).
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, JSON,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base


class Chat(Base):
    __tablename__ = "ai_agent_chat"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    lead_id = Column(Integer, nullable=True)
    phone_number = Column(String(20), nullable=True, index=True)
    session_key = Column(String(100), nullable=True, index=True)
    summary = Column(JSON, default=dict, nullable=True)
    response_received = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)

    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")

    __table_args__ = (
        UniqueConstraint("business_id", "phone_number", name="uq_chat_business_phone"),
        UniqueConstraint("business_id", "session_key", name="uq_chat_business_session"),
    )


class Message(Base):
    __tablename__ = "ai_agent_message"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("ai_agent_chat.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(10), nullable=False, index=True)  # user, assistant, system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    tool_calls = Column(JSON, default=list, nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    parent_message_id = Column(String(100), nullable=True)

    chat = relationship("Chat", back_populates="messages")
