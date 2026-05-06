# src/platform/routers/promotion.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import mlflow
from mlflow.tracking import MlflowClient

router = APIRouter(prefix="/registry", tags=["promotion"])

# MLflow setup – will be overridden by env in docker
mlflow.set_tracking_uri("file:./mlruns")
client = MlflowClient()

class PromoteRequest(BaseModel):
    model_name: str
    candidate_version: str
    approved_by: str
    investigation_id: str
    reason: str

def promotion_checklist(model_name: str, version: str) -> bool:
    """Day‑4 promotion checklist."""
    try:
        mv = client.get_model_version(model_name, version)
    except:
        return False
    if mv.stage != "Staging":
        return False
    # Check artifact triple
    run_id = mv.run_id
    artifacts = client.list_artifacts(run_id)
    artifact_paths = [a.path for a in artifacts]
    if "model" not in artifact_paths:
        return False
    if "model_card/model_card.json" not in artifact_paths:
        return False
    # Signature presence check (inside model metadata)
    model_uri = f"models:/{model_name}/{version}"
    try:
        loaded = mlflow.pyfunc.load_model(model_uri)
        if not loaded.metadata or not loaded.metadata.get("signature"):
            return False
    except:
        return False
    return True

@router.post("/promote")
async def promote(request: PromoteRequest):
    if not promotion_checklist(request.model_name, request.candidate_version):
        raise HTTPException(status_code=400, detail="Promotion checklist failed")
    client.transition_model_version_stage(
        name=request.model_name,
        version=request.candidate_version,
        stage="Production"
    )
    return {"status": "promoted", "version": request.candidate_version}