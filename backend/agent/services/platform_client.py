from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.agent.core.errors import PlatformClientError
from backend.agent.core.logging import get_logger
from backend.agent.settings import Settings, get_settings

log = get_logger(__name__)

_RETRY = dict(
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
)


class PlatformClient:
    """Async HTTP client for the platform service (port 8001).

    All calls retry with exponential backoff: 1,2,4,8,16s — Decision #31.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._base = s.platform_url.rstrip("/")
        self._headers = {"X-Agent-Key": s.agent_api_key.get_secret_value()}

    @retry(**_RETRY)
    async def get_drift_report(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/drift/report", headers=self._headers)
        if resp.status_code != 200:
            raise PlatformClientError(f"get_drift_report: {resp.status_code}")
        return cast(dict[str, Any], resp.json())

    @retry(**_RETRY)
    async def get_models(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/models", headers=self._headers)
        if resp.status_code != 200:
            raise PlatformClientError(f"get_models: {resp.status_code}")
        return cast(dict[str, Any], resp.json())

    @retry(**_RETRY)
    async def promote_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /promote — called after HIL approval (Decision #57)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{self._base}/promote", json=payload, headers=self._headers)
        if resp.status_code not in (200, 201):
            raise PlatformClientError(f"promote_model: {resp.status_code} {resp.text}")
        return cast(dict[str, Any], resp.json())
