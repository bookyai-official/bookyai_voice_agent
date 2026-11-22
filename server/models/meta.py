"""Mirrors Django-owned Meta tables. Runtime never creates production schema."""
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import declared_attr
from models.base import Base


def now():
    return datetime.now(timezone.utc)


class IntegrationColumns:
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    business_id = Column(String(255), nullable=False, unique=True)
    app_id = Column(String(255), nullable=False, default='')
    config_id = Column(String(255), nullable=False, default='')
    account_id = Column(String(255), nullable=False, default='')
    account_name = Column(String(255), nullable=False, default='')
    subject_id = Column(String(255), nullable=False, default='')
    subject_kind = Column(String(24), nullable=False, default='')
    encrypted_token = Column(Text, nullable=False, default='')
    permissions = Column(JSON, nullable=False, default=list)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    data_access_expires_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(24), nullable=False, default='disconnected')
    webhook_status = Column(String(16), nullable=False, default='pending')
    revision = Column(String(32), nullable=False)
    last_received_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(80), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class MessengerIntegration(IntegrationColumns, Base):
    __tablename__ = 'accounts_messengerintegration'
    encrypted_user_token = Column(Text, nullable=False, default='')


class InstagramIntegration(IntegrationColumns, Base):
    __tablename__ = 'accounts_instagramintegration'
    client_business_id = Column(String(255), nullable=False, default='')


class MetaWebhookEvent(Base):
    __tablename__ = 'accounts_metawebhookevent'
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    event_key = Column(String(64), nullable=False, unique=True)
    conversation_key = Column(String(64), nullable=False, index=True)
    business_id = Column(String(255), nullable=False)
    channel = Column(String(16), nullable=False)
    app_id = Column(String(255), nullable=False)
    account_id = Column(String(255), nullable=False)
    sender_id = Column(String(255), nullable=False)
    connection_revision = Column(String(32), nullable=False)
    encrypted_payload = Column(Text, nullable=False, default='')
    encrypted_reply = Column(Text, nullable=False, default='')
    status = Column(String(24), nullable=False, default='pending', index=True)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=False, default=now)
    lease_owner = Column(String(32), nullable=False, default='')
    lease_until = Column(DateTime(timezone=True), nullable=True)
    inbound_message_id = Column(BigInteger, nullable=True)
    chat_id = Column(BigInteger, nullable=True)
    provider_message_id = Column(String(255), nullable=False, default='')
    usage_charged = Column(Boolean, nullable=False, default=False)
    usage_precharged = Column(Boolean, nullable=False, default=False)
    last_error_code = Column(String(80), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class MetaConversationLease(Base):
    __tablename__ = 'accounts_metaconversationlease'
    conversation_key = Column(String(64), primary_key=True)
    owner = Column(String(32), nullable=False, default='')
    expires_at = Column(DateTime(timezone=True), nullable=False, default=now)


CHANNEL_MODELS = {'messenger': MessengerIntegration, 'instagram': InstagramIntegration}
