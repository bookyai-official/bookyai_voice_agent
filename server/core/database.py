from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# Common arguments for all engines
engine_args = {
    "echo": False,
    "future": True,
}

# Add PostgreSQL-specific settings if not using SQLite
if not is_sqlite:
    engine_args.update({
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"ssl": "require"}
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_args
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
