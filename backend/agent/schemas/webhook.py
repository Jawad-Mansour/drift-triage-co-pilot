class DriftWebhookPayload(BaseModel):
    event_id: str
    model_name: str
    model_version: str
    severity: Literal["OK", "WARNING", "CRITICAL"]
    drift_features: List[Dict[str, Any]]
    timestamp: str
    window_size: int