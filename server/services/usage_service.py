import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.subscription import Subscription, UsageTracker, CreditBalance, SubscriptionPlan
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class UsageService:
    @staticmethod
    async def get_active_usage_tracker(db: AsyncSession, business_id: int | str):
        """
        Fetches the active subscription and its current usage tracker for a business.
        """
        business_id = str(business_id)

        # 1. Get active/trialing subscription
        stmt = (
            select(Subscription)
            .where(
                Subscription.business_id == business_id,
                Subscription.status.in_(['active', 'trialing']),
                Subscription.ended_at == None
            )
            .order_by(Subscription.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        subscription = result.scalar_one_or_none()
        
        if not subscription:
            return None, None

        # 2. Get the usage tracker for this subscription
        stmt = (
            select(UsageTracker)
            .where(UsageTracker.subscription_id == subscription.id)
            .order_by(UsageTracker.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        tracker = result.scalar_one_or_none()
        
        return subscription, tracker

    @staticmethod
    async def has_remaining_usage(db: AsyncSession, business_id: int | str, usage_type: str) -> bool:
        """
        Checks if a business has remaining usage for the given type ('minutes' or 'sms').
        """
        business_id = str(business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            logger.warning(f"No active subscription found for Business {business_id}")
            return False

        # Get the plan to check limits
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        
        if not plan:
            return False

        limit = getattr(plan, f"{usage_type}_limit", 0)
        
        # 0 means unlimited
        if limit == 0:
            return True

        used = getattr(tracker, f"{usage_type}_used", 0) if tracker else 0
        
        if used < limit:
            return True
            
        # If monthly limit reached, check CreditBalance (add-ons)
        stmt = select(CreditBalance).where(CreditBalance.business_id == business_id)
        result = await db.execute(stmt)
        balance = result.scalar_one_or_none()
        
        if balance:
            additional = getattr(balance, f"additional_{usage_type}", 0)
            if additional > 0:
                return True
                
        return False

    @staticmethod
    async def get_remaining_usage(db: AsyncSession, business_id: int | str, usage_type: str) -> int:
        """
        Returns the number of remaining units (minutes or SMS) for a business.
        Returns a very large number if unlimited.
        """
        business_id = str(business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            return 0

        # Get the plan to check limits
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        
        if not plan:
            return 0

        limit = getattr(plan, f"{usage_type}_limit", 0)
        used = getattr(tracker, f"{usage_type}_used", 0) if tracker else 0

        # Check CreditBalance (add-ons)
        stmt = select(CreditBalance).where(CreditBalance.business_id == business_id)
        result = await db.execute(stmt)
        balance = result.scalar_one_or_none()
        additional = getattr(balance, f"additional_{usage_type}", 0) if balance else 0

        if limit == 0:
            return 999999 # Effectively unlimited

        remaining_from_plan = max(0, limit - used)
        return remaining_from_plan + additional

    @staticmethod
    async def update_usage(db: AsyncSession, business_id: int | str, usage_type: str, amount: int):
        """
        Increments usage for a business.
        Prioritizes the monthly allowance, then consumes from CreditBalance.
        """
        business_id = str(business_id)

        subscription, tracker = await UsageService.get_active_usage_tracker(db, business_id)
        
        if not subscription:
            logger.error(f"Cannot update usage: No active subscription for Business {business_id}")
            return

        # 1. Fetch Plan Limit
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
        limit = getattr(plan, f"{usage_type}_limit", 0) if plan else 0

        # 2. Update UsageTracker
        if tracker:
            used = getattr(tracker, f"{usage_type}_used", 0)
            
            # If we are under the monthly limit OR there's no credit balance to use, update the tracker
            # This ensures we always record the usage somewhere.
            if limit == 0 or used < limit:
                setattr(tracker, f"{usage_type}_used", used + amount)
                await db.commit()
                return

        # 3. If limit reached, try to consume from CreditBalance
        stmt = select(CreditBalance).where(CreditBalance.business_id == business_id)
        result = await db.execute(stmt)
        balance = result.scalar_one_or_none()
        
        if balance:
            additional = getattr(balance, f"additional_{usage_type}", 0)
            if additional > 0:
                # Deduct from additional credits
                new_val = max(0, additional - amount)
                setattr(balance, f"additional_{usage_type}", new_val)
                await db.commit()
                logger.info(f"Deducted {amount} {usage_type} from CreditBalance for Business {business_id}")
                return
        
        # 4. Final fallback: If we are over the limit and have no credits, we still increment the tracker
        # so the user can see the overage in their dashboard.
        if tracker:
            used = getattr(tracker, f"{usage_type}_used", 0)
            setattr(tracker, f"{usage_type}_used", used + amount)
            await db.commit()
            logger.info(f"Incremented over-limit usage for Business {business_id} on UsageTracker")
        else:
            logger.warning(f"Usage updated for Business {business_id} but no tracker or credits found to update.")
