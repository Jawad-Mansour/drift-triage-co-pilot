# Drift Triage Co-Pilot

Automated MLOps system that monitors a production LightGBM model for data drift, triages severity
with a LangGraph supervisor, dispatches corrective tasks through Redis, and requires human approval
before any Production change.

**AIE Program — Week 5 Pair Project**

---

## Quick Start

```bash
cp .env.example .env        # fill in OPENAI_API_KEY, GROQ_API_KEY, passwords
docker compose up --build   # starts all 8 services
```

Access points:
- Dashboard: http://localhost:8501
- Platform API: http://localhost:8001/docs
- Agent API: http://localhost:8002/docs
- MLflow UI: http://localhost:5000

---

## Demo

```bash
# Reset state and inject shifted euribor3m values to trigger drift
python scripts/demo_drift.py --reset
python scripts/demo_drift.py --inject
```

---

## Team Split

| Branch             | Owner    | Services                       |
|--------------------|----------|--------------------------------|
| `feature/agent`    | Jawad    | agent, worker, dashboard       |
| `feature/platform` | Teammate | platform, trainer, mlflow      |
| `main`             | Both     | docker-compose, db, scripts, docs |

---

## Development Setup

```bash
uv sync --extra dev          # install all dependencies including dev tools
uv run pre-commit install    # enable git hooks (gitleaks + ruff + mypy)
uv run pytest                # run test suite
```

---

## Environment Variables

See `.env.example` for all required and optional variables.
Required: `OPENAI_API_KEY`, `GROQ_API_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`

---

## Architecture

See [docs/ARCH.md](docs/ARCH.md) for full system diagrams and design decisions.
