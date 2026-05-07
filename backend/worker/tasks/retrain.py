"""
Retrain task — calls platform /retrain, then notifies agent to create
the 2nd HIL (PROMOTE_TO_PRODUCTION) once the new model is in Staging.
"""

import logging

import httpx

log = logging.getLogger(__name__)


async def handle_retrain(task: dict, settings) -> None:
    investigation_id = task["investigation_id"]
    feature_name = task["feature_name"]
    task_type = task.get("task_type", "RETRAIN_SCHEDULED")

    log.info("retrain_started task_type=%s feature=%s investigation=%s", task_type, feature_name, investigation_id)

    # Step 1: trigger platform retrain
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{settings.platform_url}/retrain",
            json={"investigation_id": investigation_id, "feature_name": feature_name},
        )
        resp.raise_for_status()
        result = resp.json()

    model_version = str(result.get("model_version", ""))
    model_name = result.get("model_name", "BankMarketingXGB")
    log.info("retrain_complete model=%s version=%s", model_name, model_version)

    # Step 2: notify agent → creates PROMOTE_TO_PRODUCTION HIL
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.agent_url}/investigations/{investigation_id}/notify_retrain_complete",
            json={"model_name": model_name, "model_version": model_version},
            headers={"X-Agent-API-Key": settings.agent_api_key.get_secret_value()},
        )
        resp.raise_for_status()

    log.info("retrain_hil_requested investigation=%s", investigation_id)
