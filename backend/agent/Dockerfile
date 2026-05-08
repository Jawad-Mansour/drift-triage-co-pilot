FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN uv pip install --no-cache \
    fastapi "uvicorn[standard]" \
    pydantic pydantic-settings \
    "sqlalchemy[asyncio]" asyncpg "psycopg[binary,pool]" \
    langgraph langgraph-checkpoint-postgres \
    langchain-openai langchain-groq \
    redis httpx structlog tenacity python-dotenv

COPY backend/__init__.py backend/__init__.py
COPY backend/agent/ backend/agent/

ENV PYTHONPATH=/app

CMD ["uvicorn", "backend.agent.main:app", "--host", "0.0.0.0", "--port", "8002"]
