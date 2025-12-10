from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _get_db_path() -> Path:
    """Get the database file path"""
    # 默认存储在项目的db目录下
    db_dir = Path(__file__).resolve().parent.parent.parent / "db"
    db_dir.mkdir(exist_ok=True)
    return db_dir / "report_storage.db"


def _load_database_url() -> str:
    """Load database URL from environment or config"""
    # Priority: env > config.toml > default (SQLite)
    env_url = os.getenv("REPORT_DATABASE_URL")
    if env_url:
        return env_url

    # 使用SQLite作为默认数据库
    db_path = _get_db_path()
    return f"sqlite+aiosqlite:///{db_path}"


DATABASE_URL = _load_database_url()

# Lazily create engine/sessionmaker to avoid importing drivers at module import time
_engine = None
_SessionFactory = None


def _ensure_engine():
    global _engine, _SessionFactory
    if _engine is None:
        # SQLite需要特殊配置
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            # SQLite的连接参数
            connect_args = {"check_same_thread": False}

        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            connect_args=connect_args
        )
        _SessionFactory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine, _SessionFactory


async def get_report_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession for report storage."""
    _, factory = _ensure_engine()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose global engine (optional for app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def init_db():
    """Initialize database (create tables if not exist)"""
    from .models import Base

    engine, _ = _ensure_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
