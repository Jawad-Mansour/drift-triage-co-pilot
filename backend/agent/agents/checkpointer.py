from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.agent.core.logging import get_logger
from backend.agent.settings import Settings

log = get_logger(__name__)


async def build_checkpointer(settings: Settings) -> AsyncPostgresSaver:
    """Build and initialise a Postgres-backed async checkpointer.

    Uses AsyncPostgresSaver (not AsyncRedisSaver) — brainstorm decision #22.
    Postgres already stores our domain tables; one DB keeps ops simple.

    setup() creates the langgraph checkpoint tables if they don't exist.
    Safe to call on every startup.
    """
    # AsyncPostgresSaver needs the psycopg3 connection string (no +asyncpg driver prefix)
    conn_str = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    saver = await AsyncPostgresSaver.from_conn_string(conn_str)
    await saver.setup()
    log.info("checkpointer_ready", backend="postgres")
    return saver
