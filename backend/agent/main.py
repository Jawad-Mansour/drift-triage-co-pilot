from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.agent.agents.checkpointer import build_checkpointer
from backend.agent.agents.graph import build_graph
from backend.agent.core.errors import install_exception_handlers
from backend.agent.core.logging import configure_logging, get_logger, thread_id_ctx
from backend.agent.db.base import Base, build_engine, build_sessionmaker
from backend.agent.routers import approvals, investigations, webhook
from backend.agent.schemas.api import HealthResponse
from backend.agent.settings import get_settings


def create_app(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    sessionmaker: async_sessionmaker | None = None,
) -> FastAPI:
    """Application factory — tests inject checkpointer and sessionmaker."""
    settings = get_settings()
    configure_logging(level=settings.log_level, env=settings.app_env)
    log = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        # DB
        engine = None
        if sessionmaker is None:
            engine = build_engine(settings.database_url)
            app.state.sessionmaker = build_sessionmaker(engine)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            app.state.sessionmaker = sessionmaker

        # Checkpointer
        if checkpointer is None:
            app.state.checkpointer = await build_checkpointer(settings)
        else:
            app.state.checkpointer = checkpointer

        app.state.graph = build_graph(checkpointer=app.state.checkpointer)
        log.info("agent_ready", env=settings.app_env)

        yield

        if engine is not None:
            await engine.dispose()
        saver = app.state.checkpointer
        if callable(getattr(saver, "aclose", None)):
            await saver.aclose()

    app = FastAPI(title="drift-triage-agent", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def _request_id(request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid4().hex
        token = thread_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            thread_id_ctx.reset(token)
        response.headers["x-request-id"] = rid
        return response

    install_exception_handlers(app)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse()

    app.include_router(webhook.router)
    app.include_router(investigations.router)
    app.include_router(approvals.router)

    return app


app = create_app()
