"""Async SQLAlchemy engine, session factory, and Base.

The engine uses connection pooling tuned for ~150 concurrent users.
"""

import os
import ssl as _ssl

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from config import get_settings

settings = get_settings()

# Build SSL context for Neon (cloud PostgreSQL requires TLS).
# asyncpg doesn't understand ?sslmode=require so we strip it and pass ssl via connect_args.
_db_url = settings.DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")
_connect_args: dict = {}
if "neon.tech" in settings.DATABASE_URL or "sslmode" in settings.DATABASE_URL:
    _ssl_ctx = _ssl.create_default_context()
    _connect_args["ssl"] = _ssl_ctx

# Use NullPool for serverless (Vercel) — no persistent connections
_is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

_pool_kwargs = (
    {"poolclass": NullPool}
    if _is_serverless
    else {
        "poolclass": AsyncAdaptedQueuePool,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": True,
    }
)

engine = create_async_engine(
    _db_url,
    echo=settings.DEBUG,
    future=True,
    connect_args=_connect_args,
    **_pool_kwargs,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:               # type: ignore[misc]
    """FastAPI dependency: yield an async DB session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables (call once on startup) and run lightweight migrations."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ── Lightweight column migrations ──
        # Add 'city' column to users if missing
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'city'"
            )
        )
        if result.fetchone() is None:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN city VARCHAR(120)")
            )
