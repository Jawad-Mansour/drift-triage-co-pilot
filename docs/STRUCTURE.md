# Project Directory Structure

## Full Tree

```
drift-triage-co-pilot/
│
├── backend/                        # All Python services (Docker containers)
│   ├── agent/                      # LangGraph supervisor — YOUR service
│   │   ├── prompts/                # LLM prompt templates (.txt)
│   │   ├── routers/                # FastAPI route handlers
│   │   ├── schemas/                # Pydantic models (input/output contracts)
│   │   ├── services/               # Business logic
│   │   └── Dockerfile
│   ├── platform/                   # FastAPI serving + drift detection — TEAMMATE
│   │   ├── routers/                # /predict, /promote, /drift/report, /models
│   │   ├── schemas/                # Pydantic models
│   │   ├── services/               # Model loading, drift calc, webhook sender
│   │   └── Dockerfile
│   ├── trainer/                    # One-shot training service — TEAMMATE
│   │   └── Dockerfile
│   └── worker/                     # Redis queue consumer — SHARED
│       ├── tasks/                  # retrain, replay_test, rollback handlers
│       └── Dockerfile
│
├── frontend/                       # UI layer
│   └── dashboard/                  # Streamlit dashboard — SHARED
│       ├── pages/                  # 01_registry, 02_investigations, 03_queue, 04_hil
│       ├── components/             # websocket_client, polling_client
│       └── Dockerfile
│
├── ml/                             # Data science research layer (not Docker)
│   ├── notebooks/                  # EDA + model selection experiments (Jupyter)
│   ├── preprocessing/              # Feature engineering scripts (research)
│   ├── training/                   # Training experiments (feeds backend/trainer)
│   ├── evaluation/                 # Metrics, threshold tuning research
│   └── models/                     # Local saved artifacts (.gitignore this)
│
├── db/                             # Database layer
│   ├── init/                       # Postgres init SQL (runs on first container boot)
│   ├── schemas/                    # DDL reference files — one per table
│   ├── seeds/                      # Reference seed data SQL
│   └── migrations/                 # Placeholder for future Alembic migrations
│
├── data/                           # Dataset storage
│   ├── raw/                        # bank-additional-full.csv (UCI, never modify)
│   └── processed/                  # Cleaned dataset (duration dropped, pdays flag)
│
├── tests/                          # All tests
│   ├── test_agent/                 # Unit + integration tests for agent service
│   ├── test_platform/              # Tests for platform service
│   └── test_snapshots/             # Agent trajectory JSON fixtures (CI regression)
│
├── docs/                           # All documentation
│   ├── ARCH.md                     # Architecture diagrams + system design
│   ├── DECISIONS.md                # All 64 design decisions with reasoning
│   ├── RUNBOOK.md                  # Setup, run, demo, troubleshooting
│   ├── API_CONTRACT.md             # Every endpoint both services expose
│   ├── CODING_GUIDELINES.md       # 18 engineering standards for the codebase
│   ├── DATASET.md                  # UCI dataset facts, traps, drift narrative
│   └── STRUCTURE.md                # This file
│
├── scripts/                        # Utility scripts (not Docker)
│   ├── demo_drift.py               # --reset / --inject for Friday demo
│   ├── generate_snapshot.py        # Run agent once, save trajectory fixture
│   ├── update_fidelity.py          # Update expected probability after retrain
│   └── seed_db.py                  # Manual DB initialization helper
│
├── .github/workflows/test.yml      # CI: lint + tests + snapshot regression
│
├── docker-compose.yml              # All 8 services wired together
├── .env.example                    # Required + optional env vars with placeholders
├── .gitignore
├── .dockerignore
├── .pre-commit-config.yaml         # gitleaks + ruff + mypy hooks
├── pyproject.toml                  # Tool config: ruff, mypy, pytest
├── requirements.txt                # Package list — documentation only (use uv)
├── requirements-dev.txt            # Dev package list — documentation only
└── README.md                       # Project overview and quick start
```

---

## Why Each Directory Exists

### `backend/`
Groups all runnable Docker services. Every subdirectory here becomes a Docker container. Separation of concerns: agent, platform, trainer, and worker each have a single responsibility and can be built, tested, and restarted independently.

#### `backend/agent/`
Your service. The LangGraph supervisor that receives drift alerts, triages severity, decides actions, pauses for human approval, and dispatches tasks to Redis.

- **`routers/`** — FastAPI route handlers only. No business logic. Each file maps to one endpoint group: `webhook.py` (POST /webhook), `investigations.py` (GET /investigations), `approvals.py` (POST approve/reject), `queue.py` (GET /queue/status).
- **`services/`** — All business logic. `supervisor.py` is the LangGraph graph. `triage.py`, `action.py`, `comms.py` are the three sub-agents. `checkpoint.py` manages Postgres state. `platform_client.py` makes HTTP calls to the platform. `llm_client.py` wraps OpenAI + Groq with fallback.
- **`schemas/`** — Pydantic models for every boundary crossing: incoming webhook payload, investigation state, HIL requests, queue tasks, triage results, action decisions.
- **`prompts/`** — LLM prompt templates as `.txt` files. Never inline strings. `triage_agent.txt` (kept for consistency even though triage is rule-based), `action_agent.txt` (edge case prompts), `comms_agent.txt` (human-facing explanation prompts).

#### `backend/platform/`
Teammate's service. Serves predictions, calculates PSI/Chi² drift every 50 predictions over a 500-row window, fires webhooks when severity changes, and gates model promotions.

- **`routers/`** — `predict.py` (POST /predict), `promote.py` (POST /promote), `drift.py` (GET /drift/report), `registry.py` (GET /models).
- **`services/`** — `model.py` loads model from MLflow. `drift.py` runs PSI and Chi² calculations. `mlflow_client.py` interfaces with MLflow registry. `webhook_sender.py` posts alerts to agent. `promotion_gate.py` validates AUC, recall, and feature engineering checklist before allowing promotion.
- **`schemas/`** — `prediction.py`, `drift_alert.py`, `promote.py`.

#### `backend/trainer/`
Runs exactly once on `docker-compose up`. Trains XGBoost with Sigmoid calibration, tunes threshold (recall ≥ 0.75), registers v1 in MLflow with artifact triple (model binary + input schema + model card), seeds the `drift_reference` table in Postgres, then exits with code 0. All downstream services depend on this completing before they start.

#### `backend/worker/`
Listens on the Redis main queue using `BLPOP` in an async loop. Routes tasks to handlers in `tasks/`. On failure, re-queues with exponential backoff via Redis `ZADD`. After 5 failures, moves task to DLQ. Promotes models to Staging only — never to Production directly.

---

### `frontend/`
Groups all UI code. Separated from backend because it has no business logic, no database writes, and a different dependency set.

#### `frontend/dashboard/`
Streamlit dashboard. Shows model registry state, active and historical investigations, Redis queue depth, DLQ contents, and the HIL inbox with Approve/Reject buttons. Polls agent API every 2 seconds (WebSocket primary, polling fallback).

- **`pages/`** — One file per dashboard page (Streamlit multi-page convention).
- **`components/`** — Reusable client code for WebSocket and HTTP polling.

---

### `ml/`
The data science research layer. This is where exploration and experimentation happen — **not** production code. Nothing here runs in Docker. Results from here get productionized in `backend/trainer/`.

- **`notebooks/`** — Jupyter notebooks for EDA and model selection experiments.
- **`preprocessing/`** — Feature engineering scripts (drop `duration`, create `contacted_before` flag, handle `unknown` categories).
- **`training/`** — Training experiments that informed the XGBoost pipeline in `backend/trainer/`.
- **`evaluation/`** — Metric analysis, threshold tuning curves, AUC/recall tradeoff plots.
- **`models/`** — Local saved model artifacts. **Gitignored** — too large for version control, source of truth is MLflow.

---

### `db/`
Everything about the database schema. No application code here — pure SQL and configuration.

- **`init/`** — `01_create_databases.sql` runs once when Postgres container first boots (mounted at `/docker-entrypoint-initdb.d/`). Creates the `mlflow` database (the `drift_triage` database is created by `POSTGRES_DB` env var automatically).
- **`schemas/`** — DDL reference files, one per table: `predictions_log.sql`, `drift_reference.sql`, `investigations.sql`, `hil_approvals.sql`, `queue_tasks.sql`, `audit_log.sql`. These are documentation — the actual tables are created by `SQLAlchemy create_all` on service startup.
- **`seeds/`** — Reference seed data SQL (used for local development without running the full trainer).
- **`migrations/`** — Placeholder. We use `create_all` for this project. If the schema needed to evolve post-launch, Alembic would go here.

---

### `data/`
Dataset storage. Never commit actual data files — only `.gitkeep` markers.

- **`raw/`** — `bank-additional-full.csv` from UCI ML Repository. Read-only — never modify.
- **`processed/`** — Cleaned version: `duration` dropped, `pdays` converted to `contacted_before` flag.

---

### `tests/`
All automated tests. Kept at root level (not inside individual services) so a single `pytest` command runs everything, and the CI pipeline has one clear entry point.

- **`test_agent/`** — Unit tests per sub-agent (triage, action, comms) + integration tests for supervisor, checkpoints, HIL flow, and queue dispatch. All LLM calls use `MockLLM`.
- **`test_platform/`** — Tests for `/predict`, PSI/Chi² drift calculations, and promotion gate logic.
- **`test_snapshots/`** — Three JSON trajectory fixtures. Each is a complete agent run from webhook to outcome. CI compares live trajectories against these snapshots to catch regressions in decision logic.

---

### `docs/`
All human-facing documentation. Required for project submission.

| File | Purpose |
|------|---------|
| `ARCH.md` | System diagrams (5 Mermaid diagrams) + service map + data flow |
| `DECISIONS.md` | All 64 design decisions in a table + key decision details |
| `RUNBOOK.md` | Step-by-step setup, run, demo, crash recovery, troubleshooting |
| `API_CONTRACT.md` | Every endpoint both services expose + JSON schemas |
| `CODING_GUIDELINES.md` | 18 engineering standards — async, pydantic, DI, logging, security |
| `DATASET.md` | UCI dataset facts, known traps, features, drift demo narrative |
| `STRUCTURE.md` | This file |

---

### `scripts/`
One-off utility scripts that run locally, not in Docker.

- **`demo_drift.py`** — Friday demo driver. `--reset` cleans state; `--inject` sends 500 shifted predictions to trigger drift detection live.
- **`generate_snapshot.py`** — Runs one full agent investigation and saves the trajectory to `tests/test_snapshots/`. Run after any intentional behavior change.
- **`update_fidelity.py`** — Updates the expected `predict_proba` value after a model retrain (for the 1e-12 fidelity test).
- **`seed_db.py`** — Manually initializes Postgres tables without running the full Docker stack. Useful during development.

---

### Root Config Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Wires all 8 services: images, ports, env vars, healthchecks, depends_on, volumes |
| `.env.example` | Template for secrets — copy to `.env` and fill before first run |
| `.gitignore` | Excludes `.env`, `__pycache__`, `.venv`, `data/raw/`, `ml/models/` |
| `.dockerignore` | Excludes `.git`, `.env`, tests, docs from Docker build context |
| `.pre-commit-config.yaml` | Hooks: `gitleaks` (secret scan), `ruff` (lint), `mypy` (type check) |
| `pyproject.toml` | Config for ruff, mypy, and pytest — no build system (we use uv) |
| `requirements.txt` | Package list for documentation. Install with `uv sync`, not pip |
| `requirements-dev.txt` | Dev package list (pytest, ruff, mypy) — same rule |
| `README.md` | Project overview, quick start, team split |
