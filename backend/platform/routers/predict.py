from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any
import pandas as pd
import mlflow
from mlflow.tracking import MlflowClient
from sqlalchemy.ext.asyncio import AsyncSession
import datetime
import uuid

from backend.platform.db.session import get_session
from backend.platform.db.models import PredictionLog  # we'll create this

router = APIRouter(prefix="/predict", tags=["prediction"])

# Model cache (load once at startup)
_model = None
_model_version = None
_threshold = None

def load_production_model():
    global _model, _model_version, _threshold
    client = MlflowClient()
    # Get latest production version
    latest = client.get_latest_versions("BankMarketingXGB", stages=["Production"])
    if not latest:
        raise RuntimeError("No production model found")
    mv = latest[0]
    _model_version = mv.version
    model_uri = f"models:/BankMarketingXGB/{_model_version}"
    _model = mlflow.pyfunc.load_model(model_uri)
    # Load threshold from model card (stored as artifact)
    # For simplicity, assume threshold is stored in run's params
    run = client.get_run(mv.run_id)
    _threshold = float(run.data.params.get("threshold", 0.5))
    print(f"Loaded model version {_model_version} with threshold {_threshold}")

# Startup event (in main.py)
# We'll call this when app starts

class PredictionRequest(BaseModel):
    age: int
    job: str
    marital: str
    education: str
    default: str
    housing: str
    loan: str
    contact: str
    month: str
    day_of_week: str
    campaign: int
    pdays: int
    previous: int
    poutcome: str
    emp_var_rate: float = Field(..., alias="emp.var.rate")
    cons_price_idx: float = Field(..., alias="cons.price.idx")
    cons_conf_idx: float = Field(..., alias="cons.conf.idx")
    euribor3m: float
    nr_employed: float

    class Config:
        populate_by_name = True
        extra = "forbid"

    def to_dataframe(self):
        data = self.dict(by_alias=False)
        # Rename aliases back
        data["emp.var.rate"] = data.pop("emp_var_rate")
        data["cons.price.idx"] = data.pop("cons_price_idx")
        data["cons.conf.idx"] = data.pop("cons_conf_idx")
        # Convert pdays sentinel to previously_contacted flag
        data["previously_contacted"] = 1 if data["pdays"] != 999 else 0
        del data["pdays"]
        return pd.DataFrame([data])

@router.post("")
async def predict(
    request: PredictionRequest,
    session: AsyncSession = Depends(get_session)
):
    global _model, _model_version, _threshold
    if _model is None:
        load_production_model()
    try:
        df = request.to_dataframe()
        proba = _model.predict_proba(df)[0, 1]
        label = 1 if proba >= _threshold else 0

        # Log to Postgres
        log_entry = PredictionLog(
            id=uuid.uuid4(),
            timestamp=datetime.datetime.utcnow(),
            model_version=_model_version,
            input_features=request.dict(),
            predicted_probability=float(proba),
            predicted_label=label
        )
        session.add(log_entry)
        await session.commit()

        return {
            "prediction": label,
            "probability": proba,
            "model_version": _model_version,
            "threshold_used": _threshold
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Prediction error: {str(e)}")