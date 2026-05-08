FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN uv pip install --no-cache \
    fastapi "uvicorn[standard]" \
    pydantic pydantic-settings \
    "sqlalchemy[asyncio]" asyncpg \
    "mlflow==2.14.3" "xgboost<3" scikit-learn \
    pandas numpy scipy httpx \
    python-dotenv

COPY backend/__init__.py backend/__init__.py
COPY backend/platform/ backend/platform/
COPY ml/ ml/

ENV PYTHONPATH=/app

CMD ["uvicorn", "backend.platform.main:app", "--host", "0.0.0.0", "--port", "8001"]
