from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base

class SubscriptionPlan(Base):
    __tablename__ = "subscription_subscriptionplan"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    allowed_features = Column(JSON, default=list, nullable=True)
    usage_limits = Column(JSON, default=dict, nullable=True)
    is_active = Column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscription_subscription"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(String(100), index=True)
    plan_id = Column(Integer, ForeignKey("subscription_subscriptionplan.id"))
    status = Column(String(30))
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    ended_at = Column(DateTime, nullable=True)
    
    plan = relationship("SubscriptionPlan")

class UsageTracker(Base):
    __tablename__ = "subscription_usagetracker"
    
    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscription_subscription.id"))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    minutes_used = Column(Integer, default=0)
    sms_used = Column(Integer, default=0)
    
    subscription = relationship("Subscription")

class CreditBalance(Base):
    __tablename__ = "subscription_creditbalance"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(String(100), unique=True, index=True)
    additional_limits = Column(JSON, default=dict, nullable=True)
