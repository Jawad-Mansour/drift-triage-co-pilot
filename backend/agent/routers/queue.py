from fastapi import APIRouter, Depends, Request, Security

from backend.agent.deps import require_api_key

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/depth", dependencies=[Security(require_api_key)])
async def queue_depth(request: Request) -> dict:
    """Return task counts for the main queue and DLQ."""
    redis = request.app.state.redis
    main = await redis.llen("queue:tasks")
    dlq = await redis.llen("queue:tasks:dlq")
    return {"main_queue": main, "dlq": dlq}
