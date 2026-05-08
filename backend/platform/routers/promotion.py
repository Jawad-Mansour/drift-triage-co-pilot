import mlflow
from fastapi import APIRouter, HTTPException
from mlflow.tracking import MlflowClient
from pydantic import BaseModel

from backend.platform.settings import get_settings

router = APIRouter(prefix="/registry", tags=["promotion"])


class PromoteRequest(BaseModel):
    model_name: str
    candidate_version: str
    approved_by: str
    investigation_id: str
    reason: str


@router.post("/promote")
async def promote(req: PromoteRequest):
    s = get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()

    version = req.candidate_version
    if version == "previous":
        try:
            current = client.get_model_version_by_alias(req.model_name, "champion")
            cur_v = int(current.version)
            all_v = client.search_model_versions(f"name='{req.model_name}'")
            prev = max((v for v in all_v if int(v.version) < cur_v), key=lambda v: int(v.version), default=None)
            if not prev:
                raise HTTPException(status_code=404, detail="No previous version for rollback")
            version = prev.version
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        client.get_model_version(req.model_name, version)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    client.set_registered_model_alias(req.model_name, "champion", version)
    from backend.platform.routers.predict import load_champion_model
    load_champion_model()
    return {"status": "promoted", "version": version, "alias": "champion"}
