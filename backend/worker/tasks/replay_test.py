"""
Replay test set task — calls platform /replay-test to re-score the
held-out test set and log the metrics.
"""

import logging

import httpx

log = logging.getLogger(__name__)


async def handle_replay_test(task: dict, settings) -> None:
    investigation_id = task["investigation_id"]
    feature_name = task["feature_name"]

    log.info("replay_started feature=%s investigation=%s", feature_name, investigation_id)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.platform_url}/replay-test",
            json={"investigation_id": investigation_id, "feature_name": feature_name},
        )
        resp.raise_for_status()
        result = resp.json()

    log.info("replay_complete investigation=%s metrics=%s", investigation_id, result)
