# API Contract — Drift Triage Co-Pilot

**Rule:** No endpoint exists outside this document without a decision update. Schema changes to `/webhook` or `/promote` are breaking changes — increment `schema_version`.

---

## Platform Service — port 8001

| Method | Path | Caller | Purpose |
|--------|------|--------|---------|
| POST | `/predict` | Demo script / external | Serve prediction, log to `predictions_log` |
| POST | `/promote` | Agent (after HIL approval) | Promote model version to Production |
| GET | `/drift/report` | Agent (on startup) + Dashboard | Latest drift report with per-feature severities |
| GET | `/models` | Dashboard | All MLflow registry versions + aliases |
| GET | `/health` | Docker healthcheck | Returns 200 when platform is ready |

---

## Agent Service — port 8002

| Method | Path | Caller | Purpose |
|--------|------|--------|---------|
| POST | `/webhook` | Platform | Receive drift alert, open investigation |
| GET | `/investigations` | Dashboard | List all investigations (open + closed) |
| GET | `/investigations/{id}` | Dashboard | Single investigation detail + trajectory |
| POST | `/investigations/{id}/approve` | Dashboard (human click) | Approve pending HIL request |
| POST | `/investigations/{id}/reject` | Dashboard (human click) | Reject pending HIL request |
| GET | `/queue/status` | Dashboard | Queue depth + DLQ count |
| GET | `/health` | Docker healthcheck | Returns 200 when agent is ready |

---

## Webhook Payload — Platform → Agent

`POST /webhook` — schema_version: "1.0"

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

**HTTP response from agent:** `202 Accepted` (queued for processing)

---

## Promote Payload — Agent → Platform

`POST /promote` — schema_version: "1.0"

**Request:**
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

**Headers:** `X-Agent-Key: <shared-secret>`

**Response:**
```json
{
  "schema_version": "1.0",
  "status": "promoted",
  "model_version": "v2",
  "promoted_at": "2026-05-06T14:35:30Z"
}
```

---

## Schema Versioning Rules

- Current version: `1.0`
- Field addition (backward compatible): no version bump required
- Field removal or type change: **breaking** — bump to `1.1`, both sides must support before deploy
- Both services validate `schema_version` on receipt and reject unknown versions with `422`
