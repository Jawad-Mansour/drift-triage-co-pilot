import requests
import uuid
from datetime import datetime

def trigger_agent_webhook(agent_url, model_name, model_version, severity, drift_features):
    payload = {
        "event_id": str(uuid.uuid4()),
        "model_name": model_name,
        "model_version": model_version,
        "severity": severity,
        "drift_features": drift_features,
        "timestamp": datetime.utcnow().isoformat(),
        "window_size": 1000  # or configurable
    }
    response = requests.post(f"{agent_url}/webhook/drift", json=payload, timeout=5)
    response.raise_for_status()
    return response.json()