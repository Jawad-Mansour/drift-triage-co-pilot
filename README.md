# Drift Triage Co-Pilot

An automated MLOps system that monitors a production XGBoost model for data drift, triages severity with a LangGraph supervisor agent, dispatches corrective tasks through a Redis queue, and requires human approval before any Production change.

**AIE Program — Week 5 Pair Project**

---

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [Quick Start](#quick-start)
3. [Architecture](#architecture)
4. [Agent Workflow](#agent-workflow)
5. [Drift Detection Pipeline](#drift-detection-pipeline)
6. [Redis Queue Lifecycle](#redis-queue-lifecycle)
7. [Service Map](#service-map)
8. [Dataset](#dataset)
9. [Model](#model)
10. [API Contract](#api-contract)
11. [Design Decisions](#design-decisions)
12. [Runbook](#runbook)
13. [Project Structure](#project-structure)

---

## What This System Does

A production ML model (XGBoost, bank marketing classification) serves predictions. After every 50 predictions, the platform calculates PSI and Chi² drift scores over the last 500 rows. When drift severity crosses a threshold:

1. **Platform** fires a webhook to the Agent with drift metadata
2. **Agent** (LangGraph) triages the severity with a decision tree, selects a corrective action via priority rules, and pauses for human approval
3. **Human** approves or rejects in the Streamlit Dashboard
4. **Worker** executes the approved task (retrain / rollback / replay)
5. **Agent** generates an LLM explanation, closes the investigation, and updates the model registry

No Production change ever happens without a human approving it.

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in: OPENAI_API_KEY, GROQ_API_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, AGENT_API_KEY

# 2. Add the dataset
# Download bank-additional-full.csv from UCI ML Repository
# Place at: data/raw/bank-additional-full.csv

# 3. Start everything
docker compose up --build
```

Services start in dependency order automatically. `trainer` runs once, registers v1, then exits. All other services stay up.

**Access points:**

| Service | URL |
|---------|-----|
| Dashboard (HIL inbox, investigations, queue) | http://localhost:8501 |
| Platform API docs | http://localhost:8001/docs |
| Agent API docs | http://localhost:8002/docs |
| MLflow model registry | http://localhost:5000 |

**Trigger the drift demo:**

```bash
python scripts/demo_drift.py --reset    # clean state
python scripts/demo_drift.py --inject   # shift euribor3m + job distributions
# Watch the dashboard — investigation opens within seconds
```

---

## Architecture

### Full System Overview

```
  INFRASTRUCTURE                     MLFLOW :5000
  +------------+  +----------+       +---------------------------+
  | Postgres   |  | Redis    |       | Model Registry            |
  | :5432      |  | :6379    |       | (Postgres backend +       |
  +------------+  +----------+       |  mlflow_artifacts volume) |
                                     +---------------------------+

  TRAINER (runs once, exits 0)
  +--------------------------------------------------+
  | Train XGBoost  --> Register v1                   |
  | Seed drift_reference --> Exit 0                  |
  +--------------------------------------------------+

  PLATFORM :8001
  +--------------------------------------------------+
  | FastAPI                                          |
  | /predict  /promote  /drift/report  /registry     |
  |      |                                           |
  |      v                                           |
  | Drift Calculator  (PSI · Chi² · Output PSI)      |
  |      |                                           |
  |      v                                           |
  | Webhook Sender  (3 retries, exp backoff)         |
  +--------------------------------------------------+
            |
            | POST /webhook
            v
  AGENT :8002
  +--------------------------------------------------+
  | Supervisor                                       |
  |   |                                              |
  |   +--> Triage   (Decision Tree — NO LLM)        |
  |   |       |                                      |
  |   |       +--> Action  (Rules 90% + LLM 10%)    |
  |   |               |                              |
  |   |               +--> Comms   (Pure LLM)        |
  |   |                                              |
  |   +--> PostgresSaver Checkpoints                 |
  +--------------------------------------------------+
        |                    |
        | dispatch task       | read/write
        v                    v
  WORKER                POSTGRES :5432
  +------------------+
  | BLPOP loop       |
  | retrain          |
  | replay_test      |
  | rollback         |
  +------------------+

  DASHBOARD :8501
  +--------------------------------------------------+
  | Streamlit                                        |
  | HIL Inbox · Investigations · Registry · Queue    |
  +--------------------------------------------------+
        |
        | POST approve/reject
        v
  AGENT :8002
```

### Startup Dependency Chain

```
  postgres         redis
  (healthy) -----> (healthy)
      |
      +----------> mlflow
                   (healthy)
                       |
                       v
                   trainer
                   (exits 0) ---------> platform
                                        (healthy) --> agent
                                                      (healthy) --> dashboard
                                        (healthy) --> worker
                                                      (starts)
```

`trainer` must exit 0 before `platform` starts — the platform loads the Production model from MLflow on startup. If MLflow is empty, it crashes.

### Data Flows

| Source | Destination | What |
|--------|------------|------|
| Trainer | MLflow Registry | Register v1 with `champion` alias |
| Trainer | Postgres | Seed `drift_reference` table |
| Platform | Agent `POST /webhook` | Drift alert with PSI/severity |
| Agent | Redis | Dispatch approved task |
| Worker | Redis BLPOP | Consume task |
| Worker | MLflow | Register retrained model as Staging |
| Agent | Platform `POST /promote` | Promote Staging → Production after HIL |
| Dashboard | Agent `POST /approve` or `/reject` | Human decision |

### Database Ownership

| Table | Owner | Created by |
|-------|-------|-----------|
| `predictions_log` | Platform | `create_all` on startup |
| `drift_reference` | Platform | `create_all` on startup — **populated by trainer** |
| `audit_log` | Platform | `create_all` on startup |
| `investigations` | Agent | `create_all` on startup |
| `hil_approvals` | Agent | `create_all` on startup |
| `checkpoints` | Agent | LangGraph `PostgresSaver` — auto-creates |
| `queue_tasks` | Worker | `create_all` on startup |

Rule: Services communicate via HTTP only. No cross-service DB writes.

---

## Agent Workflow

The agent is a LangGraph graph with four nodes wired by a supervisor:

```
START → supervisor → triage → supervisor → action → supervisor → comms → END
```

### Supervisor

Pure router. Reads `next_node` from graph state and routes accordingly. Enforces a max-steps guard (8 steps) to prevent infinite loops. No business logic.

### Triage Node — Decision Tree, NO LLM

```
POST /webhook received
        |
        v
  +---------------------------+
  | Triage Agent              |
  | Decision Tree — NO LLM    |
  | Inputs: PSI / Chi²        |
  +---------------------------+
        |
        | severity
        v
  PSI band   →  LOW / MED / HIGH / CRIT
  Chi² band  →  LOW / MED / HIGH
  worst(both) = final severity
        |
        | economic feature? (euribor3m / cons.price.idx)
        | PSI > 0.15 → escalate +1 level
        v
  Output: severity code (LOW / MED / HIGH / CRIT)
```

PSI threshold table:

| Code | Label | PSI Range |
|------|-------|-----------|
| `LOW` | Low | < 0.10 |
| `MED` | Medium | 0.10 – 0.20 |
| `HIGH` | High | 0.20 – 0.25 |
| `CRIT` | Critical | ≥ 0.25 |

### Action Node — 7-Rule Priority Chain

Rules evaluated top-to-bottom, first match wins. LLM is called only for edge cases (borderline scores, conflicting signals, recent retrain within 24h).

| Priority | Condition | Action |
|----------|-----------|--------|
| 1 | No model in registry | `ESCALATE` |
| 2 | `CRIT` + economic feature | `ROLLBACK` |
| 3 | `CRIT` severity | `ROLLBACK` |
| 4 | `HIGH` severity | `RETRAIN_URGENT` |
| 5 | `MED` severity | `RETRAIN` |
| 6 | `LOW` severity | `REPLAY` |
| 7 | Fallback (edge cases) | LLM decides |

**HIL-required actions:** `RETRAIN_URGENT`, `ROLLBACK`, `SWITCH_TO_FALLBACK`

When HIL is required, the graph calls `interrupt()` — the LangGraph checkpoint is written to Postgres and execution pauses. The investigation flips to `awaiting_hil` and a card appears in the Dashboard HIL Inbox.

**Idempotency:** Each task has a key = `hash(action + feature + hour + severity)`. Duplicate drift in the same hour produces the same key — only one task is dispatched.

### HIL Pause / Resume

```
Action decides ROLLBACK (or RETRAIN_URGENT)
        |
        v
  interrupt() — graph checkpointed to Postgres
  Investigation status → awaiting_hil
  HIL card appears in Dashboard (10-min expiry)
        |
        v
  Human clicks APPROVE or REJECT
        |
  APPROVE              REJECT
        |                    |
  Validate:            Close investigation
  - not expired        (no task dispatched)
  - no new drift
        |
  Graph resumes from checkpoint
  Task dispatched to Redis
```

### Comms Node — Pure LLM

Always runs last, regardless of outcome. Calls GPT-4o-mini (Groq Llama fallback) to generate a human-readable explanation of what happened and why. The message is stored in `comms_message` on the investigation and displayed in the Dashboard Investigations tab.

Example output:
> "The drift monitoring dashboard has identified a critical issue with the euribor3m feature, showing a PSI score of 0.3500. As a result, a rollback has been approved and is currently being executed to address this significant drift."

### Checkpoint Milestones

The agent checkpoints to Postgres at 7 milestones so it can resume after a crash:

1. Investigation created (webhook received)
2. Triage complete
3. Action decision made
4. HIL request sent
5. HIL response received
6. Task dispatched to queue
7. Task confirmed complete

---

## Drift Detection Pipeline

```
  POST /predict
       |
       | log row
       v
  predictions_log (Postgres)
       |
       | every 50 predictions, window = last 500
       v
  +------------------+
  | Drift Calculator |
  +------------------+
       |         |         |
       v         v         v
  PSI           Chi²      Output PSI
  (numerical    (categori  (10 bins of
  features)     cal feats) predict_proba)
       |
       v
  worst(PSI, Chi²) → severity band
       |
       | economic feature escalation
       | euribor3m or cons.price.idx + PSI > 0.15 → +1 level
       v
  HIGH or CRIT → POST /webhook → Agent :8002
```

**Numerical features (PSI):** age, euribor3m, cons.price.idx, campaign, previous, emp.var.rate

**Categorical features (Chi²):** job, marital, education, contact, month, day_of_week

**Output drift (PSI):** 10 equal-width bins of `predict_proba` scores

---

## Redis Queue Lifecycle

```
  Agent dispatches task
  idempotency key = hash(action + feature + hour + severity)
          |
          v
  Key exists in Redis?
  |              |
  YES            NO
  |              |
  Skip        Main Queue (Redis LIST — FIFO)
  (duplicate       |
  within TTL)      | BLPOP (5-sec timeout)
                   v
  +--------------------------------+
  | Worker handler                 |
  | retrain / replay / rollback    |
  +--------------------------------+
          |
       Result?
       |       |
     SUCCESS  FAILURE
       |       |
  status=    retry count < 5?
  COMPLETED  |             |
             YES           NO
             |             |
         Delayed       Dead Letter Queue
         retry         (Redis LIST)
         1s/2s/4s/     Human reviews
         8s/16s        in Dashboard
```

**TTL:** 24h for RETRAIN tasks, 1h for all others.

---

## Service Map

| Service | Port | Purpose |
|---------|------|---------|
| `postgres` | 5432 | All persistent state: checkpoints, predictions, drift reference, investigations |
| `redis` | 6379 | Task queue + DLQ + idempotency keys |
| `mlflow` | 5000 | Model registry — Postgres backend, `mlflow_artifacts` volume |
| `trainer` | — | One-shot bootstrap: train → register v1 → seed `drift_reference` → exit 0 |
| `platform` | 8001 | Serve predictions, calculate drift, fire webhooks, gate promotions |
| `agent` | 8002 | LangGraph supervisor, HIL pause/resume, Redis dispatch |
| `worker` | — | Redis consumer: retrain / replay / rollback tasks |
| `dashboard` | 8501 | UI: HIL inbox, investigations, registry, queue depth |

---

## Dataset

**UCI Bank Marketing** — `bank-additional-full.csv`

| Property | Value |
|----------|-------|
| Rows | 41,188 |
| Features | 20 (19 used — `duration` dropped) |
| Target | Term deposit subscription (yes/no → 1/0) |
| Positive rate | ~11% (imbalanced) |
| Split | 60% train / 20% val / 20% test, stratified |

### Known Traps

| Trap | Problem | Decision |
|------|---------|----------|
| `duration` | Recorded after the call ends — leaks the target | **Drop entirely** |
| `pdays == 999` | Sentinel meaning "never contacted before" — not a real duration | Create `contacted_before = (pdays != 999)`, drop raw `pdays` |
| `unknown` categories | NOT missing data — the bank genuinely doesn't know | Treat as real category |

---

## Model

**Algorithm:** XGBoost + `CalibratedClassifierCV(method="sigmoid", cv=3)`

**Why calibration:** XGBoost probabilities are poorly calibrated on imbalanced data. Sigmoid calibration corrects this so `predict_proba` scores are reliable for threshold tuning.

**Threshold tuning:** Highest threshold where `recall >= 0.75` on validation split.

**Promotion gate:** `AUC > 0.80 AND Recall >= 0.75`

**Metrics (v1, test set):**

| Metric | Value |
|--------|-------|
| AUC | 0.8095 |
| F1 | 0.3495 |
| Recall | 0.7963 |
| Precision | 0.2239 |
| Threshold | 0.070 |

Low F1 / precision is expected and acceptable — the business problem is lead qualification where missing a subscriber (false negative) costs more than calling a non-subscriber (false positive).

---

## API Contract

### Platform Service — port 8001

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/predict` | Serve prediction, log to `predictions_log` |
| `POST` | `/promote` | Promote model version to Production |
| `GET` | `/drift/report` | Latest drift report with per-feature severities |
| `GET` | `/registry` | Champion model + all MLflow registry versions |
| `GET` | `/health` | Docker healthcheck |

### Agent Service — port 8002

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/webhook` | Receive drift alert, open investigation |
| `GET` | `/investigations` | List all investigations (open + closed) |
| `GET` | `/investigations/{id}` | Single investigation detail + trajectory |
| `POST` | `/investigations/{id}/approve` | Approve pending HIL request |
| `POST` | `/investigations/{id}/reject` | Reject pending HIL request |
| `GET` | `/queue/status` | Queue depth + DLQ count |
| `GET` | `/health` | Docker healthcheck |

### Webhook Payload — Platform → Agent

```json
{
  "schema_version": "1.0",
  "alert_id": "uuid4",
  "timestamp": "2026-05-06T14:30:00Z",
  "source": "platform-drift-detector",
  "model_version": "v1",
  "drift_type": "feature",
  "feature_name": "euribor3m",
  "psi_score": 0.31,
  "severity": "CRITICAL",
  "window_size": 500,
  "affected_predictions": 500
}
```

Response: `202 Accepted`

### Promote Payload — Agent → Platform

```json
{
  "schema_version": "1.0",
  "model_version": "v2",
  "investigation_id": "uuid4",
  "promoted_by": "agent_supervisor",
  "hil_approval_id": "uuid4",
  "reason": "Drift resolved. Promotion gate passed."
}
```

Header: `X-Agent-Key: <shared-secret>`

---

## Design Decisions

All 64 decisions are complete. Full source of truth: [docs/DECISIONS.md](docs/DECISIONS.md).

### Complete Decision Table

| # | Decision | Choice |
|---|----------|--------|
| 1 | ML Model | XGBoost + Sigmoid calibration (`CalibratedClassifierCV`, `random_state=42`) |
| 2 | pdays==999 | Boolean flag `contacted_before`, drop raw pdays |
| 3 | Drift window size | 500 predictions (sliding window) |
| 4 | Drift frequency | Recalculate every 50 new predictions |
| 5 | Predictions log | Postgres table `predictions_log` |
| 6 | PSI thresholds | <0.1 LOW · 0.1–0.2 MED · 0.2–0.25 HIGH · ≥0.25 CRIT |
| 7 | Chi² thresholds | p>0.05 LOW · 0.01–0.05 MED · ≤0.01 HIGH |
| 8 | Registry persistence | MLflow own service (:5000), Postgres backend + volume |
| 9 | Platform→Agent comms | Webhooks (not polling) |
| 10 | Polling interval | N/A — webhooks chosen |
| 11 | Webhook payload | JSON with `schema_version` field |
| 12 | HTTP status codes | Standard REST (200, 202, 400, 404, 409, 422, 500) |
| 13 | Triage agent | Decision tree — NO LLM |
| 14 | Severity rules | worst(PSI band, chi² band) + economic feature escalation |
| 15 | Action agent | Rules for 90% of cases, LLM for edge cases |
| 16 | Available actions | 7 actions (RETRAIN, RETRAIN_URGENT, ROLLBACK, REPLAY, MONITOR, ESCALATE, SWITCH_FALLBACK) |
| 17 | Action trigger logic | Priority-based rules (7 ordered rules) |
| 18 | Comms agent | Pure LLM — always required |
| 19 | Prompts storage | Python constants in `agents/prompts/action.py` + `comms.py` |
| 20 | Checkpoint content | Complete investigation state |
| 21 | Checkpoint frequency | 7 milestones + before every risky operation |
| 22 | Missing model URI | Ask human via HIL — no automatic fallback |
| 23 | Registry sync detection | Validate on resume, trust MLflow as source of truth |
| 24 | HIL required actions | RETRAIN (urgent), ROLLBACK, SWITCH_TO_FALLBACK |
| 25 | HIL approval validity | 10 minutes — staleness validated before dispatch |
| 26 | New drift during HIL | Open parallel investigation + warning, no auto-cancel |
| 27 | Dashboard HIL surface | Auto-refresh polling (2-second interval) |
| 28 | HIL comments | Optional free-text with audit trail |
| 29 | Idempotency key | `hash(action + feature + hour + severity)` |
| 30 | Idempotency TTL | 24h for retrain · 1h for all others |
| 31 | Retry strategy | 5 retries, exponential backoff: 1, 2, 4, 8, 16 seconds |
| 32 | DLQ handling | No auto-retry — human reviews via Dashboard |
| 33 | Task completion notification | Status updated in Postgres `queue_tasks` table |
| 34 | Promotion criteria | AUC > 0.80 AND Recall ≥ 0.75 at tuned threshold |
| 35 | Direct promotion bypass | Agent + emergency key (secret header) |
| 36 | Emergency mechanism | `X-Emergency-Key` header |
| 37 | Audit logging | Minimal — `audit_log` table on platform |
| 38 | Dashboard data source | Agent API (HTTP) — polls every 2 seconds |
| 39 | Dashboard refresh rate | 2 seconds (`streamlit-autorefresh`) |
| 40 | Dashboard sections | HIL Inbox · Investigations · Registry · Queue |
| 41 | LLM mock | Keyword-based dictionary (`MockLLM` class) for tests |
| 42 | Snapshot fixtures | Full agent trajectory JSON |
| 43 | Fidelity test input | Single fixed input, 1e-12 tolerance, versioned |
| 44 | CI platform | GitHub Actions |
| 45–46 | LLM provider | GPT-4o-mini primary + Groq Llama fallback |
| 47 | LLM reason for submission | Cost-effective reliability with free redundancy |
| 48 | LLM failure handling | tenacity retry → Groq fallback → template text |
| 49 | Docker services | 8 services (postgres, redis, mlflow, trainer, platform, agent, worker, dashboard) |
| 50 | Environment variables | See `.env.example` |
| 51 | Service discovery | Docker Compose service names as hostnames |
| 52 | Volumes | `postgres_data`, `redis_data`, `mlflow_artifacts` |
| 53 | Diagram tool | ASCII (inline in ARCH.md) |
| 54 | RUNBOOK detail | Full sections with exact commands |
| 55 | Output-distribution drift | PSI on 10 bins of `predict_proba` scores |
| 56 | Worker promotion rule | Worker → Staging only. Production = agent + HIL always |
| 57 | Agent→Platform promote contract | `POST /promote` JSON schema v1.0 + `X-Agent-Key` header |
| 58 | Bootstrap training flow | Dedicated `trainer` service — runs once, exits 0 |
| 59 | Reference distribution storage | Postgres `drift_reference` table, seeded by trainer |
| 60 | API endpoint inventory | 5 platform + 7 agent endpoints — see `API_CONTRACT.md` |
| 61 | Worker design | Custom async BLPOP loop + Redis ZADD delayed queue |
| 62 | DB init | SQLAlchemy `create_all` per service — no Alembic |
| 63 | Startup sequence | 8-service chain with `depends_on` + healthchecks |
| 64 | Demo simulation | `scripts/demo_drift.py --reset / --inject` |

### Drift Thresholds (Decisions 6, 7, 55)

| Metric | LOW | MEDIUM | HIGH | CRITICAL |
|--------|-----|--------|------|----------|
| PSI (numeric features) | < 0.1 | 0.1 – 0.2 | 0.2 – 0.25 | ≥ 0.25 |
| Chi² p-value (categorical) | > 0.05 | 0.01 – 0.05 | ≤ 0.01 | — |
| Output PSI (predict_proba) | < 0.1 | 0.1 – 0.2 | 0.2 – 0.25 | ≥ 0.25 |

Final severity = worst(PSI band, Chi² band). Economic escalation: `euribor3m` or `cons.price.idx` with PSI > 0.15 escalates +1 level.

### Agent Topology (Decisions 13–18)

```
Supervisor
├── Triage    → Decision tree (NO LLM). Inputs: PSI/Chi² numbers. Output: severity code.
├── Action    → Rules for 90%. LLM only for borderline scores, multiple simultaneous drifts,
│               recent retrain within 24h, or conflicting signals.
└── Comms     → Pure LLM always. Translates internal state to human-readable text.
```

### Checkpoint Milestones (Decision 21)

1. Investigation created (webhook received)
2. Triage complete
3. Action decision made
4. HIL request sent
5. HIL response received
6. Task dispatched to queue
7. Task confirmed complete

### Idempotency (Decisions 29–30)

```
key = hash(action + feature_name + current_hour + severity)
TTL = 24h for RETRAIN tasks
TTL = 1h  for all other tasks
```

Same drift in the same hour = same key = one task dispatched, duplicate silently dropped.

### The 5 Hard Problems — How We Solved Them

| Problem | Solution |
|---------|----------|
| Checkpoint & registry out of sync after crash | On resume: validate checkpoint model URI against MLflow. Trust MLflow as source of truth. |
| Missing model URI in checkpoint | Pause via HIL, ask human. No automatic fallback — safety first. |
| Duplicate retrain requests | Idempotency key with 24h TTL. Same drift in same hour = same key = one task. |
| Stale HIL approval | 10-minute expiry. Validate staleness before dispatch. |
| Production promotion bypass | Emergency key header. Normal path always requires agent + HIL. |

---

## Runbook

### Prerequisites

- Docker Desktop (with Compose v2)
- Git
- OpenAI API key (GPT-4o-mini)
- Groq API key (Llama fallback — free tier)

### Setup

```bash
git clone https://github.com/Jawad-Mansour/drift-triage-co-pilot.git
cd drift-triage-co-pilot

cp .env.example .env
# Edit .env — fill in the required secrets:
#   OPENAI_API_KEY, GROQ_API_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, AGENT_API_KEY

# Download bank-additional-full.csv from UCI ML Repository
# Place at: data/raw/bank-additional-full.csv
```

### Start the System

```bash
docker-compose up --build
```

Services start in order (automatic via healthchecks):
```
postgres → redis → mlflow → trainer → platform → agent → worker + dashboard
```

`trainer` runs once, registers v1 in MLflow, then exits. All other services stay up.

### Run a Prediction

All 19 fields are required. `pdays=999` means "never contacted before".

```bash
curl -X POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  -d '{
    "age": 35,
    "job": "admin.",
    "marital": "married",
    "education": "university.degree",
    "default": "no",
    "housing": "yes",
    "loan": "no",
    "contact": "cellular",
    "month": "may",
    "day_of_week": "mon",
    "campaign": 1,
    "pdays": 999,
    "previous": 0,
    "poutcome": "nonexistent",
    "emp.var.rate": -1.8,
    "cons.price.idx": 92.893,
    "cons.conf.idx": -46.2,
    "euribor3m": 1.313,
    "nr_employed": 5099.1
  }'
```

Expected: `{"prediction": 0, "probability": 0.042, "model_version": "1"}`

### Trigger Drift Demo

```bash
python scripts/demo_drift.py --reset    # clean state
python scripts/demo_drift.py --inject   # shift euribor3m + job distributions
```

**Demo flow:**
1. `--reset` → clean state, no drift
2. `--inject` → sends 500 shifted predictions
3. Platform detects PSI > 0.2 on euribor3m → fires webhook
4. Agent creates investigation, Dashboard shows HIL request
5. Click **APPROVE** in Dashboard HIL Inbox
6. Worker executes task (retrain or rollback)
7. Agent generates explanation, investigation marked `completed`
8. Dashboard Registry tab shows updated champion version

### End-to-End Pipeline Test (Step by Step)

#### Step 0 — Verify all services healthy

```powershell
docker-compose ps
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8001/registry
```

#### Step 1 — Fire a drift webhook

```powershell
$KEY = (Get-Content .env | Select-String "^AGENT_API_KEY=").ToString().Split("=",2)[1].Trim()

curl -X POST http://localhost:8002/webhook `
  -H "Content-Type: application/json" `
  -H "X-Agent-API-Key: $KEY" `
  -d '{
    "feature_name": "euribor3m",
    "psi_score": 0.35,
    "model_version": "1",
    "model_auc": 0.8095,
    "window_size": 500
  }'
```

Expected: `202 Accepted` with `investigation_id`.

#### Step 2 — Watch the investigation

```powershell
curl http://localhost:8002/investigations -H "X-Agent-API-Key: $KEY"
```

Within ~2 seconds: `status` → `awaiting_hil`. Dashboard HIL Inbox shows the pending card.

#### Step 3 — Approve via Dashboard or API

Via Dashboard: click **Approve** in the HIL Inbox tab at http://localhost:8501

Via API:
```powershell
$INV_ID = "<investigation_id from step 2>"
curl -X POST "http://localhost:8002/investigations/$INV_ID/approve" `
  -H "Content-Type: application/json" `
  -H "X-Agent-API-Key: $KEY" `
  -d '{"note": "Approved — euribor3m drift is real"}'
```

#### Step 4 — Watch worker execute

```powershell
docker-compose logs -f worker
```

Expected output:
```
task_attempt task_type=RETRAIN_URGENT attempt=1/5
retrain_complete model=BankMarketingXGB version=2
```

#### Step 5 — Verify investigation complete

```powershell
curl "http://localhost:8002/investigations/$INV_ID" -H "X-Agent-API-Key: $KEY"
# "status": "completed"
# "comms_message": "..." (LLM-generated explanation)
```

### Quick Smoke Tests

```powershell
$KEY = (Get-Content .env | Select-String "^AGENT_API_KEY=").ToString().Split("=",2)[1].Trim()

# Champion model loaded
curl http://localhost:8001/registry | python -m json.tool

# Agent DB-connected
curl http://localhost:8002/investigations -H "X-Agent-API-Key: $KEY"

# Redis queue empty
curl http://localhost:8002/queue/status -H "X-Agent-API-Key: $KEY"

# Replay test (non-destructive)
curl -X POST http://localhost:8001/replay-test

# Latest drift report
curl http://localhost:8001/drift/report
```

### Crash Recovery

```bash
# Kill agent mid-investigation
docker-compose stop agent

# Restart — resumes from last Postgres checkpoint automatically
docker-compose start agent
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Trainer exits non-zero | MLflow not ready | Increase `start_period` in mlflow healthcheck |
| Platform stuck on startup | Trainer didn't complete | Check `docker-compose logs trainer` |
| Agent can't reach platform | Platform not healthy | Check `docker-compose logs platform` |
| HIL request not appearing | Dashboard not polling | Refresh Dashboard, check `docker-compose logs agent` |
| Queue stuck | Redis auth failed | Verify `REDIS_PASSWORD` in `.env` |
| MLflow shows no models | Trainer skipped (model exists) | Normal on restart — model already in registry |
| `401 Unauthorized` on agent API | Missing `AGENT_API_KEY` | Set `X-Agent-API-Key` header or check `.env` |

### Useful Commands

```bash
docker-compose logs -f              # all service logs
docker-compose logs -f agent        # single service
docker-compose restart agent        # restart one service
docker-compose down -v && docker-compose up --build   # full reset
```

---

## Project Structure

```
drift-triage-co-pilot/
│
├── backend/
│   ├── agent/                  # LangGraph supervisor — agent service
│   │   ├── agents/nodes/       # triage.py, action.py, comms.py, supervisor.py
│   │   ├── routers/            # webhook.py, investigations.py, queue.py
│   │   ├── schemas/            # Pydantic models for all boundary crossings
│   │   ├── db/                 # SQLAlchemy models + session
│   │   └── Dockerfile
│   ├── platform/               # FastAPI serving + drift detection
│   │   ├── routers/            # predict.py, promote.py, drift.py, registry.py
│   │   ├── db/                 # predictions_log, drift_reference models
│   │   └── Dockerfile
│   ├── trainer/                # One-shot bootstrap: train → register v1 → exit 0
│   │   └── Dockerfile
│   └── worker/                 # Redis BLPOP consumer
│       ├── tasks/              # retrain.py, replay_test.py, rollback.py
│       └── Dockerfile
│
├── frontend/
│   └── dashboard/              # Streamlit dashboard
│       ├── app.py              # Single-file app: HIL Inbox, Investigations, Registry, Queue
│       ├── requirements.txt
│       └── Dockerfile
│
├── ml/
│   ├── training/train.py       # XGBoost + calibration + threshold tuning
│   └── notebooks/              # EDA and model selection experiments
│
├── data/
│   └── raw/                    # bank-additional-full.csv (not committed)
│
├── tests/
│   ├── test_agent/             # Unit + integration tests
│   └── test_platform/          # Platform service tests
│
├── docs/
│   ├── ARCH.md                 # System diagrams (5 ASCII diagrams)
│   ├── DECISIONS.md            # All 64 design decisions
│   ├── RUNBOOK.md              # Full setup, run, demo, troubleshooting
│   ├── API_CONTRACT.md         # Every endpoint + JSON schemas
│   ├── DATASET.md              # UCI dataset facts, traps, drift narrative
│   └── STRUCTURE.md            # Full directory tree with explanations
│
├── scripts/
│   ├── demo_drift.py           # --reset / --inject for demo
│   └── seed_db.py              # Manual DB initialization helper
│
├── docker-compose.yml          # All 8 services wired together
├── .env.example                # Required + optional env vars
├── pyproject.toml              # ruff, mypy, pytest config
└── requirements.txt            # Package list (install with: uv sync)
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | GPT-4o-mini for action edge cases + comms |
| `GROQ_API_KEY` | Yes | Llama fallback (free tier) |
| `POSTGRES_PASSWORD` | Yes | Shared Postgres password |
| `REDIS_PASSWORD` | Yes | Redis AUTH password |
| `AGENT_API_KEY` | Yes | Shared secret for agent API authentication |
| `POSTGRES_USER` | No | Default: `drift_user` |
| `POSTGRES_DB` | No | Default: `drift_triage` |
| `MLFLOW_TRACKING_URI` | No | Default: `http://mlflow:5000` |

---

## Development

```bash
uv sync --extra dev         # install all dependencies including dev tools
uv run pre-commit install   # enable git hooks (gitleaks + ruff + mypy)
uv run pytest               # run test suite (80% coverage required)
```

---

## Submission

```
Project 5 - Jawad Mansour

Repo: https://github.com/Jawad-Mansour/drift-triage-co-pilot
Tag: v0.1.0-week5
Dataset: UCI Bank Marketing (bank-additional-full.csv)
Model: BankMarketingXGB v1 (Test AUC: 0.8095 | Test F1: 0.3495)
Operating threshold: 0.070 (Recall: 0.7963 >= 0.75)
LLM: OpenAI GPT-4o-mini + Groq Llama fallback
     — cost-effective reliability with free redundancy
```
