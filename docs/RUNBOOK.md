# Runbook — Drift Triage Co-Pilot

## Prerequisites

- Docker Desktop (with Compose v2)
- Git
- OpenAI API key (GPT-4o-mini)
- Groq API key (Llama fallback — free tier)

---

## Setup

```bash
git clone <repo-url>
cd drift-triage-co-pilot

cp .env.example .env
# Edit .env — fill in the 4 required secrets:
#   OPENAI_API_KEY, GROQ_API_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
```

Add the dataset to `data/raw/`:
```bash
# Download bank-additional-full.csv from UCI ML Repository
# Place at: data/raw/bank-additional-full.csv
```

---

## Start the System

```bash
docker-compose up --build
```

Services start in order (automatic via healthchecks):
```
postgres → redis → mlflow → trainer → platform → agent → worker + dashboard
```

`trainer` runs once, registers v1 in MLflow, then exits. All other services stay up.

---

## Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| Dashboard | http://localhost:8501 | Main UI — HIL inbox, investigations, queue |
| Platform API | http://localhost:8001 | Model serving + drift reports |
| Agent API | http://localhost:8002 | Investigation state + approvals |
| MLflow UI | http://localhost:5000 | Model registry browser |

---

## Run a Prediction

All 19 fields are required. `pdays=999` means "never contacted before".
Fields with dots (`emp.var.rate` etc.) can be sent either way — both the alias
and the Python name are accepted by the platform.

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

Expected response:
```json
{"prediction": 0, "probability": 0.042, "model_version": "3"}
```

---

## Trigger Drift Demo

```bash
# Reset to clean state
python scripts/demo_drift.py --reset

# Inject drift (shifts euribor3m + job distribution)
python scripts/demo_drift.py --inject

# Watch the dashboard — agent should open an investigation within seconds
```

**Demo flow:**
1. `--reset` → clean state, no drift
2. `--inject` → sends 500 shifted predictions
3. Platform detects PSI > 0.2 on euribor3m → fires webhook
4. Agent creates investigation, Dashboard shows HIL request
5. Click APPROVE in Dashboard
6. Worker retrains model, promotes v2 to Staging
7. Agent calls /promote → v2 to Production
8. Dashboard shows "Production: v2"

---

---

## End-to-End Pipeline Test (Step by Step)

This verifies the entire pipeline without needing the demo script.
Run each step, then observe the result before continuing.

### Step 0 — Verify all services healthy

```powershell
# All should show "healthy" or running
docker-compose ps
curl http://localhost:8001/health          # Platform
curl http://localhost:8002/health          # Agent
curl http://localhost:8001/registry        # Champion model loaded
```

### Step 1 — Fire a drift webhook to the agent

This simulates what the platform sends when PSI > 0.2 on `euribor3m`.

```powershell
$KEY = (Get-Content .env | Select-String "^AGENT_API_KEY=").ToString().Split("=",2)[1].Trim()

curl -X POST http://localhost:8002/webhook `
  -H "Content-Type: application/json" `
  -H "X-Agent-API-Key: $KEY" `
  -d '{
    "feature_name": "euribor3m",
    "psi_score": 0.35,
    "model_version": "3",
    "model_auc": 0.8095,
    "window_size": 500
  }'
```

Expected: `202 Accepted` with `investigation_id` and `thread_id`.

### Step 2 — Watch the investigation appear

```powershell
curl http://localhost:8002/investigations `
  -H "X-Agent-API-Key: $KEY"
```

Within ~2 seconds:
- `status` → `awaiting_hil` (action decided: ROLLBACK or RETRAIN_URGENT)
- Dashboard HIL Inbox shows the pending approval card

### Step 3 — Check what HIL is pending

```powershell
curl http://localhost:8002/approvals `
  -H "X-Agent-API-Key: $KEY"
```

Note the `investigation_id` from the response.

### Step 4 — Approve the HIL (via API or Dashboard)

Via API:
```powershell
$INV_ID = "<investigation_id from step 2>"
curl -X POST "http://localhost:8002/investigations/$INV_ID/approve" `
  -H "Content-Type: application/json" `
  -H "X-Agent-API-Key: $KEY" `
  -d '{"note": "Approved — euribor3m drift is real, retrain needed"}'
```

Via Dashboard: click **✅ Approve** in the HIL Inbox tab at http://localhost:8501

### Step 5 — Confirm task dispatched to worker

```powershell
# Right after approval — queue depth should be 1
curl http://localhost:8002/queue/depth -H "X-Agent-API-Key: $KEY"
# {"main_queue": 1, "dlq": 0}

# Watch worker logs
docker-compose logs -f worker
```

Expected worker output:
```
task_attempt task_type=RETRAIN_URGENT attempt=1/5 investigation=...
retrain_started ...
retrain_complete model=BankMarketingXGB version=4
retrain_hil_requested investigation=...
```

### Step 6 — Approve the PROMOTE_TO_PRODUCTION HIL

After retraining completes, a second HIL appears for production promotion.

```powershell
curl http://localhost:8002/approvals -H "X-Agent-API-Key: $KEY"
# Shows proposed_action: "PROMOTE_TO_PRODUCTION"

curl -X POST "http://localhost:8002/investigations/$INV_ID/approve" `
  -H "Content-Type: application/json" `
  -H "X-Agent-API-Key: $KEY" `
  -d '{"note": "Model metrics pass gate — promoting to production"}'
```

### Step 7 — Verify champion updated

```powershell
curl http://localhost:8001/registry
# "champion": {"version": "4", "auc": ...}
```

Dashboard Registry tab shows the new champion version.

### Step 8 — Verify investigation complete

```powershell
curl "http://localhost:8002/investigations/$INV_ID" `
  -H "X-Agent-API-Key: $KEY"
# "status": "completed"
# "comms_message": "..." (LLM-generated explanation)
```

---

## Quick Smoke Tests (Individual Components)

```powershell
$KEY = (Get-Content .env | Select-String "^AGENT_API_KEY=").ToString().Split("=",2)[1].Trim()

# MLflow registry has a champion model
curl http://localhost:8001/registry | python -m json.tool

# Agent is healthy and DB-connected
curl http://localhost:8002/investigations -H "X-Agent-API-Key: $KEY"

# Redis queue is empty
curl http://localhost:8002/queue/depth -H "X-Agent-API-Key: $KEY"

# Replay test set (non-destructive, returns metrics)
curl -X POST http://localhost:8001/replay-test

# Rollback to previous version (only works if 2+ versions exist)
curl -X POST http://localhost:8001/registry/promote `
  -H "Content-Type: application/json" `
  -d '{"model_name":"BankMarketingXGB","candidate_version":"previous","approved_by":"test","investigation_id":"00000000-0000-0000-0000-000000000000","reason":"test rollback"}'
```

---

## Crash Recovery Demo

```bash
# Kill agent mid-investigation
docker-compose stop agent

# Restart it
docker-compose start agent

# Agent resumes from last Postgres checkpoint automatically
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Trainer exits non-zero | MLflow not ready yet | Increase `start_period` in mlflow healthcheck |
| Platform stuck on startup | Trainer didn't complete | Check `docker-compose logs trainer` |
| Agent can't reach platform | Platform not healthy | Check `docker-compose logs platform` |
| HIL request not appearing | Agent not connected to Dashboard | Refresh Dashboard, check `docker-compose logs agent` |
| Queue stuck | Redis auth failed | Verify `REDIS_PASSWORD` in `.env` |
| MLflow shows no models | Trainer skipped (model exists) | Normal on restart — model already in registry |

---

## Useful Commands

```bash
# View all logs
docker-compose logs -f

# View single service
docker-compose logs -f agent

# Restart one service
docker-compose restart agent

# Full reset (destroys all data)
docker-compose down -v && docker-compose up --build

# Check queue depth
curl http://localhost:8002/queue/status

# Check drift report
curl http://localhost:8001/drift/report
```

---

## Submission Checklist

- [ ] `docker-compose up` works from clean clone
- [ ] `.env.example` exists with placeholder values
- [ ] Tag `v0.1.0-week5` pushed to GitHub
- [ ] Drift demo runs end-to-end
- [ ] Agent survives crash and resumes from checkpoint
- [ ] CI passes (GitHub Actions green)
- [ ] Both partners can explain every line of code

## Submission Message Format

```
Project 5 - [Name 1] | [Name 2]

Repo: https://github.com/<username>/drift-triage-co-pilot
Tag: v0.1.0-week5
Dataset: UCI Bank Marketing (bank-additional-full.csv)
Model: bank-classifier v1 (Test AUC: X.XX | Test F1: X.XX)
Operating threshold: X.XX (recall >= 0.75)
LLM: OpenAI GPT-4o-mini + Groq Llama fallback
     — cost-effective reliability with free redundancy
```
