from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from backend.agent.db.session import get_session as _get_session  # noqa: F401 — re-exported
from backend.agent.settings import Settings, get_settings

_api_key_header = APIKeyHeader(name="X-Agent-API-Key", auto_error=False)


def get_settings_dep() -> Settings:
    return get_settings()


def get_graph(request: Request):
    return request.app.state.graph


def get_sessionmaker(request: Request):
    return request.app.state.sessionmaker


async def require_api_key(
    key: str | None = Security(_api_key_header),
) -> None:
    """Reject requests that don't carry the shared agent API key.

    Also accepts the emergency_bypass_key so ops can act during an outage
    without needing the normal key rotation flow.
    """
    settings = get_settings()
    valid = {
        settings.agent_api_key.get_secret_value(),
        settings.emergency_bypass_key.get_secret_value(),
    }
    if key not in valid:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
