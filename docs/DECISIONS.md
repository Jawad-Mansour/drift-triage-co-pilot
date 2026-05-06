# Design Decisions — Drift Triage Co-Pilot

All 64 decisions are complete. Source of truth: `deepseek-brainstorm.txt`.

---

## Complete Decision Table

| # | Decision | Choice | Status |
|---|----------|--------|--------|
| 1 | ML Model | LightGBM (`class_weight=balanced`, `random_state=42`) | ✅ |
| 2 | pdays==999 | Boolean flag `contacted_before`, drop raw pdays | ✅ |
| 3 | Drift window size | 500 predictions (sliding window) | ✅ |
| 4 | Drift frequency | Recalculate every 50 new predictions | ✅ |
| 5 | Predictions log | Postgres table `predictions_log` | ✅ |
| 6 | PSI thresholds | <0.1 LOW · 0.1–0.2 MED · 0.2–0.25 HIGH · ≥0.25 CRIT | ✅ |
| 7 | Chi² thresholds | p>0.05 LOW · 0.01–0.05 MED · ≤0.01 HIGH | ✅ |
| 8 | Registry persistence | MLflow own service (:5000), Postgres backend + volume | ✅ |
| 9 | Platform→Agent comms | Webhooks (not polling) | ✅ |
| 10 | Polling interval | N/A — webhooks chosen | ✅ |
| 11 | Webhook payload | JSON with `schema_version` field | ✅ |
| 12 | HTTP status codes | Standard REST (200, 202, 400, 404, 409, 422, 500) | ✅ |
| 13 | Triage agent | Decision tree — NO LLM | ✅ |
| 14 | Severity rules | PSI thresholds + economic feature escalation | ✅ |
| 15 | Action agent | Rules for 90% of cases, LLM for edge cases | ✅ |
| 16 | Available actions | 7 actions (RETRAIN, RETRAIN_URGENT, ROLLBACK, REPLAY, MONITOR, ESCALATE, SWITCH_FALLBACK) | ✅ |
| 17 | Action trigger logic | Priority-based rules (7 ordered rules) | ✅ |
| 18 | Comms agent | Pure LLM — always required | ✅ |
| 19 | Prompts storage | Separate `.txt` files in `agent/prompts/` | ✅ |
| 20 | Checkpoint content | Complete investigation state | ✅ |
| 21 | Checkpoint frequency | 7 milestones + before every risky operation | ✅ |
| 22 | Missing model URI | Ask human via HIL — no automatic fallback | ✅ |
| 23 | Registry sync detection | Validate on resume, trust MLflow as source of truth | ✅ |
| 24 | HIL required actions | RETRAIN (urgent), ROLLBACK, SWITCH_TO_FALLBACK | ✅ |
| 25 | HIL approval validity | 10 minutes — staleness validated before dispatch | ✅ |
| 26 | New drift during HIL | Open parallel investigation + warning, no auto-cancel | ✅ |
| 27 | Dashboard HIL surface | WebSocket primary + polling fallback | ✅ |
| 28 | HIL comments | Optional free-text with audit trail | ✅ |
| 29 | Idempotency key | `hash(action + feature + hour + severity)` | ✅ |
| 30 | Idempotency TTL | 24h for retrain · 1h for all others | ✅ |
| 31 | Retry strategy | 5 retries, exponential backoff: 1, 2, 4, 8, 16 seconds | ✅ |
| 32 | DLQ handling | No auto-retry — human reviews via Dashboard | ✅ |
| 33 | Task completion notification | Status updated in Postgres `queue_tasks` table | ✅ |
| 34 | Promotion criteria | AUC > 0.80 AND Recall ≥ 0.75 at tuned threshold | ✅ |
| 35 | Direct promotion bypass | Agent + emergency key (secret header) | ✅ |
| 36 | Emergency mechanism | `X-Emergency-Key` header — JWT upgrade as stretch goal | ✅ |
| 37 | Audit logging | Minimal (time-permitting: full) | ✅ |
| 38 | Dashboard data source | Direct Postgres read-only — API if time permits | ✅ |
| 39 | Dashboard refresh rate | 2 seconds | ✅ |
| 40 | Dashboard sections | All sections shown (history collapsed by default) | ✅ |
| 41 | LLM mock | Keyword-based dictionary (`MockLLM` class) | ✅ |
| 42 | Snapshot fixtures | Full agent trajectory JSON | ✅ |
| 43 | Fidelity test input | Single fixed input, 1e-12 tolerance, versioned | ✅ |
| 44 | CI platform | GitHub Actions | ✅ |
| 45–46 | LLM provider | GPT-4o-mini primary + Groq Llama fallback | ✅ |
| 47 | LLM reason for submission | One-liner: cost-effective reliability with free redundancy | ✅ |
| 48 | LLM failure handling | tenacity retry → Groq fallback → template text | ✅ |
| 49 | Docker services | 8 services (postgres, redis, mlflow, trainer, platform, agent, worker, dashboard) | ✅ |
| 50 | Environment variables | See `.env.example` | ✅ |
| 51 | Service discovery | Docker Compose service names as hostnames | ✅ |
| 52 | Volumes | `postgres_data`, `redis_data`, `mlflow_artifacts` | ✅ |
| 53 | Diagram tool | Mermaid (primary) + Draw.io optional | ✅ |
| 54 | RUNBOOK detail | Full sections with exact commands | ✅ |
| 55 | Output-distribution drift | PSI on 10 bins of `predict_proba` scores | ✅ |
| 56 | Worker promotion rule | Worker → Staging only. Production = agent + HIL always | ✅ |
| 57 | Agent→Platform promote contract | `POST /promote` JSON schema v1.0 + `X-Agent-Key` header | ✅ |
| 58 | Bootstrap training flow | Dedicated `trainer` service — runs once, exits 0 | ✅ |
| 59 | Reference distribution storage | Postgres `drift_reference` table, seeded by trainer | ✅ |
| 60 | API endpoint inventory | 5 platform + 7 agent endpoints — see `API_CONTRACT.md` | ✅ |
| 61 | Worker design | Custom async BLPOP loop + Redis ZADD delayed queue | ✅ |
| 62 | DB init | SQLAlchemy `create_all` per service — no Alembic | ✅ |
| 63 | Startup sequence | 8-service chain with `depends_on` + healthchecks | ✅ |
| 64 | Demo simulation | `scripts/demo_drift.py --reset / --inject`, 6-step script | ✅ |

---

## Key Decision Details

### Drift Thresholds (Decisions 6, 7, 55)

| Metric | LOW | MEDIUM | HIGH | CRITICAL |
|--------|-----|--------|------|----------|
| PSI (numeric) | < 0.1 | 0.1 – 0.2 | 0.2 – 0.25 | ≥ 0.25 |
| Chi² p-value (categorical) | > 0.05 | 0.01 – 0.05 | ≤ 0.01 | — |
| Output PSI (predict_proba) | < 0.1 | 0.1 – 0.2 | 0.2 – 0.25 | ≥ 0.25 |

**Economic feature escalation:** `euribor3m` or `cons.price.idx` at HIGH automatically escalates to CRITICAL.

### Agent Topology (Decisions 13–18)

```
Supervisor
├── Triage    → Decision tree (NO LLM). Inputs: PSI/Chi² numbers. Output: severity.
├── Action    → Rules for 90%. LLM only for: borderline scores, multiple simultaneous drifts,
│               recent retrain within 24h, conflicting signals.
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
TTL = 1h for all other tasks
```

If key exists in Redis → skip. Same drift in same hour = same key = one task only.

### The 5 "Think About" Problems — Solved

| Problem | Solution |
|---------|----------|
| Checkpoint & registry out of sync | On resume: validate checkpoint model URI against MLflow. Trust MLflow. |
| Missing model URI in checkpoint | Pause via HIL, ask human. No automatic fallback (safety). |
| Duplicate retrain requests | Idempotency key with 24h TTL. |
| Stale HIL approval | 10-minute expiry. Validate staleness before dispatch. |
| Production promotion bypass | Emergency key header. Normal path always requires agent + HIL. |
