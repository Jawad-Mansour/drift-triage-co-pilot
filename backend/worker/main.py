"""
Worker — BLPOP loop that consumes queue:tasks and dispatches to task handlers.
Retry: 1s / 2s / 4s / 8s / 16s (5 attempts), then → DLQ.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from backend.worker.queue.dlq import push_to_dlq
from backend.worker.settings import get_settings
from backend.worker.tasks.replay_test import handle_replay_test
from backend.worker.tasks.retrain import handle_retrain
from backend.worker.tasks.rollback import handle_rollback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

QUEUE = "queue:tasks"
RETRY_DELAYS = [1, 2, 4, 8, 16]

HANDLERS = {
    "RETRAIN_SCHEDULED": handle_retrain,
    "RETRAIN_URGENT": handle_retrain,
    "ROLLBACK": handle_rollback,
    "SWITCH_TO_FALLBACK": handle_rollback,
    "REPLAY_TEST_SET": handle_replay_test,
}


async def run_with_retry(task: dict, settings) -> None:
    task_type = task.get("task_type", "")
    inv_id = task.get("investigation_id", "?")
    handler = HANDLERS.get(task_type)

    if handler is None:
        log.warning("unknown_task_type task_type=%s", task_type)
        return

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            log.info(
                "task_attempt task_type=%s attempt=%d/%d investigation=%s",
                task_type, attempt, len(RETRY_DELAYS), inv_id,
            )
            await handler(task, settings)
            log.info("task_complete task_type=%s investigation=%s", task_type, inv_id)
            return
        except Exception as exc:
            log.error("task_error attempt=%d error=%s", attempt, exc)
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)
            else:
                log.error("task_exhausted — moving to DLQ investigation=%s", inv_id)
                await push_to_dlq(task, str(exc), settings)


async def main() -> None:
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    log.info("worker_ready queue=%s", QUEUE)

    try:
        while True:
            result = await redis_client.blpop(QUEUE, timeout=5)
            if result is None:
                continue
            _, raw = result
            try:
                task = json.loads(raw)
            except json.JSONDecodeError:
                log.error("invalid_json raw=%s", raw[:200])
                continue
            # Fire-and-forget — each task runs independently with its own retry budget
            asyncio.create_task(run_with_retry(task, settings))
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
