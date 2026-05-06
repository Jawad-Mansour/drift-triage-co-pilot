from fastapi import FastAPI
from .routers import promotion
app = FastAPI(title="Drift Triage Platform")

app.include_router(promotion.router)

# ... other endpoints (like /predict) can be added here or in separate routers