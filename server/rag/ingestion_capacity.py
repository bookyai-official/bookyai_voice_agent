"""Serialize capacity accounting while allowing page fetches to run concurrently."""
import asyncio
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from services.billing_scope import billing_business_id, lock_billing_account

_locks = WeakValueDictionary()


@asynccontextmanager
async def capacity_guard(db, business_id):
    primary = await billing_business_id(db, business_id)
    lock = _locks.get(primary)
    if lock is None:
        lock = asyncio.Lock()
        _locks[primary] = lock
    async with lock:
        try:
            await lock_billing_account(db, primary)
            yield
        except BaseException:
            await db.rollback()
            raise
