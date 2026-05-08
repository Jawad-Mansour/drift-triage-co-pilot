# Dataset — UCI Bank Marketing

## Overview

| Property | Value |
|----------|-------|
| Name | UCI Bank Marketing |
| File | `bank-additional-full.csv` |
| Description | Phone-call campaign records from a Portuguese retail bank |
| Rows | ~41,188 |
| Features | 20 |
| Target | Did the client subscribe to a term deposit? (yes/no → 1/0) |
| Positive rate | ~11% (imbalanced) |
| Path in repo | `data/raw/bank-additional-full.csv` |

---

## Split Strategy

| Split | Size | Rows |
|-------|------|------|
| Train | 60% | ~24,713 |
| Validation | 20% | ~8,238 |
| Test | 20% | ~8,237 |

Stratified by target, `random_state=42`.

---

## Known Traps — Critical

| Trap | Problem | Decision |
|------|---------|----------|
| `duration` feature | Recorded **after** the call ends — leaks the target. Long calls = more likely to buy. Not available at prediction time. | **Drop entirely** |
| `pdays == 999` | Sentinel value meaning "never contacted before" — not a real duration | Create `contacted_before = (pdays != 999)`, drop raw `pdays` |
| `unknown` category values | NOT missing data — means the bank genuinely doesn't know | Treat as a real category — it's informative |

---

## Features

**Numerical** — PSI monitors these for drift:

| Feature | Range | Notes |
|---------|-------|-------|
| `age` | 21–90 | Client age |
| `euribor3m` | 0.5%–5% | 3-month Euribor rate — key economic indicator |
| `cons.price.idx` | — | Consumer price index |
| `campaign` | 1–n | Number of calls this campaign |
| `previous` | 0–n | Contacts before this campaign |
| `emp.var.rate` | — | Employment variation rate |

**Categorical** — Chi² monitors these for drift:

| Feature | Values |
|---------|--------|
| `job` | admin., technician, services, retired, student, management, ... |
| `marital` | married, single, divorced |
| `education` | basic.4y, basic.6y, basic.9y, high.school, university.degree, ... |
| `contact` | telephone, cellular |
| `month` | jan–dec |
| `day_of_week` | mon–fri |

---

## Model Decisions

- **Algorithm:** XGBoost + Sigmoid calibration (`CalibratedClassifierCV`)
- **Class imbalance:** `scale_pos_weight` tuned via calibration
- **Threshold tuning:** highest threshold where `recall >= 0.75` on validation split
- **Promotion gate:** `AUC > 0.80 AND Recall >= 0.75`

---

## Drift Narrative — Friday Demo

**Story:** Economic features like `euribor3m` change with real interest rate movements. A model trained when rates were low becomes inaccurate when rates rise.

**What the demo does:**
1. Start system — everything healthy, no drift
2. Inject shifted `euribor3m` values via `scripts/demo_drift.py --inject`
3. Platform detects PSI > 0.2 → fires webhook to agent
4. Agent opens investigation → Triage says CRITICAL (economic feature)
5. Action agent decides RETRAIN_URGENT → HIL pause
6. Human clicks APPROVE in Dashboard
7. Worker retrains, promotes v2
8. Dashboard shows "Production: v2"

**Second drift:** Also shift `job` distribution (cellular → telephone) to demonstrate Chi² detection.
