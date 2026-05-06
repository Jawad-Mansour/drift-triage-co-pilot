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

```bash
curl -X POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  -d '{
    "age": 35,
    "job": "admin.",
    "marital": "married",
    "education": "university.degree",
    "contacted_before": false,
    "euribor3m": 4.857,
    "cons_price_idx": 93.994,
    "campaign": 1,
    "previous": 0,
    "emp_var_rate": -1.8
  }'
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
