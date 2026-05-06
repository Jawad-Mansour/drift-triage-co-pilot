import uuid
from datetime import datetime

from pydantic import BaseModel


class InvestigationSummary(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    thread_id: str
    feature_name: str
    psi_score: float | None
    severity: str
    status: str
    proposed_action: str | None
    created_at: datetime
    updated_at: datetime


class InvestigationDetail(InvestigationSummary):
    action_rationale: str | None = None
    comms_message: str | None = None
    requires_hil: bool = False
    hil_approved: bool | None = None
