import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from sqlalchemy import select

from backend.agent.agents.prompts.action import ACTION_EDGE_PROMPT
from backend.agent.agents.state import AgentState, DriftContext, TriageDecision
from backend.agent.core.logging import get_logger
from backend.agent.db.models import (
    DriftInvestigation,
    HILApproval,
    HILStatus,
    IdempotencyKey,
    InvestigationStatus,
)
from backend.agent.settings import get_settings

log = get_logger(__name__)

_REQUIRES_HIL = {"ROLLBACK", "RETRAIN_URGENT", "RETRAIN_SCHEDULED", "SWITCH_TO_FALLBACK"}


def _build_ikey(action: str, feature: str, severity: str) -> str:
    """hash(action + feature + hour_bucket + severity) — brainstorm Decision #29."""
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    return hashlib.sha256(f"{action}:{feature}:{hour}:{severity}".encode()).hexdigest()[:32]


def _rule_based_action(triage: TriageDecision, ctx: DriftContext, s) -> tuple[str, str] | None:
    """7-rule priority chain (brainstorm Decision #17). Returns (action, rationale) or None."""

    # Rule 1: model URI missing
    if ctx.model_uri_missing:
        return "SWITCH_TO_FALLBACK", "Model URI missing — switching to fallback"

    # Rule 2: AUC below threshold
    if ctx.model_auc is not None and ctx.model_auc < s.poor_performance_auc_threshold:
        return (
            "ROLLBACK",
            f"AUC {ctx.model_auc:.3f} below threshold {s.poor_performance_auc_threshold}",
        )

    # Rule 3: critical severity
    if triage.severity == "CRIT":
        return "ROLLBACK", f"CRITICAL drift (PSI={ctx.psi_score:.3f})"

    # Rule 4: economic feature + HIGH
    if ctx.economic_impact and triage.severity == "HIGH":
        return "RETRAIN_URGENT", f"Economic feature HIGH drift (PSI={ctx.psi_score:.3f})"

    # Rule 5: economic feature + MED
    if ctx.economic_impact and triage.severity == "MED":
        return "RETRAIN_SCHEDULED", "Economic feature MED drift — escalated to scheduled retrain"

    # Rule 6: recent retrain
    if ctx.recent_retrain and triage.severity in ("HIGH", "MED"):
        return (
            "REPLAY_TEST_SET",
            f"Retrained {ctx.minutes_since_retrain}min ago — replaying test set",
        )

    # Rule 7: standard severity mapping
    if triage.severity == "HIGH":
        return "RETRAIN_SCHEDULED", "HIGH severity — scheduling retrain"
    if triage.severity == "MED":
        return "REPLAY_TEST_SET", "MED severity — replaying test set"

    return "MONITOR", "LOW severity — monitoring only"


async def action_node(state: AgentState, config: RunnableConfig) -> dict:
    triage: TriageDecision = state["triage"]
    ctx: DriftContext = state["drift_context"]
    s = get_settings()

    result = _rule_based_action(triage, ctx, s)

    # Edge case: rules returned None — ask LLM (10% path, brainstorm Decision #15)
    if result is None:
        from backend.agent.agents.llm import invoke_with_fallback

        prompt = ACTION_EDGE_PROMPT.format(
            feature_name=ctx.feature_name,
            psi_score=ctx.psi_score,
            severity=triage.severity,
            economic_impact=ctx.economic_impact,
            minutes_since_retrain=ctx.minutes_since_retrain,
            model_auc=ctx.model_auc,
            chi2_pvalue=ctx.chi2_pvalue,
        )
        raw = await invoke_with_fallback(prompt, s)
        action = raw.strip().upper()
        rationale = "LLM edge-case decision"
    else:
        action, rationale = result

    ikey = _build_ikey(action, ctx.feature_name, triage.severity)
    sessionmaker = config.get("configurable", {}).get("sessionmaker")
    redis_client = config.get("configurable", {}).get("redis")
    action_dispatched = False

    # LangGraph re-executes the entire node on resume (interrupt() reruns from top).
    # Detect resume by querying for an APPROVED HIL — that record is committed to DB
    # by _resolve_hil before the graph task is created, so it's always present on resume.
    is_resume = False
    hil_approval_id: str | None = None
    if sessionmaker:
        async with sessionmaker() as session:
            resolved_hil = await session.scalar(
                select(HILApproval).where(
                    HILApproval.investigation_id == uuid.UUID(state["investigation_id"]),
                    HILApproval.status.in_([HILStatus.APPROVED, HILStatus.REJECTED]),
                )
            )
            if resolved_hil is not None:
                is_resume = True
                if resolved_hil.status == HILStatus.APPROVED:
                    hil_approval_id = str(resolved_hil.id)

    if sessionmaker and not is_resume:
        async with sessionmaker() as session:
            ttl = s.idempotency_ttl_retrain if "RETRAIN" in action else s.idempotency_ttl_other
            existing = await session.scalar(
                select(IdempotencyKey).where(
                    IdempotencyKey.key == ikey,
                    IdempotencyKey.expires_at > datetime.now(UTC),
                )
            )
            if existing:
                log.info("action_deduplicated", key=ikey, action=action)
                return {
                    "proposed_action": action,
                    "action_rationale": f"[DUPLICATE] {rationale}",
                    "idempotency_key": ikey,
                    "requires_hil": False,
                    "action_dispatched": False,
                    "next_node": "comms",
                }
            expires = datetime.now(UTC) + timedelta(seconds=ttl)
            session.add(
                IdempotencyKey(
                    key=ikey,
                    action_type=action,
                    feature_name=ctx.feature_name,
                    expires_at=expires,
                )
            )
            await session.commit()

    requires_hil = action in _REQUIRES_HIL
    hil_approved: bool | None = None
    hil_note: str | None = None

    if requires_hil:
        if sessionmaker and not is_resume:
            async with sessionmaker() as session:
                expires = datetime.now(UTC) + timedelta(minutes=s.approval_timeout_minutes)
                hil = HILApproval(
                    investigation_id=uuid.UUID(state["investigation_id"]),
                    thread_id=state["thread_id"],
                    proposed_action=action,
                    rationale=rationale,
                    status=HILStatus.PENDING,
                    expires_at=expires,
                )
                session.add(hil)
                inv = await session.get(DriftInvestigation, uuid.UUID(state["investigation_id"]))
                if inv:
                    inv.proposed_action = action
                    inv.status = InvestigationStatus.AWAITING_HIL
                await session.commit()
                await session.refresh(hil)
                hil_approval_id = str(hil.id)

        log.info(
            "action_hil_requested", action=action, hil_id=hil_approval_id, feature=ctx.feature_name
        )

        # Pause graph — resumes when operator calls /approve or /reject
        resume = interrupt({"action": action, "rationale": rationale})
        hil_approved = resume.get("hil_approved")
        hil_note = resume.get("hil_note", "")

        # A1: dispatch to worker queue after operator approves
        if hil_approved and redis_client:
            task = json.dumps({
                "task_type": action,
                "investigation_id": state["investigation_id"],
                "feature_name": ctx.feature_name,
                "thread_id": state["thread_id"],
            })
            await redis_client.lpush("queue:tasks", task)
            action_dispatched = True
            log.info("task_dispatched", action=action, feature=ctx.feature_name)

    if sessionmaker and not requires_hil and not is_resume:
        async with sessionmaker() as session:
            inv = await session.get(DriftInvestigation, uuid.UUID(state["investigation_id"]))
            if inv:
                inv.proposed_action = action
                await session.commit()

    # A2: REPLAY_TEST_SET bypasses HIL — dispatch immediately
    if action == "REPLAY_TEST_SET" and redis_client:
        task = json.dumps({
            "task_type": action,
            "investigation_id": state["investigation_id"],
            "feature_name": ctx.feature_name,
            "thread_id": state["thread_id"],
        })
        await redis_client.lpush("queue:tasks", task)
        action_dispatched = True
        log.info("task_dispatched", action=action, feature=ctx.feature_name)

    log.info(
        "action_decided",
        action=action,
        severity=triage.severity,
        requires_hil=requires_hil,
        feature=ctx.feature_name,
    )

    return {
        "proposed_action": action,
        "action_rationale": rationale,
        "idempotency_key": ikey,
        "requires_hil": requires_hil,
        "hil_approval_id": hil_approval_id,
        "hil_approved": hil_approved,
        "hil_note": hil_note,
        "action_dispatched": action_dispatched,
        "next_node": "comms",
    }
