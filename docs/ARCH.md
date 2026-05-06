# Architecture — Drift Triage Co-Pilot

## What It Is

An automated MLOps system: a production ML model is monitored for data drift, the severity is
triaged by a LangGraph supervisor, corrective tasks are dispatched through a Redis queue, and a
human approves before anything reaches Production.

---

## Diagram 1 — Full System Overview

```
  INFRASTRUCTURE                     MLFLOW :5000
  +------------+  +----------+       +---------------------------+
  | Postgres   |  | Redis    |       | Model Registry            |
  | :5432      |  | :6379    |       | (Postgres backend +       |
  +------------+  +----------+       |  mlflow_artifacts volume) |
                                     +---------------------------+

  TRAINER (runs once, exits 0)
  +--------------------------------------------------+
  | Train LightGBM --> Register v1                   |
  | Seed drift_reference --> Exit 0                  |
  +--------------------------------------------------+

  PLATFORM :8001 (teammate)
  +--------------------------------------------------+
  | FastAPI                                          |
  | /predict  /promote  /drift/report  /models       |
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
  AGENT :8002 (your service)
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
  WORKER (shared)      POSTGRES :5432
  +------------------+
  | BLPOP loop       |
  | retrain          |
  | replay_test      |
  | rollback         |
  +------------------+

  DASHBOARD :8501 (shared)
  +--------------------------------------------------+
  | Streamlit                                        |
  | HIL inbox · Investigations · Registry · Queue    |
  +--------------------------------------------------+
        |
        | POST approve/reject
        v
  AGENT :8002
```

Data flows (summary):
  Trainer  -->  MLflow Registry (register v1)
  Trainer  -->  Postgres (seed drift_reference)
  Platform -->  Agent POST /webhook (drift alert)
  Agent    -->  Redis (dispatch task)
  Worker   -->  Redis BLPOP (consume task)
  Worker   -->  MLflow (register Staging candidate)
  Agent    -->  Platform POST /promote (after HIL approval)
  Dashboard --> Agent POST approve/reject
  Dashboard --> Postgres (read-only)

---

## Diagram 2 — Startup Dependency Chain

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

Rule: `trainer` must exit 0 before `platform` starts — the platform loads the Production model
from MLflow on startup. If MLflow is empty, it crashes.

---

## Diagram 3 — Agent Internal Flow

```
  POST /webhook
  (drift alert received)
          |
          v
  +---------------+
  |   Supervisor  | --> checkpoint #1 (investigation created) --> Postgres
  +---------------+
          |
          v
  +---------------------------+
  |   Triage Agent            |
  |   Decision Tree — NO LLM  |
  |   Inputs: PSI / Chi²      |
  +---------------------------+
          |
          | severity
          v
  +---------------------------+
  |   Action Agent            | --> checkpoint #2 (action decided) --> Postgres
  |   Rules for 90%           |
  |   LLM only for edge cases |
  +---------------------------+
          |
          v
  HIL required?
  |             |
  YES           NO (MONITOR / REPLAY)
  |             |
  v             v
  Pause graph   Redis Queue --> Worker BLPOP --> Comms Agent --> Dashboard
  Send HIL to
  Dashboard
  (10-min expiry)
          |
          v
  Human response
  |                |
  APPROVE          REJECT
  (within 10 min)  |
  |                v
  v           Close investigation
  Validate:
  - not expired
  - no new drift
          |
          v
  Redis Queue --> Worker BLPOP
          |
          v
  +---------------------------+
  |   Comms Agent             |
  |   Pure LLM                |
  |   Generates human summary |
  +---------------------------+
          |
          v
  Dashboard notification
```

---

## Diagram 4 — Drift Detection Pipeline

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
  features:     cal featu  predict_proba
  age,          res: job,  scores)
  euribor3m,    marital,
  ...)          ...)
       |         |         |
       +----+----+----------+
            |
            v
       Severity?
       |    |    |    |
       v    v    v    v
      <0.1 0.1- 0.2- >=0.25
      LOW  0.2  0.25  CRITICAL
           MED  HIGH  --> POST /webhook --> Agent :8002
                |
                | economic feature?
                | (euribor3m / cons.price.idx)
                v
            CRITICAL (escalate)
```

---

## Diagram 5 — Redis Queue Lifecycle

```
  Agent dispatches task
  idempotency key = hash(action + feature + hour + severity)
          |
          v
  Key exists in Redis?
  |              |
  YES            NO
  |              |
  v              v
  Skip        Main Queue (Redis LIST — FIFO)
  (duplicate       |
  within TTL)      | BLPOP (5-sec timeout)
                   v
  +--------------------------------+
  | Worker handler                 |
  | retrain / replay / rollback    |
  +--------------------------------+
          |
          v
       Result?
       |       |
     SUCCESS  FAILURE
       |       |
       v       v
  Update     retry count < 5?
  queue_     |             |
  tasks      YES           NO (5 failures)
  status=    |             |
  COMPLETED  v             v
  Release  Delayed Queue  Dead Letter Queue
  idemp.   (Redis ZADD    (Redis LIST)
  key      score=Unix     Human reviews
           timestamp)     in Dashboard
           1s/2s/4s/8s/16s
               |
               | time reached
               | ZRANGEBYSCORE
               v
           Main Queue
```

---

## Service Map

| Service   | Port | Owner    | Purpose                                                                        |
|-----------|------|----------|--------------------------------------------------------------------------------|
| postgres  | 5432 | Infra    | All persistent state: checkpoints, predictions, drift reference, investigations |
| redis     | 6379 | Infra    | Task queue + DLQ + idempotency keys                                            |
| mlflow    | 5000 | Infra    | Model registry — Postgres backend, `mlflow_artifacts` volume                   |
| trainer   | —    | Teammate | One-shot bootstrap: train → register v1 → seed `drift_reference` → exit 0      |
| platform  | 8001 | Teammate | Serve predictions, calculate drift, fire webhooks, gate promotions             |
| agent     | 8002 | You      | LangGraph supervisor, HIL pause/resume, Redis dispatch                         |
| worker    | —    | Shared   | Redis consumer: retrain / replay / rollback tasks                              |
| dashboard | 8501 | Shared   | UI: HIL inbox, investigations, registry, queue depth                           |

---

## Database Ownership

| Table             | Owner    | Created by                                                 |
|-------------------|----------|------------------------------------------------------------|
| `predictions_log` | Platform | `create_all` on startup                                    |
| `drift_reference` | Platform | `create_all` on startup — **populated by trainer**         |
| `audit_log`       | Platform | `create_all` on startup                                    |
| `investigations`  | Agent    | `create_all` on startup                                    |
| `hil_approvals`   | Agent    | `create_all` on startup                                    |
| `checkpoints`     | Agent    | LangGraph `PostgresSaver` — auto-creates                   |
| `queue_tasks`     | Worker   | `create_all` on startup                                    |

Rule: Services talk via HTTP only. No cross-service DB writes. Dashboard may read Postgres
directly (read-only).

---

## Key Design Decisions

| What                    | Choice                          | Why                                                                 |
|-------------------------|---------------------------------|---------------------------------------------------------------------|
| Platform→Agent comms    | Webhooks                        | Sub-second for economic feature drift — polling would be too slow   |
| Triage logic            | Decision tree, NO LLM           | PSI is a number. Comparing to 0.2 doesn't need an AI               |
| Action logic            | Rules 90%, LLM edge cases       | Deterministic for common cases; LLM only where judgment is needed   |
| Comms logic             | Pure LLM always                 | Humans read sentences, not PSI=0.31                                 |
| Checkpoint backend      | Postgres `PostgresSaver`        | Already in stack, crash-resilient, queryable                        |
| Queue implementation    | Custom async BLPOP              | ~60 lines, transparent, no Celery/arq overhead                      |
| MLflow backend          | Own Docker + Postgres           | SQLite has file-locking issues under concurrent Docker writes       |
| Production promotion    | Agent + HIL always              | Safety — no automatic production changes ever                       |
