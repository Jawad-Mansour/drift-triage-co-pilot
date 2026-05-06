from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped AsyncSession from the lifespan sessionmaker.

    Background tasks must NOT capture this session — open a fresh one via
    request.app.state.sessionmaker() directly.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
