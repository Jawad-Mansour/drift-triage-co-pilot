import os
import subprocess
import sys

import mlflow
from fastapi import APIRouter, HTTPException
from mlflow.tracking import MlflowClient

from pydantic import BaseModel

from backend.platform.settings import get_settings

router = APIRouter(tags=["retrain"])


class RetrainRequest(BaseModel):
    investigation_id: str | None = None
    feature_name: str | None = None


@router.post("/retrain")
async def retrain(req: RetrainRequest = RetrainRequest()):
    s = get_settings()
    train_script = os.getenv("TRAIN_SCRIPT", "/app/ml/training/train.py")

    env = os.environ.copy()
    env["PROMOTE_ON_TRAIN"] = "false"
    env["MLFLOW_TRACKING_URI"] = s.mlflow_tracking_uri

    result = subprocess.run(
        [sys.executable, train_script],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:])

    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{s.model_name}'")
    if not versions:
        raise HTTPException(status_code=500, detail="No model versions found after retrain")
    latest = max(versions, key=lambda v: int(v.version))

    return {"model_name": s.model_name, "model_version": latest.version}
