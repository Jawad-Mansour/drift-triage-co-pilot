from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from backend.platform.db.base import get_engine

_sessionmaker = None


def get_sessionmaker():
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncSession:
    async with get_sessionmaker()() as session:
        yield session
