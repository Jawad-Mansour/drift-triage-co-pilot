import mlflow
from fastapi import APIRouter
from mlflow.tracking import MlflowClient

from backend.platform.settings import get_settings

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("")
async def list_registry():
    s = get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    try:
        mv = client.get_model_version_by_alias(s.model_name, "champion")
        run = client.get_run(mv.run_id)
        champion = {"version": mv.version, "auc": run.data.metrics.get("test_auc")}
    except Exception:
        champion = None

    versions = client.search_model_versions(f"name='{s.model_name}'")
    return {
        "model_name": s.model_name,
        "champion": champion,
        "versions": [{"version": v.version, "run_id": v.run_id, "status": v.status} for v in versions],
    }
