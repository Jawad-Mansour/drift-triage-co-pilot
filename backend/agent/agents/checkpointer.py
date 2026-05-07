from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.agent.core.logging import get_logger
from backend.agent.settings import Settings

log = get_logger(__name__)


@asynccontextmanager
async def checkpointer_lifespan(settings: Settings):
    """Async context manager for Postgres checkpointer — use inside app lifespan."""
    conn_str = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(conn_str) as saver:
        await saver.setup()
        log.info("checkpointer_ready", backend="postgres")
        yield saver
