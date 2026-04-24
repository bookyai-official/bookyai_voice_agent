from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from core.config import settings

database_url = settings.DATABASE_URL
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

is_sqlite = database_url.startswith("sqlite")

# Common arguments for all engines
engine_args = {
    "echo": False,
}

# Add PostgreSQL-specific settings if not using SQLite
if not is_sqlite:
    engine_args.update({
        "pool_pre_ping": True,
        "pool_recycle": 300,
    })
    # If the database requires SSL (e.g., Railway, Render), asyncpg usually handles it via query params
    # but we can add it here if needed. Note: asyncpg uses ssl=True or ssl=ssl_context
    if "sslmode=require" in database_url or "ssl=require" in database_url:
        engine_args["connect_args"] = {"ssl": True}

engine = create_async_engine(
    database_url,
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
