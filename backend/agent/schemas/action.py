import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActionLogEntry(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    investigation_id: uuid.UUID
    thread_id: str
    action_type: str
    feature_name: str
    severity: str
    payload: dict[str, Any]
    worker_status: str | None
    created_at: datetime
