import uuid

from langchain_core.runnables import RunnableConfig

from backend.agent.agents.state import AgentState, DriftContext, TriageDecision
from backend.agent.core.logging import get_logger
from backend.agent.db.models import DriftInvestigation
from backend.agent.settings import get_settings

log = get_logger(__name__)

_SEVERITY_ORDER = ["LOW", "MED", "HIGH", "CRIT"]


def _psi_band(psi: float, s) -> str:
    if psi >= s.drift_psi_threshold_critical:
        return "CRIT"
    if psi >= s.drift_psi_threshold_high:
        return "HIGH"
    if psi >= s.drift_psi_threshold_medium:
        return "MED"
    return "LOW"


def _chi2_band(p: float | None, s) -> str | None:
    if p is None:
        return None
    if p <= s.drift_chi2_threshold_high:
        return "HIGH"
    if p <= s.drift_chi2_threshold_medium:
        return "MED"
    return "LOW"


def _escalate(severity: str) -> str:
    idx = _SEVERITY_ORDER.index(severity)
    return _SEVERITY_ORDER[min(idx + 1, len(_SEVERITY_ORDER) - 1)]


async def triage_node(state: AgentState, config: RunnableConfig) -> dict:
    """Pure decision tree — no LLM (brainstorm Decision #13)."""
    s = get_settings()
    ctx: DriftContext = state["drift_context"]

    psi_band = _psi_band(ctx.psi_score, s)
    chi2_band = _chi2_band(ctx.chi2_pvalue, s)

    # Final severity = worst of PSI and chi² signals (Decision #6 + #7)
    if chi2_band is not None:
        base_severity = (
            chi2_band
            if _SEVERITY_ORDER.index(chi2_band) > _SEVERITY_ORDER.index(psi_band)
            else psi_band
        )
    else:
        base_severity = psi_band

    # Economic feature escalation on top (Decision #14)
    economic_escalation = (
        ctx.economic_impact and ctx.psi_score > 0.15 and base_severity in ("MED", "HIGH")
    )
    severity = _escalate(base_severity) if economic_escalation else base_severity

    parts = [f"PSI={ctx.psi_score:.3f} → {psi_band}"]
    if chi2_band:
        parts.append(f"chi²_p={ctx.chi2_pvalue:.4f} → {chi2_band}")
    if chi2_band and chi2_band != psi_band:
        parts.append(f"worst signal used: {base_severity}")
    if economic_escalation:
        parts.append(f"economic escalation {base_severity}→{severity}")

    triage = TriageDecision(
        severity=severity,
        psi_band=psi_band,
        chi2_band=chi2_band,
        economic_escalation=economic_escalation,
        rationale="; ".join(parts),
    )

    sessionmaker = config.get("configurable", {}).get("sessionmaker")
    if sessionmaker:
        async with sessionmaker() as session:
            inv = await session.get(DriftInvestigation, uuid.UUID(state["investigation_id"]))
            if inv:
                inv.severity = severity
                await session.commit()

    log.info("triage_complete", feature=ctx.feature_name, severity=severity, psi=ctx.psi_score)
    return {"triage": triage, "next_node": "action"}
