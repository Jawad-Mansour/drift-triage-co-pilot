from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class DriftContext(BaseModel):
    """Validated drift payload received from the platform webhook."""

    feature_name: str
    psi_score: float = Field(ge=0.0)
    chi2_pvalue: float | None = Field(default=None, ge=0.0, le=1.0)
    model_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    model_uri_missing: bool = False
    model_version: str | None = None
    economic_impact: bool = False
    recent_retrain: bool = False
    minutes_since_retrain: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TriageDecision(BaseModel):
    """Output of the triage node — pure decision tree, no LLM."""

    severity: str  # LOW | MED | HIGH | CRIT
    psi_band: str  # LOW | MED | HIGH | CRIT
    chi2_band: str | None  # LOW | MED | HIGH | None
    economic_escalation: bool = False
    rationale: str


class AgentState(TypedDict, total=False):
    """Working memory for one drift investigation graph run.

    total=False: only thread_id and drift_context are required at entry.
    Every other field is populated by successive nodes.
    """

    # Entry
    thread_id: str
    investigation_id: str  # UUID of DriftInvestigation DB row

    drift_context: DriftContext

    # Triage node output
    triage: TriageDecision

    # Action node output
    proposed_action: str  # ROLLBACK | RETRAIN_URGENT | RETRAIN_SCHEDULED |
    # REPLAY_TEST_SET | SWITCH_TO_FALLBACK | MONITOR
    action_rationale: str
    idempotency_key: str | None

    # HIL
    requires_hil: bool
    hil_approval_id: str | None
    hil_approved: bool | None  # None = pending, True = approved, False = rejected
    hil_note: str | None

    # Execution
    action_dispatched: bool
    worker_job_id: str | None
    worker_status: str | None  # pending | completed | failed

    # Comms node output
    comms_message: str | None

    # Supervisor routing
    next_node: str | None
    step_count: int

    # LangGraph message channel
    messages: Annotated[list[BaseMessage], add_messages]
