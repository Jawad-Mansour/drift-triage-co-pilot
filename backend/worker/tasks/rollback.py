"""
Rollback / SWITCH_TO_FALLBACK task — calls platform /registry/promote
to roll back to the previous Production alias.
"""

import logging

import httpx

log = logging.getLogger(__name__)


async def handle_rollback(task: dict, settings) -> None:
    investigation_id = task["investigation_id"]
    task_type = task.get("task_type", "ROLLBACK")

    log.info("rollback_started task_type=%s investigation=%s", task_type, investigation_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.platform_url}/registry/promote",
            json={
                "model_name": "BankMarketingXGB",
                "candidate_version": "previous",
                "approved_by": "agent-worker",
                "investigation_id": investigation_id,
                "reason": f"{task_type} — automatic rollback to last known good version",
            },
        )
        resp.raise_for_status()

    log.info("rollback_complete investigation=%s", investigation_id)
