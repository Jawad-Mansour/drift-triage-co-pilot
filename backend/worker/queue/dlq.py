import json
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

DLQ = "queue:tasks:dlq"


async def push_to_dlq(task: dict, error: str, settings) -> None:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        entry = {**task, "error": error, "failed_at": datetime.now(UTC).isoformat()}
        await client.lpush(DLQ, json.dumps(entry))
        log.info("dlq_pushed task_type=%s investigation=%s", task.get("task_type"), task.get("investigation_id"))
    finally:
        await client.aclose()
