from pydantic import BaseModel


class TriageRead(BaseModel):
    model_config = {"extra": "forbid"}

    severity: str
    psi_band: str
    chi2_band: str | None
    economic_escalation: bool
    rationale: str
