from pydantic import BaseModel


class HealthResponse(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = "ok"
    service: str = "agent"


class ErrorResponse(BaseModel):
    model_config = {"extra": "forbid"}

    error: str
    detail: str | None = None
