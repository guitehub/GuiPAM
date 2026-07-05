"""Moteur SQLite async : WAL + busy_timeout (scheduler et web écrivent en parallèle)."""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _configure_sqlite(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_engine(database_url: str) -> AsyncEngine:
    """Initialise le moteur global. Appelé au démarrage (et par les tests)."""
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, echo=False)
    event.listen(_engine.sync_engine, "connect", _configure_sqlite)
    _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Moteur non initialisé : appeler init_engine() d'abord.")
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Moteur non initialisé : appeler init_engine() d'abord.")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI."""
    async with session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
