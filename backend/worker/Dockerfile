FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN uv pip install --no-cache \
    pydantic pydantic-settings \
    redis httpx python-dotenv

COPY backend/__init__.py backend/__init__.py
COPY backend/worker/ backend/worker/

ENV PYTHONPATH=/app

CMD ["python", "-m", "backend.worker.main"]
