from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.db.models import HILApproval, HILStatus
from backend.agent.db.session import get_session
from backend.agent.deps import require_api_key
from backend.agent.schemas.hil import HILApprovalRead

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _to_read(row: HILApproval) -> HILApprovalRead:
    return HILApprovalRead(
        id=row.id,
        investigation_id=row.investigation_id,
        thread_id=row.thread_id,
        proposed_action=row.proposed_action,
        rationale=row.rationale,
        status=row.status.value,
        reviewer_note=row.reviewer_note,
        expires_at=row.expires_at,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


@router.get("", response_model=list[HILApprovalRead], dependencies=[Security(require_api_key)])
async def list_pending_approvals(
    session: AsyncSession = Depends(get_session),
) -> list[HILApprovalRead]:
    """Dashboard polls this to show the HIL inbox."""
    rows = await session.scalars(
        select(HILApproval)
        .where(
            HILApproval.status == HILStatus.PENDING,
            HILApproval.expires_at > datetime.now(UTC),
        )
        .order_by(HILApproval.created_at.desc())
    )
    return [_to_read(r) for r in rows]
