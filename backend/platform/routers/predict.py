import asyncio
import datetime
import uuid

import mlflow
import mlflow.sklearn
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.models import PredictionLog
from backend.platform.db.session import get_session
from backend.platform.settings import get_settings

router = APIRouter(tags=["prediction"])

_model = None
_model_version = None
_threshold = 0.5
_prediction_count = 0


def load_champion_model():
    global _model, _model_version, _threshold
    s = get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    mv = client.get_model_version_by_alias(s.model_name, "champion")
    _model_version = mv.version
    _model = mlflow.sklearn.load_model(f"models:/{s.model_name}@champion")
    run = client.get_run(mv.run_id)
    _threshold = float(run.data.params.get("tuned_threshold", 0.5))


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

    def to_dataframe(self):
        d = self.model_dump(by_alias=False)
        d["emp.var.rate"] = d.pop("emp_var_rate")
        d["cons.price.idx"] = d.pop("cons_price_idx")
        d["cons.conf.idx"] = d.pop("cons_conf_idx")
        d["previously_contacted"] = 1 if d["pdays"] != 999 else 0
        del d["pdays"]
        return pd.DataFrame([d])


@router.post("/predict")
async def predict(req: PredictionRequest, session: AsyncSession = Depends(get_session)):
    global _prediction_count
    if _model is None:
        load_champion_model()
    df = req.to_dataframe()
    proba = float(_model.predict_proba(df)[0, 1])
    label = 1 if proba >= _threshold else 0

    session.add(PredictionLog(
        id=str(uuid.uuid4()),
        timestamp=datetime.datetime.utcnow(),
        model_version=_model_version,
        input_features=req.model_dump(),
        predicted_probability=proba,
        predicted_label=label,
    ))
    await session.commit()

    _prediction_count += 1
    if _prediction_count % get_settings().drift_window_size == 0:
        asyncio.create_task(_trigger_drift())

    return {"prediction": label, "probability": proba, "model_version": _model_version}


async def _trigger_drift():
    from backend.platform.routers.drift import run_drift_check
    await run_drift_check()
