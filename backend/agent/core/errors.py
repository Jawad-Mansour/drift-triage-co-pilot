from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.agent.core.logging import get_logger

log = get_logger(__name__)


class AgentError(Exception):
    """Agent node failed to produce a usable result."""


class ValidationError(Exception):
    """Payload is structurally valid but semantically wrong."""


class ProviderError(Exception):
    """Upstream LLM provider returned an error."""


class DriftWebhookError(Exception):
    """Drift webhook payload is invalid or cannot be processed."""


class HILTimeoutError(Exception):
    """HIL approval window expired."""


class IdempotencyError(Exception):
    """Action is a duplicate within the dedup window."""


class PlatformClientError(Exception):
    """Platform service returned an unexpected error."""


class TransientError(Exception):
    """Retryable failure — network, 5xx, rate-limit."""


class PermanentError(Exception):
    """Non-retryable failure — goes to DLQ."""


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentError)
    async def _agent(_req: Request, exc: AgentError) -> JSONResponse:
        log.warning("agent_error", error=str(exc))
        return JSONResponse(502, {"error": "agent_error", "detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def _validation(_req: Request, exc: ValidationError) -> JSONResponse:
        log.warning("validation_error", error=str(exc))
        return JSONResponse(400, {"error": "validation_error", "detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def _provider(_req: Request, exc: ProviderError) -> JSONResponse:
        log.error("provider_error", error=str(exc))
        return JSONResponse(502, {"error": "provider_error", "detail": str(exc)})

    @app.exception_handler(DriftWebhookError)
    async def _webhook(_req: Request, exc: DriftWebhookError) -> JSONResponse:
        log.warning("webhook_error", error=str(exc))
        return JSONResponse(422, {"error": "webhook_error", "detail": str(exc)})

    @app.exception_handler(HILTimeoutError)
    async def _hil(_req: Request, exc: HILTimeoutError) -> JSONResponse:
        log.warning("hil_timeout", error=str(exc))
        return JSONResponse(408, {"error": "hil_timeout", "detail": str(exc)})
