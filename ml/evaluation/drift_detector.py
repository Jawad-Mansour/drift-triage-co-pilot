"""
Periodic drift detection script.
Should be run as a cron job or triggered by the platform API.
"""

import os
import sys
import json
import uuid
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import mlflow
from mlflow.tracking import MlflowClient

# Add parent dir to path to import psi_chi2
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.psi_chi2 import compute_psi_from_continuous, compute_chi2_pvalue

# -------------------------------
# Configuration (read from env)
# -------------------------------
DRIFT_WINDOW = int(os.getenv("DRIFT_WINDOW", "1000"))  # number of recent predictions to analyze
PSI_WARNING = float(os.getenv("PSI_WARNING", "0.1"))
PSI_CRITICAL = float(os.getenv("PSI_CRITICAL", "0.2"))
CHI2_ALPHA = float(os.getenv("CHI2_ALPHA", "0.05"))
AGENT_WEBHOOK_URL = os.getenv("AGENT_WEBHOOK_URL", "http://localhost:8002/webhook/drift")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///platform.db")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
engine = create_engine(DATABASE_URL)

def get_production_model_info(model_name="BankMarketingXGB"):
    """Return (version, run_id, baseline_stats) for production model."""
    client = MlflowClient()
    latest = client.get_latest_versions(model_name, stages=["Production"])
    if not latest:
        raise ValueError(f"No production model found for {model_name}")
    mv = latest[0]
    # Download baseline_stats.json from artifact
    local_path = client.download_artifacts(mv.run_id, "drift/baseline_stats.json")
    with open(local_path, "r") as f:
        baseline = json.load(f)
    return mv.version, mv.run_id, baseline

def fetch_recent_predictions(limit=DRIFT_WINDOW):
    """Fetch recent predictions from platform database."""
    query = text("""
        SELECT input_features, predicted_probability, timestamp
        FROM predictions_log
        ORDER BY timestamp DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()
    if len(rows) < 100:
        return None
    # Convert to DataFrame
    records = []
    for row in rows:
        feat = row[0]
        # Ensure previously_contacted is present (if not, compute from pdays)
        if "previously_contacted" not in feat and "pdays" in feat:
            feat["previously_contacted"] = 1 if feat["pdays"] != 999 else 0
        feat["predicted_probability"] = row[1]
        feat["timestamp"] = row[2]
        records.append(feat)
    return pd.DataFrame(records)

def compute_drift_report(live_df, baseline_stats):
    """Return dict with overall severity and per-feature drift metrics."""
    numeric_features = [k for k, v in baseline_stats.items() if "percentiles" in v]
    categorical_features = [k for k, v in baseline_stats.items() if "percentiles" not in k and k != "output"]

    severity_levels = []
    drift_features = []

    # Numeric: PSI
    for col in numeric_features:
        expected_vals = np.random.normal(
            baseline_stats[col]["mean"],
            baseline_stats[col]["std"],
            1000
        )  # approximate baseline distribution
        actual_vals = live_df[col].dropna()
        if len(actual_vals) < 30:
            continue
        psi = compute_psi_from_continuous(pd.Series(expected_vals), actual_vals, bins=10)
        if psi >= PSI_CRITICAL:
            sev = "CRITICAL"
        elif psi >= PSI_WARNING:
            sev = "WARNING"
        else:
            sev = "OK"
        severity_levels.append(sev)
        if sev != "OK":
            drift_features.append({"name": col, "psi": psi, "severity": sev})

    # Categorical: chi-squared
    for col in categorical_features:
        expected_counts = baseline_stats[col]
        actual_counts = live_df[col].value_counts().to_dict()
        p_val = compute_chi2_pvalue(expected_counts, actual_counts)
        if p_val < CHI2_ALPHA:
            sev = "CRITICAL"
        elif p_val < 0.1:
            sev = "WARNING"
        else:
            sev = "OK"
        severity_levels.append(sev)
        if sev != "OK":
            drift_features.append({"name": col, "p_value": p_val, "severity": sev})

    # Output drift: compare predicted probability distribution (optional)
    # For simplicity, we use KS test or PSI on output probabilities
    # (Leave as bonus; project requires output-distribution drift)
    expected_output_probs = baseline_stats.get("output", {}).get("predicted_probability_mean")
    if expected_output_probs is not None and "predicted_probability" in live_df.columns:
        # Use PSI on binned probabilities
        proba_psi = compute_psi_from_continuous(
            pd.Series([expected_output_probs] * 1000),  # dummy
            live_df["predicted_probability"],
            bins=5
        )
        if proba_psi >= PSI_CRITICAL:
            sev = "CRITICAL"
            severity_levels.append(sev)
            drift_features.append({"name": "output_probability", "psi": proba_psi, "severity": sev})

    if "CRITICAL" in severity_levels:
        overall = "CRITICAL"
    elif "WARNING" in severity_levels:
        overall = "WARNING"
    else:
        overall = "OK"

    return {
        "severity": overall,
        "features": drift_features,
        "timestamp": datetime.utcnow().isoformat()
    }

def send_webhook(drift_report, model_version, model_name="BankMarketingXGB"):
    """Send HTTP POST to agent's webhook endpoint."""
    payload = {
        "event_id": str(uuid.uuid4()),
        "model_name": model_name,
        "model_version": model_version,
        "severity": drift_report["severity"],
        "drift_features": drift_report["features"],
        "timestamp": drift_report["timestamp"],
        "window_size": DRIFT_WINDOW
    }
    try:
        resp = requests.post(AGENT_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        print(f"Webhook sent successfully. Agent responded {resp.status_code}")
    except Exception as e:
        print(f"Failed to send webhook: {e}")

def main():
    print("Drift detector started")
    # 1. Get production model info
    try:
        model_version, run_id, baseline_stats = get_production_model_info()
        print(f"Production model version: {model_version}")
    except Exception as e:
        print(f"Error loading production model: {e}")
        return

    # 2. Fetch recent predictions
    live_df = fetch_recent_predictions()
    if live_df is None or len(live_df) < 100:
        print(f"Not enough predictions (got {len(live_df) if live_df is not None else 0})")
        return

    # 3. Compute drift
    drift_report = compute_drift_report(live_df, baseline_stats)
    print(f"Drift severity: {drift_report['severity']}")
    print(f"Drifting features: {[f['name'] for f in drift_report['features']]}")

    # 4. If not OK, send webhook
    if drift_report["severity"] != "OK":
        send_webhook(drift_report, model_version)
    else:
        print("No significant drift detected.")

if __name__ == "__main__":
    main()