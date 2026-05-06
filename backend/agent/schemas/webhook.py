from typing import Any

from pydantic import BaseModel, Field


class DriftWebhookPayload(BaseModel):
    """Payload sent by the platform when drift is detected (Decision #11)."""

    model_config = {"extra": "forbid"}

    schema_version: str = "1.0"
    feature_name: str = Field(..., min_length=1, max_length=255)
    psi_score: float = Field(..., ge=0.0)
    chi2_pvalue: float | None = Field(default=None, ge=0.0, le=1.0)
    model_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    model_uri: str | None = None
    model_uri_missing: bool = False
    model_version: str | None = None
    minutes_since_retrain: int | None = Field(default=None, ge=0)
    window_size: int = Field(default=500, ge=1)
    timestamp: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class DriftWebhookResponse(BaseModel):
    model_config = {"extra": "forbid"}

    investigation_id: str
    thread_id: str
    status: str = "accepted"
