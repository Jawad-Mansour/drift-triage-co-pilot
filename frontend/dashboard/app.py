"""Drift Triage Co-Pilot — Operations Dashboard."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import dotenv_values
from streamlit_autorefresh import st_autorefresh

# Read .env from project root for the API key when running locally.
# We use dotenv_values (not load_dotenv) so we don't overwrite PLATFORM_URL /
# AGENT_URL already set in the environment (Docker sets them to container names).
_dotenv = dotenv_values(Path(__file__).parents[2] / ".env")

# ── Page configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Drift Triage Co-Pilot",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Environment ────────────────────────────────────────────────────────────────
PLATFORM_URL = os.getenv("PLATFORM_URL", "http://localhost:8001")
AGENT_URL    = os.getenv("AGENT_URL",    "http://localhost:8002")
API_KEY      = os.getenv("AGENT_API_KEY") or _dotenv.get("AGENT_API_KEY", "")
POLL_MS      = int(os.getenv("AGENT_HIL_POLL_INTERVAL", "2")) * 1000

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Badges ─────────────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}
.sev-critical { background:#EF444420; color:#EF4444; border:1px solid #EF444440; }
.sev-high     { background:#F9731620; color:#F97316; border:1px solid #F9731640; }
.sev-medium   { background:#F59E0B20; color:#F59E0B; border:1px solid #F59E0B40; }
.sev-low      { background:#22C55E20; color:#22C55E; border:1px solid #22C55E40; }
.st-hil       { background:#3B82F620; color:#3B82F6; border:1px solid #3B82F640; }
.st-running   { background:#8B5CF620; color:#8B5CF6; border:1px solid #8B5CF640; }
.st-done      { background:#33415530; color:#94A3B8; border:1px solid #33415550; }
.st-failed    { background:#EF444420; color:#EF4444; border:1px solid #EF444440; }

/* ── Service status dots ─────────────────────────────────────────────────── */
.dot {
    width: 8px; height: 8px; border-radius: 50%;
    display: inline-block; margin-right: 6px; vertical-align: middle;
}
.dot-ok  { background: #22C55E; box-shadow: 0 0 5px #22C55E66; }
.dot-err { background: #EF4444; box-shadow: 0 0 5px #EF444466; }

/* ── HIL card ────────────────────────────────────────────────────────────── */
.hil-card {
    background: #1E293B;
    border: 1px solid #334155;
    border-left: 4px solid #3B82F6;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 8px;
}
.hil-action  { font-size: 18px; font-weight: 700; color: #F1F5F9; margin-bottom: 6px; }
.hil-meta    { font-size: 12px; color: #64748B; font-family: monospace; margin-bottom: 10px; }
.hil-text    { font-size: 14px; color: #CBD5E1; line-height: 1.65; }

/* ── Champion card ───────────────────────────────────────────────────────── */
.champion-card {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
    border: 1px solid #3B82F640;
    border-radius: 8px;
    padding: 24px;
    margin-bottom: 8px;
}
.champ-label   {
    font-size: 11px; font-weight: 700; letter-spacing: 2px;
    text-transform: uppercase; color: #3B82F6; margin-bottom: 6px;
}
.champ-version {
    font-size: 52px; font-weight: 800; color: #F1F5F9;
    line-height: 1; margin: 6px 0 18px;
}
.stat-grid { display: flex; gap: 32px; flex-wrap: wrap; }
.stat-item { display: flex; flex-direction: column; gap: 3px; }
.stat-val  { font-size: 22px; font-weight: 700; color: #E2E8F0; }
.stat-key  { font-size: 11px; color: #64748B; text-transform: uppercase; letter-spacing: 1px; }

/* ── Queue metric boxes ──────────────────────────────────────────────────── */
.metric-box {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 28px 20px;
    text-align: center;
}
.metric-num     { font-size: 52px; font-weight: 800; color: #F1F5F9; line-height: 1; }
.metric-num-red { color: #EF4444; }
.metric-lbl     {
    font-size: 11px; color: #64748B;
    text-transform: uppercase; letter-spacing: 1px; margin-top: 6px;
}
</style>
""", unsafe_allow_html=True)

# ── Auto-refresh (non-blocking JS timer) ───────────────────────────────────────
st_autorefresh(interval=POLL_MS, key="dash_refresh")

# ── API helpers ────────────────────────────────────────────────────────────────

def _agent(path: str, method: str = "GET", json=None):
    try:
        r = requests.request(
            method, f"{AGENT_URL}{path}",
            headers={"X-Agent-API-Key": API_KEY},
            json=json, timeout=5,
        )
        r.raise_for_status()
        return r.json(), None
    except requests.Timeout:
        return None, "Request timed out"
    except requests.HTTPError as e:
        return None, f"HTTP {e.response.status_code}: {e.response.text[:120]}"
    except Exception as e:
        return None, str(e)


def _platform(path: str):
    try:
        r = requests.get(f"{PLATFORM_URL}{path}", timeout=5)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _health(url: str) -> bool:
    try:
        return requests.get(f"{url}/health", timeout=3).status_code == 200
    except Exception:
        return False


# ── Normalisation helpers ──────────────────────────────────────────────────────
# The triage node uses short codes: "CRIT" → display as "CRITICAL", "MED" → "MEDIUM".
# DB status enum uses lowercase values: "awaiting_hil", "running", "completed", etc.

_SEV_NORM: dict[str, str] = {"CRIT": "CRITICAL", "MED": "MEDIUM"}


def _norm_sev(s: str) -> str:
    """Normalise triage severity code to display label."""
    return _SEV_NORM.get(s.upper(), s.upper())


# ── Badge helpers ──────────────────────────────────────────────────────────────

_SEV_CLASS: dict[str, str] = {
    "CRITICAL": "sev-critical",
    "HIGH":     "sev-high",
    "MEDIUM":   "sev-medium",
    "LOW":      "sev-low",
}

# Status values returned by the API are lowercase StrEnum values.
_ST_CLASS: dict[str, str] = {
    "awaiting_hil": "st-hil",
    "running":       "st-running",
    "open":          "st-running",
    "pending":       "st-running",
    "completed":     "st-done",
    "closed":        "st-done",
    "failed":        "st-failed",
}


def sev_badge(raw: str) -> str:
    norm = _norm_sev(raw)
    cls  = _SEV_CLASS.get(norm, "st-done")
    return f'<span class="badge {cls}">{norm}</span>'


def status_badge(raw: str) -> str:
    cls   = _ST_CLASS.get(raw.lower(), "st-done")
    label = raw.replace("_", " ").upper()
    return f'<span class="badge {cls}">{label}</span>'


def _expiry(ts: str) -> tuple[str, str]:
    """Return (label, streamlit_level: error|warning|info)."""
    try:
        dt  = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        rem = (dt - datetime.now(timezone.utc)).total_seconds()
        if rem <= 0:
            return "Expired", "error"
        m, s = int(rem // 60), int(rem % 60)
        level = "error" if rem < 90 else "warning" if rem < 300 else "info"
        return f"{m}m {s:02d}s remaining", level
    except Exception:
        return ts, "info"


# ── Data fetch (once per render) ───────────────────────────────────────────────
platform_ok = _health(PLATFORM_URL)
agent_ok    = _health(AGENT_URL)

approvals, _e_app = _agent("/approvals")
invs,      _e_inv = _agent("/investigations")
queue,     _e_q   = _agent("/queue/depth")
registry,  _e_reg = _platform("/registry")

pending_n = len(approvals) if approvals else 0

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎯 Drift Triage\n### Co-Pilot")
    st.divider()

    # Live service status
    st.markdown("**System Status**")
    pc = "dot-ok" if platform_ok else "dot-err"
    ac = "dot-ok" if agent_ok    else "dot-err"
    pt = "Platform" if platform_ok else "Platform (offline)"
    at = "Agent"    if agent_ok    else "Agent (offline)"
    st.markdown(
        f'<span class="dot {pc}"></span>{pt}&nbsp;&nbsp;&nbsp;'
        f'<span class="dot {ac}"></span>{at}',
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown("**About**")
    st.caption(
        "Monitors a production XGBoost model for data drift. "
        "When PSI or Chi² signals exceed thresholds, a LangGraph supervisor "
        "triages severity, decides on a remediation action, and pauses for "
        "human approval before any production change."
    )

    st.divider()

    st.markdown("**Stack**")
    st.markdown(
        "XGBoost + Sigmoid calibration  \n"
        "MLflow 2.14 · Postgres backend  \n"
        "PSI · Chi² · Output-PSI drift  \n"
        "LangGraph HIL supervisor  \n"
        "Redis BLPOP queue + DLQ"
    )

    st.divider()

    st.markdown("**Links**")
    mlflow_port = os.getenv("MLFLOW_PORT", "5000")
    st.markdown(
        f"[📊 MLflow Registry](http://localhost:{mlflow_port})  \n"
        f"[🔌 Platform API]({PLATFORM_URL}/docs)  \n"
        f"[🤖 Agent API]({AGENT_URL}/docs)"
    )

    st.divider()

    if st.button("↺  Refresh now", use_container_width=True):
        st.rerun()
    st.caption(f"Auto-refreshing every {POLL_MS // 1000}s")
    st.caption(f"Updated at {datetime.now().strftime('%H:%M:%S')}")


# ── Tab bar ────────────────────────────────────────────────────────────────────
hil_label = f"🔔 HIL Inbox  ·  {pending_n} pending" if pending_n else "🔔 HIL Inbox"
tab1, tab2, tab3, tab4 = st.tabs(
    [hil_label, "🔍 Investigations", "📦 Registry", "📊 Queue"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — HIL Inbox
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("## Human-in-the-Loop Inbox")
    st.caption(
        "Pending approvals expire after 10 minutes. "
        "Approve to let the agent proceed, or reject to close the investigation."
    )

    if _e_app:
        st.error(f"Agent unreachable: {_e_app}")
    elif not approvals:
        st.success("✅  No pending approvals — system running autonomously.")
    else:
        st.warning(
            f"⚠️  **{pending_n} pending approval{'s' if pending_n > 1 else ''}** "
            "waiting for your decision."
        )
        st.markdown("---")

        for item in approvals:
            inv_id    = item["investigation_id"]
            action    = item["proposed_action"].replace("_", " ")
            rationale = item.get("rationale", "—")
            exp_label, exp_level = _expiry(item.get("expires_at", ""))

            st.markdown(f"""
<div class="hil-card">
  <div class="hil-action">🔐 {action}</div>
  <div class="hil-meta">investigation · {inv_id}</div>
  <div class="hil-text">{rationale}</div>
</div>""", unsafe_allow_html=True)

            if exp_level == "error":
                st.error(f"⏱  {exp_label}")
            elif exp_level == "warning":
                st.warning(f"⏱  {exp_label}")
            else:
                st.info(f"⏱  {exp_label}")

            note = st.text_area(
                "Note",
                key=f"note_{item['id']}",
                height=68,
                placeholder="Optional context for the audit trail…",
                label_visibility="collapsed",
            )

            col_a, col_b, *_ = st.columns([1, 1, 4])
            with col_a:
                if st.button(
                    "✅  Approve",
                    key=f"app_{item['id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    _, err = _agent(
                        f"/investigations/{inv_id}/approve",
                        "POST",
                        {"note": note or None},
                    )
                    if err:
                        st.error(f"Error: {err}")
                    else:
                        st.success("Approved — investigation resumed.")
                        time.sleep(0.8)
                        st.rerun()

            with col_b:
                if st.button(
                    "❌  Reject",
                    key=f"rej_{item['id']}",
                    use_container_width=True,
                ):
                    _, err = _agent(
                        f"/investigations/{inv_id}/reject",
                        "POST",
                        {"note": note or None},
                    )
                    if err:
                        st.error(f"Error: {err}")
                    else:
                        st.warning("Rejected — investigation closed.")
                        time.sleep(0.8)
                        st.rerun()

            st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Investigations
# Status values from the API are lowercase StrEnum strings:
#   awaiting_hil | running | completed | failed | pending
# Severity codes from the triage node:
#   LOW | MED | HIGH | CRIT  (normalised to MEDIUM / CRITICAL for display)
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("## Investigations")

    if _e_inv:
        st.error(f"Agent unreachable: {_e_inv}")
    elif not invs:
        st.info("No investigations yet. Drift events will appear here automatically.")
    else:
        total     = len(invs)
        n_hil     = sum(1 for i in invs if i["status"] == "awaiting_hil")
        n_running = sum(1 for i in invs if i["status"] in ("running", "open", "pending"))
        n_done    = sum(1 for i in invs if i["status"] == "completed")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total", total)
        m2.metric("Running", n_running)
        m3.metric("Awaiting HIL", n_hil)
        m4.metric("Completed", n_done)

        st.divider()

        # Filter uses lowercase values that match the API
        FILTER_OPTIONS = {
            "All":         None,
            "Awaiting HIL": "awaiting_hil",
            "Running":      "running",
            "Completed":    "completed",
            "Failed":       "failed",
        }
        f_label  = st.selectbox("Filter by status", list(FILTER_OPTIONS.keys()))
        f_status = FILTER_OPTIONS[f_label]
        shown    = invs if f_status is None else [i for i in invs if i["status"] == f_status]

        # ── Summary table ──────────────────────────────────────────────────────
        SEV_ICON: dict[str, str] = {
            "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢",
        }
        ST_ICON: dict[str, str] = {
            "awaiting_hil": "🔵",
            "running": "🟣", "open": "🟣", "pending": "🟣",
            "completed": "✅", "failed": "❌", "closed": "⚫",
        }

        rows = [
            {
                "Severity": (
                    SEV_ICON.get(_norm_sev(i.get("severity", "")), "⚪")
                    + "  " + _norm_sev(i.get("severity", "—"))
                ),
                "Feature":  i.get("feature_name", "—"),
                "PSI":      f"{i['psi_score']:.4f}" if i.get("psi_score") is not None else "—",
                "Status":   (
                    ST_ICON.get(i.get("status", ""), "⚪")
                    + "  " + i.get("status", "—").replace("_", " ").upper()
                ),
                "Action":   i.get("proposed_action") or "—",
                "Created":  i["created_at"][:16].replace("T", " "),
            }
            for i in shown
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── Detail panel ───────────────────────────────────────────────────────
        st.divider()
        st.markdown("**Investigation Detail**")

        inv_labels = {
            f"{i['feature_name']}  ·  {i['status'].replace('_', ' ').upper()}  ·  {i['id'][:8]}…": i
            for i in shown
        }
        if inv_labels:
            sel_key = st.selectbox(
                "Select investigation",
                list(inv_labels.keys()),
                label_visibility="collapsed",
            )
            sel = inv_labels[sel_key]
            detail, d_err = _agent(f"/investigations/{sel['id']}")

            if d_err:
                st.error(f"Could not fetch detail: {d_err}")
            elif detail:
                dc1, dc2, dc3 = st.columns(3)
                dc1.markdown(
                    f"**Severity**  \n{sev_badge(sel.get('severity', '—'))}",
                    unsafe_allow_html=True,
                )
                dc2.markdown(
                    f"**Status**  \n{status_badge(sel.get('status', '—'))}",
                    unsafe_allow_html=True,
                )
                dc3.markdown(
                    f"**Action**  \n`{sel.get('proposed_action') or '—'}`",
                    unsafe_allow_html=True,
                )

                if detail.get("comms_message"):
                    st.markdown("**Agent Summary**")
                    st.info(detail["comms_message"])

                st.caption(
                    f"ID: {sel['id']}  ·  "
                    f"Thread: {sel['thread_id']}  ·  "
                    f"Updated: {sel['updated_at'][:16].replace('T', ' ')}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Model Registry
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("## Model Registry")

    if _e_reg:
        st.error(f"Platform unreachable: {_e_reg}")
    else:
        model_name = (registry or {}).get("model_name", "—")
        champion   = (registry or {}).get("champion")
        versions   = (registry or {}).get("versions", [])

        if champion:
            ver     = champion.get("version", "—")
            auc     = champion.get("auc")
            auc_str = f"{auc:.4f}" if auc else "—"
            n_ver   = len(versions)

            st.markdown(f"""
<div class="champion-card">
  <div class="champ-label">🏆 Production Champion · {model_name}</div>
  <div class="champ-version">v{ver}</div>
  <div class="stat-grid">
    <div class="stat-item">
      <span class="stat-val">{auc_str}</span>
      <span class="stat-key">Test AUC</span>
    </div>
    <div class="stat-item">
      <span class="stat-val">{n_ver}</span>
      <span class="stat-key">Total Versions</span>
    </div>
    <div class="stat-item">
      <span class="stat-val">XGBoost</span>
      <span class="stat-key">Algorithm</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.warning("No champion model registered. Run the trainer to bootstrap.")

        st.markdown("---")
        st.markdown("**All Registered Versions**")

        if versions:
            df_v = pd.DataFrame([
                {
                    "Version": f"v{v['version']}",
                    "Status":  v.get("status", "—"),
                    "Run ID":  (v.get("run_id") or "—")[:14] + "…",
                }
                for v in sorted(versions, key=lambda x: int(x["version"]), reverse=True)
            ])
            st.dataframe(df_v, use_container_width=True, hide_index=True)
        else:
            st.caption("No versions found.")

        st.markdown("---")
        col_p, col_a = st.columns(2)
        with col_p:
            st.markdown("**Promotion Gates**")
            st.markdown("""
| Gate | Threshold |
|------|-----------|
| Test AUC | > 0.80 |
| Test Recall | ≥ 0.75 |
| Approver | Human (HIL required) |
""")
        with col_a:
            st.markdown("**Promotion Path**")
            st.markdown("""
```
Trainer  →  MLflow (champion alias)
Worker   →  MLflow Staging only
Agent    →  Production (HIL gate)
```
Production promotion **always** requires the agent supervisor and a human approval.
""")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Queue
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("## Task Queue")

    if _e_q:
        st.error(f"Agent unreachable: {_e_q}")
    else:
        main_q = (queue or {}).get("main_queue", 0)
        dlq    = (queue or {}).get("dlq", 0)

        q1, q2, _ = st.columns([1, 1, 2])
        with q1:
            st.markdown(f"""
<div class="metric-box">
  <div class="metric-num">{main_q}</div>
  <div class="metric-lbl">Tasks in Queue</div>
</div>""", unsafe_allow_html=True)
        with q2:
            dlq_border = "border-color:#EF444460;" if dlq > 0 else ""
            dlq_cls    = "metric-num-red" if dlq > 0 else ""
            st.markdown(f"""
<div class="metric-box" style="{dlq_border}">
  <div class="metric-num {dlq_cls}">{dlq}</div>
  <div class="metric-lbl">Dead Letter Queue</div>
</div>""", unsafe_allow_html=True)

        st.markdown("---")

        if dlq > 0:
            st.error(
                f"⚠️  **{dlq} task{'s' if dlq > 1 else ''} in DLQ** — "
                "failed after 5 retries. Check `docker-compose logs worker` for details."
            )
        elif main_q == 0:
            st.success("✅  Queue is empty — all tasks processed.")
        else:
            st.info(f"Worker is processing {main_q} pending task{'s' if main_q > 1 else ''}.")

        st.markdown("---")
        tl, tr = st.columns(2)
        with tl:
            st.markdown("**Retry Policy**")
            st.markdown("""
| Attempt | Delay before retry |
|---------|--------------------|
| 1st | 1 second |
| 2nd | 2 seconds |
| 3rd | 4 seconds |
| 4th | 8 seconds |
| 5th | 16 seconds |
| After 5th | → Dead Letter Queue |
""")
        with tr:
            st.markdown("**Supported Task Types**")
            st.markdown("""
| Type | Trigger |
|------|---------|
| `RETRAIN_SCHEDULED` | MEDIUM / HIGH drift |
| `RETRAIN_URGENT` | CRITICAL drift |
| `ROLLBACK` | Poor model performance |
| `REPLAY_TEST_SET` | Validation request |
| `SWITCH_TO_FALLBACK` | Emergency fallback |
""")
