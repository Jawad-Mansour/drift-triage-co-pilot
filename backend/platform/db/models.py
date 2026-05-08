import uuid
import datetime
from sqlalchemy import String, Float, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from backend.platform.db.base import Base


class PredictionLog(Base):
    __tablename__ = "predictions_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    model_version: Mapped[str] = mapped_column(String(50))
    input_features: Mapped[dict] = mapped_column(JSON)
    predicted_probability: Mapped[float] = mapped_column(Float)
    predicted_label: Mapped[int] = mapped_column(Integer)


class DriftReference(Base):
    __tablename__ = "drift_reference"

    feature_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    feature_type: Mapped[str] = mapped_column(String(20))
    bin_edges: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ref_counts: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(50))
