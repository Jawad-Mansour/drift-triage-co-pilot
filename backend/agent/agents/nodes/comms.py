import uuid

from langchain_core.runnables import RunnableConfig

from backend.agent.agents.llm import invoke_with_fallback
from backend.agent.agents.prompts.comms import COMMS_PROMPT
from backend.agent.agents.state import AgentState, TriageDecision
from backend.agent.core.logging import get_logger
from backend.agent.db.models import DriftInvestigation, InvestigationStatus
from backend.agent.settings import get_settings

log = get_logger(__name__)


def _status_label(state: AgentState) -> str:
    if state.get("requires_hil") and state.get("hil_approved") is None:
        return "awaiting human approval"
    if state.get("hil_approved") is True:
        return "approved — executing"
    if state.get("hil_approved") is False:
        return "rejected by operator"
    return "executing autonomously"


async def comms_node(state: AgentState, config: RunnableConfig) -> dict:
    """Always uses LLM — brainstorm Decision #18."""
    triage: TriageDecision = state["triage"]
    ctx = state["drift_context"]
    action = state.get("proposed_action", "MONITOR")
    rationale = state.get("action_rationale", "")

    # Duplicate action — skip LLM, use minimal message
    if rationale.startswith("[DUPLICATE]"):
        msg = (
            f"Drift detected on {ctx.feature_name} (PSI={ctx.psi_score:.3f}, "
            f"severity={triage.severity}). Action {action} already dispatched "
            f"within the dedup window — no new task created."
        )
        log.info("comms_duplicate_skipped", action=action)
        sessionmaker = config.get("configurable", {}).get("sessionmaker")
        if sessionmaker:
            async with sessionmaker() as session:
                inv = await session.get(DriftInvestigation, uuid.UUID(state["investigation_id"]))
                if inv:
                    inv.comms_message = msg
                    inv.status = InvestigationStatus.COMPLETED
                    await session.commit()
        return {"comms_message": msg, "next_node": None}

    prompt = COMMS_PROMPT.format(
        feature_name=ctx.feature_name,
        psi_score=f"{ctx.psi_score:.4f}",
        severity=triage.severity,
        triage_rationale=triage.rationale,
        proposed_action=action,
        action_rationale=rationale,
        status=_status_label(state),
        operator_note=state.get("hil_note") or "none",
    )

    settings = get_settings()
    message = await invoke_with_fallback(prompt, settings)

    sessionmaker = config.get("configurable", {}).get("sessionmaker")
    if sessionmaker:
        async with sessionmaker() as session:
            inv = await session.get(DriftInvestigation, uuid.UUID(state["investigation_id"]))
            if inv:
                inv.comms_message = message
                inv.status = InvestigationStatus.COMPLETED
                await session.commit()

    log.info("comms_complete", action=action, chars=len(message))
    return {"comms_message": message, "next_node": None}
