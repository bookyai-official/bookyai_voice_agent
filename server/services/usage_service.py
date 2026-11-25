import logging
from sqlalchemy.future import select
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from models.subscription import Subscription, UsageTracker, CreditBalance, SubscriptionPlan
from datetime import datetime, timezone
from services.lifetime_runtime import LifetimeRuntime
from services.billing_scope import billing_business_id, lock_billing_account, subscription_covers_workspace

logger = logging.getLogger(__name__)

class UsageService:
    @staticmethod
    async def get_active_usage_tracker(db: AsyncSession, business_id: int | str):
        """
        Fetches the active subscription and its current usage tracker for a business.
        """
        requested_id = str(business_id)
        business_id = await billing_business_id(db, business_id)

        # 1. Get active/trialing subscription
        stmt = (
            select(Subscription)
            .where(
                Subscription.business_id == business_id,
                Subscription.status.in_(['active', 'trialing']),
                Subscription.ended_at.is_(None),
                or_(Subscription.current_period_end.is_(None), Subscription.current_period_end > func.now()),
                or_(Subscription.status != 'trialing', Subscription.trial_end.is_(None), Subscription.trial_end > func.now()),
            )
            .order_by(Subscription.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        subscription = result.scalar_one_or_none()
        
        if not subscription:
            return None, None
        if not await subscription_covers_workspace(db, requested_id, subscription):
            return None, None

        # 2. Get the usage tracker for this subscription
        stmt = (
            select(UsageTracker)
            .where(UsageTracker.subscription_id == subscription.id,
                   UsageTracker.period_start == subscription.current_period_start,
                   UsageTracker.period_end == subscription.current_period_end)
            .order_by(UsageTracker.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        tracker = result.scalar_one_or_none()
        
        return subscription, tracker

    @staticmethod
    async def has_feature_access(db: AsyncSession, business_id: int | str, feature_key: str) -> bool:
        """
        Checks if a business has access to a specific feature key based on their subscription plan.
        """
        policy = await LifetimeRuntime.context(business_id)
        if policy:
            allowed = policy.get('allowed_features', [])
            return not allowed or feature_key in allowed
        business_id = str(business_id)
        subscription, _ = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            logger.warning(f"No active subscription found for Business {business_id} to check feature {feature_key}")
            return False

        # Get the plan to check features
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        
        if not plan:
            return False

        # Empty allowed_features list = all features allowed (backward-compatible default)
        allowed = getattr(plan, "allowed_features", None)
        if not allowed:  # None or []
            return True
            
        return feature_key in allowed

    @staticmethod
    async def has_remaining_usage(db: AsyncSession, business_id: int | str, usage_type: str) -> bool:
        """
        Checks if a business has remaining usage for the given type ('minutes' or 'sms').
        """
        policy = await LifetimeRuntime.context(business_id)
        if policy:
            remaining = policy['remaining'].get(usage_type, 0)
            return remaining is None or remaining > 0
        business_id = str(business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            logger.warning(f"No active subscription found for Business {business_id}")
            return False
        business_id = str(subscription.business_id)

        # Get the plan to check limits
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        
        if not plan:
            return False

        limits = plan.usage_limits if isinstance(plan.usage_limits, dict) else {}
        limit = limits.get(usage_type, 0)
        
        # Only an explicit JSON null is unlimited. Zero grants no allowance.
        if limit is None:
            return True

        used = getattr(tracker, f"{usage_type}_used", 0) if tracker else 0
        
        if used < limit:
            return True
            
        # If monthly limit reached, check CreditBalance (add-ons)
        stmt = select(CreditBalance).where(CreditBalance.business_id == business_id)
        result = await db.execute(stmt)
        balance = result.scalar_one_or_none()
        
        if balance:
            additional_limits = balance.additional_limits if isinstance(balance.additional_limits, dict) else {}
            additional = additional_limits.get(usage_type, 0)
            if additional > 0:
                return True
                
        return False

    @staticmethod
    async def get_remaining_usage(db: AsyncSession, business_id: int | str, usage_type: str) -> int:
        """
        Returns the number of remaining units (minutes or SMS) for a business.
        Returns a very large number if unlimited.
        """
        policy = await LifetimeRuntime.context(business_id)
        if policy:
            remaining = policy['remaining'].get(usage_type, 0)
            return 999999 if remaining is None else remaining
        business_id = str(business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            return 0
        business_id = str(subscription.business_id)

        # Get the plan to check limits
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        
        if not plan:
            return 0

        limits = plan.usage_limits if isinstance(plan.usage_limits, dict) else {}
        limit = limits.get(usage_type, 0)
        used = getattr(tracker, f"{usage_type}_used", 0) if tracker else 0

        # Check CreditBalance (add-ons)
        stmt = select(CreditBalance).where(CreditBalance.business_id == business_id)
        result = await db.execute(stmt)
        balance = result.scalar_one_or_none()
        additional_limits = balance.additional_limits if (balance and isinstance(balance.additional_limits, dict)) else {}
        additional = additional_limits.get(usage_type, 0)

        if limit is None:
            return 999999 # Effectively unlimited

        remaining_from_plan = max(0, limit - used)
        return remaining_from_plan + additional

    @staticmethod
    async def update_usage(db: AsyncSession, business_id: int | str, usage_type: str, amount: int):
        """
        Increments usage for a business.
        Prioritizes the monthly allowance, then consumes from CreditBalance.
        """
        if await LifetimeRuntime.context(business_id):
            # LTD is reserved before provider work in the execution path, never charged twice here.
            return
        business_id = await lock_billing_account(db, business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            logger.error(f"Cannot update usage: No active subscription for Business {business_id}")
            return

        # 1. Fetch Plan Limit
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        limits = plan.usage_limits if (plan and isinstance(plan.usage_limits, dict)) else {}
        limit = limits.get(usage_type, 0)

        # Lock both rows, then split usage across allowance and purchased credits.
        if tracker:
            tracker = (await db.execute(select(UsageTracker).where(
                UsageTracker.id == tracker.id).with_for_update())).scalar_one()
        used = getattr(tracker, f"{usage_type}_used", 0) if tracker else 0
        allowance_remaining = amount if limit is None else max(0, limit - used)
        allowance = min(amount, allowance_remaining) if tracker else 0
        if tracker and allowance:
            setattr(tracker, f"{usage_type}_used", used + allowance)
        credits_needed = amount - allowance
        if credits_needed:
            balance = (await db.execute(select(CreditBalance).where(
                CreditBalance.business_id == business_id).with_for_update())).scalar_one_or_none()
            values = dict(balance.additional_limits or {}) if balance else {}
            debit = min(credits_needed, values.get(usage_type, 0))
            if balance and debit:
                values[usage_type] -= debit
                balance.additional_limits = values
            # Preserve visibility of provider usage that was already incurred.
            if tracker and credits_needed > debit:
                setattr(tracker, f"{usage_type}_used", getattr(tracker, f"{usage_type}_used") + credits_needed - debit)
        await db.commit()
