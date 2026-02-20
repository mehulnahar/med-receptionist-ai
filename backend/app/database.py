import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Connection pool tuning
# ---------------------------------------------------------------------------
# pool_size:       Number of persistent connections kept open.  With 500-600
#                  calls/day and bursty dashboard traffic, 20 is a safe start.
# max_overflow:    Extra connections allowed when the pool is exhausted. These
#                  are closed after use.
# pool_timeout:    Seconds to wait for a connection before raising.
# pool_recycle:    Recycle connections after N seconds to avoid stale TCP.
# pool_pre_ping:   Issue a lightweight "SELECT 1" before handing out a
#                  connection — catches connections killed by the DB/firewall.
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=1800,    # recycle every 30 minutes
    pool_pre_ping=True,   # detect dead connections before use
    connect_args={
        "command_timeout": 30,                        # 30s per-statement timeout
        "server_settings": {"statement_timeout": "30000"},  # 30s server-side guard
    },
)

# ---------------------------------------------------------------------------
# Pool event listeners — surface connection exhaustion before it causes outages
# ---------------------------------------------------------------------------
_sync_engine = engine.sync_engine

@event.listens_for(_sync_engine, "checkout")
def _on_checkout(dbapi_conn, connection_rec, connection_proxy):
    pool = _sync_engine.pool
    logger.debug(
        "db_pool: checkout — size=%s, checkedin=%s, overflow=%s",
        pool.size(), pool.checkedin(), pool.overflow(),
    )

@event.listens_for(_sync_engine, "checkin")
def _on_checkin(dbapi_conn, connection_rec):
    pool = _sync_engine.pool
    if pool.overflow() > pool.size() * 0.5:
        logger.warning(
            "db_pool: high overflow — size=%s, checkedin=%s, overflow=%s (>50%% of pool_size)",
            pool.size(), pool.checkedin(), pool.overflow(),
        )


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session scoped to the request lifecycle.

    Route handlers are responsible for calling ``await db.commit()``
    explicitly after write operations.  This avoids double-commits when
    handlers already commit (e.g. after SMS sends).  Read-only endpoints
    don't need to commit.  On exception the session is rolled back.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
