from fastapi import APIRouter, BackgroundTasks
from ml.evaluation.drift_detector import main as run_drift

router = APIRouter(prefix="/drift", tags=["drift"])

def run_drift_background():
    run_drift()

@router.post("/trigger")
async def trigger_drift_check(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_drift_background)
    return {"message": "Drift detection started in background"}