"""Resolve subscription ownership without changing the business used for tenant data."""
from sqlalchemy import text

from services.lifetime_runtime import RuntimeDenied


async def billing_business_id(db, business_id):
    result = await db.execute(text('''
        SELECT parent.id FROM business_business workspace
        JOIN business_business parent ON parent.id = COALESCE(workspace.billing_parent_id, workspace.id)
        WHERE workspace.id = :business_id AND workspace.is_active = :active AND parent.is_active = :active
    '''), {'business_id': str(business_id), 'active': True})
    primary = result.scalar_one_or_none()
    if primary is None:
        raise RuntimeDenied('The business or its billing account is inactive.')
    return str(primary)


async def billing_workspace_ids(db, business_id):
    primary = await billing_business_id(db, business_id)
    result = await db.execute(text('''
        SELECT id FROM business_business
        WHERE (id = :primary OR billing_parent_id = :primary) AND is_active = :active
        ORDER BY CASE WHEN id = :primary THEN 0 ELSE 1 END, created_at, id
    '''), {'primary': primary, 'active': True})
    return [str(value) for value in result.scalars().all()]


async def subscription_covers_workspace(db, requested_id, subscription):
    if str(requested_id) == str(subscription.business_id):
        return True
    from sqlalchemy import select
    from models.subscription import SubscriptionPlan, CreditBalance
    plan = await db.get(SubscriptionPlan, subscription.plan_id)
    limit = (plan.usage_limits or {}).get('workspaces', 0) if plan else 0
    if limit is None:
        return True
    balance = (await db.execute(select(CreditBalance).where(
        CreditBalance.business_id == subscription.business_id))).scalar_one_or_none()
    limit += (balance.additional_limits or {}).get('workspaces', 0) if balance else 0
    covered = await billing_workspace_ids(db, requested_id)
    return str(requested_id) in covered[:max(0, limit)]


async def lock_billing_account(db, business_id):
    primary = await billing_business_id(db, business_id)
    statement = 'SELECT id FROM business_business WHERE id = :primary'
    if db.bind.dialect.name == 'postgresql':
        statement += ' FOR UPDATE'
    await db.execute(text(statement), {'primary': primary})
    return primary
