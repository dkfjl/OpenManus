from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Read DATABASE_URL from environment; example:
# mysql+aiomysql://user:password@127.0.0.1:3306/openmanus
def _load_database_url() -> str:
    # Priority: env > config.toml > default
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    try:
        from app.config import config as app_config

        return app_config.chat.database_url or "mysql+aiomysql://root:password@127.0.0.1:3306/openmanus"
    except Exception:
        return "mysql+aiomysql://root:password@127.0.0.1:3306/openmanus"

DATABASE_URL = _load_database_url()

# Lazily create engine/sessionmaker to avoid importing drivers at module import time
_engine = None
_SessionFactory = None


def _ensure_engine():
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
        _SessionFactory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine, _SessionFactory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession."""
    _, factory = _ensure_engine()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose global engine (optional for app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
