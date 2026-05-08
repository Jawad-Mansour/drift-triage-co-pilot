FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN uv pip install --no-cache \
    "mlflow==2.14.3" "xgboost<3" scikit-learn \
    pandas numpy scipy \
    "psycopg[binary]" \
    python-dotenv

COPY ml/ ml/

ENV PYTHONPATH=/app

CMD ["python", "ml/training/train.py"]
