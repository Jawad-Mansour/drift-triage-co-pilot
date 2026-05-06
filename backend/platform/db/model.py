from sqlalchemy import Column, String, Float, Integer, DateTime, JSON
from platform.db.base import Base
import uuid
import datetime

class PredictionLog(Base):
    __tablename__ = "predictions_log"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    model_version = Column(String(50))
    input_features = Column(JSON)
    predicted_probability = Column(Float)
    predicted_label = Column(Integer)

class DriftEvent(Base):   # optional, to store historical drift reports
    __tablename__ = "drift_events"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    model_version = Column(String(50))
    severity = Column(String(20))
    drift_features = Column(JSON)
    webhook_sent = Column(Integer, default=0)