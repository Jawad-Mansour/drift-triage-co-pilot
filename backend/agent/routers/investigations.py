import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Security
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.core.logging import get_logger
from backend.agent.db.models import (
    DriftInvestigation,
    HILApproval,
    HILStatus,
    InvestigationStatus,
)
from backend.agent.db.session import get_session
from backend.agent.deps import get_graph, get_sessionmaker, require_api_key
from backend.agent.schemas.hil import HILApprovalRequest
from backend.agent.schemas.investigation import InvestigationDetail, InvestigationSummary

router = APIRouter(prefix="/investigations", tags=["investigations"])
log = get_logger(__name__)


def _to_summary(row: DriftInvestigation) -> InvestigationSummary:
    return InvestigationSummary(
        id=row.id,
        thread_id=row.thread_id,
        feature_name=row.feature_name,
        psi_score=row.psi_score,
        severity=row.severity,
        status=row.status.value,
        proposed_action=row.proposed_action,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail(row: DriftInvestigation) -> InvestigationDetail:
    hil = next((h for h in row.hil_approvals if h.status == HILStatus.PENDING), None)
    return InvestigationDetail(
        id=row.id,
        thread_id=row.thread_id,
        feature_name=row.feature_name,
        psi_score=row.psi_score,
        severity=row.severity,
        status=row.status.value,
        proposed_action=row.proposed_action,
        comms_message=row.comms_message,
        action_rationale=None,
        requires_hil=hil is not None,
        hil_approved=None if hil else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[InvestigationSummary], dependencies=[Security(require_api_key)])
async def list_investigations(
    session: AsyncSession = Depends(get_session),
) -> list[InvestigationSummary]:
    rows = await session.scalars(
        select(DriftInvestigation).order_by(DriftInvestigation.created_at.desc()).limit(100)
    )
    return [_to_summary(r) for r in rows]


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetail,
    dependencies=[Security(require_api_key)],
)
async def get_investigation(
    investigation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> InvestigationDetail:
    row = await session.get(DriftInvestigation, investigation_id)
    if not row:
        raise HTTPException(404, "Investigation not found")
    return _to_detail(row)


async def _resolve_hil(
    investigation_id: uuid.UUID,
    body: HILApprovalRequest,
    approved: bool,
    session: AsyncSession,
    graph,
    sessionmaker,
) -> InvestigationDetail:
    row = await session.get(DriftInvestigation, investigation_id)
    if not row:
        raise HTTPException(404, "Investigation not found")

    hil = await session.scalar(
        select(HILApproval).where(
            HILApproval.investigation_id == investigation_id,
            HILApproval.status == HILStatus.PENDING,
        )
    )
    if not hil:
        raise HTTPException(409, "No pending HIL approval for this investigation")
    if hil.expires_at <= datetime.now(UTC):
        hil.status = HILStatus.EXPIRED
        await session.commit()
        raise HTTPException(410, "HIL approval window expired")

    hil.status = HILStatus.APPROVED if approved else HILStatus.REJECTED
    hil.reviewer_note = body.note
    hil.resolved_at = datetime.now(UTC)
    row.status = InvestigationStatus.RUNNING
    await session.commit()

    resume = {
        "hil_approved": approved,
        "hil_note": body.note or "",
        "next_node": "comms",
        "messages": [
            HumanMessage(content=f"HIL {'approved' if approved else 'rejected'}: {body.note or ''}")
        ],
    }
    config = {"configurable": {"thread_id": row.thread_id, "sessionmaker": sessionmaker}}
    asyncio.create_task(graph.ainvoke(Command(resume=resume), config=config))

    log.info("hil_resolved", investigation_id=str(investigation_id), approved=approved)
    await session.refresh(row)
    return _to_detail(row)


@router.post(
    "/{investigation_id}/approve",
    response_model=InvestigationDetail,
    dependencies=[Security(require_api_key)],
)
async def approve_investigation(
    investigation_id: uuid.UUID,
    body: HILApprovalRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_graph),
    sessionmaker=Depends(get_sessionmaker),
) -> InvestigationDetail:
    return await _resolve_hil(investigation_id, body, True, session, graph, sessionmaker)


@router.post(
    "/{investigation_id}/reject",
    response_model=InvestigationDetail,
    dependencies=[Security(require_api_key)],
)
async def reject_investigation(
    investigation_id: uuid.UUID,
    body: HILApprovalRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_graph),
    sessionmaker=Depends(get_sessionmaker),
) -> InvestigationDetail:
    return await _resolve_hil(investigation_id, body, False, session, graph, sessionmaker)
