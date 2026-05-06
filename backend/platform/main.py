from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.platform.routers import prediction, registry, drift_trigger
from backend.platform.db.base import engine, Base
import mlflow
from backend.platform.routers.prediction import load_production_model

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    Base.metadata.create_all(bind=engine)
    # Load production model into memory
    load_production_model()
    yield
    # Cleanup (optional)

app = FastAPI(title="ML Platform", lifespan=lifespan)

app.include_router(prediction.router)
app.include_router(registry.router)   # for /promote
app.include_router(drift_trigger.router)  # optional manual trigger

@app.get("/health")
def health():
    return {"status": "ok"}