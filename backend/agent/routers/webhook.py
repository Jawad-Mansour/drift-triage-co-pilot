import asyncio
import uuid

from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.agents.state import AgentState, DriftContext
from backend.agent.core.logging import get_logger, thread_id_ctx
from backend.agent.db.models import DriftInvestigation, InvestigationStatus
from backend.agent.db.session import get_session
from backend.agent.deps import get_graph, get_redis, get_sessionmaker, get_settings_dep, require_api_key
from backend.agent.schemas.webhook import DriftWebhookPayload, DriftWebhookResponse
from backend.agent.settings import Settings

router = APIRouter(tags=["webhook"])
log = get_logger(__name__)


@router.post(
    "/webhook",
    response_model=DriftWebhookResponse,
    status_code=202,
    dependencies=[Security(require_api_key)],
)
async def receive_drift(
    payload: DriftWebhookPayload,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_graph),
    sessionmaker=Depends(get_sessionmaker),
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
) -> DriftWebhookResponse:
    """Receive drift alert from platform, open investigation, launch graph (202)."""
    thread_id = uuid.uuid4().hex
    token = thread_id_ctx.set(thread_id)

    ctx = DriftContext(
        feature_name=payload.feature_name,
        psi_score=payload.psi_score,
        chi2_pvalue=payload.chi2_pvalue,
        model_auc=payload.model_auc,
        model_uri_missing=payload.model_uri_missing,
        model_version=payload.model_version,
        economic_impact=payload.feature_name in settings.economic_feature_list,
        recent_retrain=(
            payload.minutes_since_retrain is not None
            and payload.minutes_since_retrain < settings.recent_retrain_threshold_minutes
        ),
        minutes_since_retrain=payload.minutes_since_retrain,
        raw=payload.raw,
    )

    investigation = DriftInvestigation(
        thread_id=thread_id,
        feature_name=payload.feature_name,
        psi_score=payload.psi_score,
        severity="PENDING",
        drift_payload=payload.model_dump(),
        status=InvestigationStatus.RUNNING,
    )
    session.add(investigation)
    await session.commit()
    await session.refresh(investigation)

    log.info("webhook_received", feature=payload.feature_name, psi=payload.psi_score)

    initial_state: AgentState = {
        "thread_id": thread_id,
        "investigation_id": str(investigation.id),
        "drift_context": ctx,
        "next_node": "triage",
        "messages": [],
    }
    config = {"configurable": {"thread_id": thread_id, "sessionmaker": sessionmaker, "redis": redis}}
    asyncio.create_task(graph.ainvoke(initial_state, config=config))

    thread_id_ctx.reset(token)
    return DriftWebhookResponse(
        investigation_id=str(investigation.id),
        thread_id=thread_id,
    )
