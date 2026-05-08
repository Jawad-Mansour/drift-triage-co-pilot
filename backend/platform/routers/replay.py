import os

import mlflow
import mlflow.sklearn
import pandas as pd
from fastapi import APIRouter, HTTPException
from mlflow.tracking import MlflowClient
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from pydantic import BaseModel

from backend.platform.settings import get_settings

router = APIRouter(tags=["replay"])


class ReplayRequest(BaseModel):
    investigation_id: str | None = None
    feature_name: str | None = None


@router.post("/replay-test")
async def replay_test(req: ReplayRequest = ReplayRequest()):
    s = get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    mv = client.get_model_version_by_alias(s.model_name, "champion")
    run = client.get_run(mv.run_id)
    threshold = float(run.data.params.get("tuned_threshold", 0.5))

    model = mlflow.sklearn.load_model(f"models:/{s.model_name}@champion")

    data_path = os.getenv("DATA_PATH", "/app/ml/data/bank-additional-full.csv")
    if not os.path.exists(data_path):
        raise HTTPException(status_code=503, detail="Test data not found")

    df = pd.read_csv(data_path, sep=";")
    df = df.drop(columns=["duration"])
    df["previously_contacted"] = (df["pdays"] != 999).astype(int)
    df = df.drop(columns=["pdays"])
    y = df["y"].map({"yes": 1, "no": 0})
    X = df.drop(columns=["y"])

    _, X_tmp, _, y_tmp = train_test_split(X, y, test_size=0.4, stratify=y, random_state=42)
    _, X_test, _, y_test = train_test_split(X_tmp, y_tmp, test_size=0.5, stratify=y_tmp, random_state=42)

    proba = model.predict_proba(X_test)[:, 1]
    y_pred = (proba >= threshold).astype(int)

    return {
        "auc": float(roc_auc_score(y_test, proba)),
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "f1": float(f1_score(y_test, y_pred)),
        "model_version": mv.version,
        "n_samples": len(X_test),
    }
