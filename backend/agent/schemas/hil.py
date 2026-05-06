import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class HILApprovalRead(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    investigation_id: uuid.UUID
    thread_id: str
    proposed_action: str
    rationale: str
    status: str
    reviewer_note: str | None
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None


class HILApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    approved: bool
    note: str | None = Field(default=None, max_length=2000)
