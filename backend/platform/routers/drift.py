import numpy as np
import httpx
from scipy.stats import chi2_contingency
from sqlalchemy import select

from backend.platform.db.models import PredictionLog, DriftReference
from backend.platform.db.session import get_sessionmaker
from backend.platform.settings import get_settings

EPSILON = 1e-6


async def run_drift_check():
    s = get_settings()
    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            select(PredictionLog).order_by(PredictionLog.timestamp.desc()).limit(s.drift_window_size)
        )).scalars().all()
        if len(rows) < 100:
            return

        refs = {r.feature_name: r for r in (await session.execute(select(DriftReference))).scalars().all()}
        if not refs:
            return

    import pandas as pd
    import mlflow
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    mv = client.get_model_version_by_alias(s.model_name, "champion")
    run = client.get_run(mv.run_id)
    model_auc = float(run.data.metrics.get("test_auc", 0.0))

    live_df = pd.DataFrame([r.input_features for r in rows])

    for fname, ref in refs.items():
        if fname not in live_df.columns:
            continue
        vals = live_df[fname].dropna()
        if ref.feature_type == "numeric":
            psi = _psi_numeric(vals, ref.bin_edges, ref.ref_counts)
            chi2p = None
        else:
            psi, chi2p = _psi_categorical(vals, ref.ref_counts)

        if psi > s.drift_psi_threshold_high:
            await _fire_webhook(s, fname, psi, chi2p, model_auc, mv.version)


def _psi_numeric(vals, bin_edges, ref_counts):
    edges = list(bin_edges)
    edges[0] = -np.inf
    edges[-1] = np.inf
    counts, _ = np.histogram(vals, bins=edges)
    ref = np.array(ref_counts, dtype=float) + EPSILON
    act = np.array(counts, dtype=float) + EPSILON
    ref /= ref.sum(); act /= act.sum()
    return float(np.sum((act - ref) * np.log(act / ref)))


def _psi_categorical(vals, ref_counts):
    live = vals.value_counts(normalize=True).to_dict()
    cats = set(ref_counts) | set(live)
    ref = np.array([ref_counts.get(c, EPSILON) for c in cats])
    act = np.array([live.get(c, EPSILON) for c in cats])
    ref /= ref.sum(); act /= act.sum()
    psi = float(np.sum((act - ref) * np.log(act / ref)))
    tbl = np.vstack([ref, act])
    tbl = tbl[:, ~np.all(tbl == 0, axis=0)]
    p = float(chi2_contingency(tbl)[1]) if tbl.shape[1] >= 2 else 1.0
    return psi, p


async def _fire_webhook(s, feature_name, psi_score, chi2_pvalue, model_auc, model_version):
    payload = {
        "feature_name": feature_name,
        "psi_score": psi_score,
        "model_version": model_version,
        "model_auc": model_auc,
        "window_size": s.drift_window_size,
    }
    if chi2_pvalue is not None:
        payload["chi2_pvalue"] = chi2_pvalue
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                f"{s.agent_url}/webhook",
                json=payload,
                headers={"X-Agent-API-Key": s.agent_api_key.get_secret_value()},
            )
        except Exception as e:
            print(f"drift webhook failed: {e}")
