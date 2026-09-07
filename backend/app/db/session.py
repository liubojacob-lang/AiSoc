"""Async engine/session management.

Two execution contexts:
- API process: one cached engine for the app's lifetime (``get_session``).
- Task bodies (Celery / inline): each invocation runs on a fresh asyncio
  loop, so it uses ``fresh_session`` — a short-lived engine disposed at the
  end. ``get_sessionmaker`` resolves the contextual maker first, which keeps
  the LLM gateway's independent accounting sessions on the *same* loop as the
  calling task.
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_current_maker: contextvars.ContextVar[async_sessionmaker[AsyncSession] | None] = (
    contextvars.ContextVar("current_session_maker", default=None)
)
_current_session: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "current_session", default=None
)


def _engine_kwargs() -> dict:
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if not settings.database_url.startswith("sqlite"):
        kwargs["pool_size"] = settings.sql_pool_size
        kwargs["max_overflow"] = settings.sql_max_overflow
    return kwargs


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, **_engine_kwargs())
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    contextual = _current_maker.get()
    if contextual is not None:
        return contextual
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session (exposed via contextvar for
    cross-cutting writes like AI accounting fallback)."""
    maker = get_sessionmaker()
    async with maker() as session:
        token = _current_session.set(session)
        try:
            yield session
        finally:
            _current_session.reset(token)


def get_current_session() -> AsyncSession | None:
    return _current_session.get()


@asynccontextmanager
async def fresh_session() -> AsyncIterator[AsyncSession]:
    """Short-lived engine+session for task bodies (fresh event loop per run)."""
    engine = create_async_engine(settings.database_url, **_engine_kwargs())
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    token = _current_maker.set(maker)
    try:
        async with maker() as session:
            stoken = _current_session.set(session)
            try:
                yield session
            finally:
                _current_session.reset(stoken)
    finally:
        _current_maker.reset(token)
        await engine.dispose()


def get_sync_engine():
    """For Alembic migrations and maintenance scripts."""
    return create_engine(settings.sync_database_url, echo=False)


async def dispose_engine() -> None:
    """Dispose the cached engine (lifespan teardown; releases sqlite locks)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def reset_engine_cache() -> None:
    """Test isolation hook: drop cached engine so new URLs take effect."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


# re-export for maintenance scripts that need a plain sync Session
Session = sessionmaker
