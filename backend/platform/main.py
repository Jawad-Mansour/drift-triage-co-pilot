from contextlib import asynccontextmanager

import mlflow
from fastapi import FastAPI

from backend.platform.db.base import Base, get_engine
from backend.platform.routers import predict, registry, promotion, retrain, replay
from backend.platform.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    predict.load_champion_model()
    yield
    await engine.dispose()


app = FastAPI(title="ML Platform", lifespan=lifespan)

app.include_router(predict.router)
app.include_router(registry.router)
app.include_router(promotion.router)
app.include_router(retrain.router)
app.include_router(replay.router)


@app.get("/health")
def health():
    return {"status": "ok"}
