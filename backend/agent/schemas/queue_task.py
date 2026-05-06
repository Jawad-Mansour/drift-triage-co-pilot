from typing import Any, Literal

from pydantic import BaseModel, Field


class QueueTask(BaseModel):
    """Task pushed onto Redis queue by the action executor."""

    model_config = {"extra": "forbid"}

    task_type: Literal[
        "RETRAIN",
        "RETRAIN_URGENT",
        "ROLLBACK",
        "REPLAY_TEST_SET",
        "SWITCH_TO_FALLBACK",
    ]
    investigation_id: str
    thread_id: str
    feature_name: str
    severity: str
    idempotency_key: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    """Status update written back to Postgres by the worker."""

    model_config = {"extra": "forbid"}

    investigation_id: str
    thread_id: str
    task_type: str
    status: Literal["completed", "failed"]
    detail: str | None = None
