from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="ignore")

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"

    # ── LLM ──────────────────────────────────────────────────────────────────
    openai_api_key: SecretStr
    groq_api_key: SecretStr | None = None

    # ── Postgres ──────────────────────────────────────────────────────────────
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "drift"
    postgres_password: SecretStr
    postgres_db: str = "drift_triage"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr

    # ── Services ──────────────────────────────────────────────────────────────
    platform_url: str = "http://platform:8001"
    mlflow_tracking_uri: str = "http://mlflow:5000"

    # ── Auth ──────────────────────────────────────────────────────────────────
    agent_api_key: SecretStr
    emergency_bypass_key: SecretStr

    # ── HIL ───────────────────────────────────────────────────────────────────
    approval_timeout_minutes: int = 10

    # ── Drift thresholds ──────────────────────────────────────────────────────
    drift_psi_threshold_medium: float = 0.1
    drift_psi_threshold_high: float = 0.2
    drift_psi_threshold_critical: float = 0.25
    drift_chi2_threshold_medium: float = 0.05
    drift_chi2_threshold_high: float = 0.01

    # ── Action logic ──────────────────────────────────────────────────────────
    recent_retrain_threshold_minutes: int = 30
    poor_performance_auc_threshold: float = 0.65
    economic_features: str = "euribor3m,cons.price.idx"

    # ── Queue / idempotency ───────────────────────────────────────────────────
    max_retries: int = 5
    idempotency_ttl_retrain: int = 86400  # 24 h
    idempotency_ttl_other: int = 3600  # 1 h

    # ── Computed properties ───────────────────────────────────────────────────
    @property
    def database_url(self) -> str:
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        pw = self.redis_password.get_secret_value()
        return f"redis://:{pw}@{self.redis_host}:{self.redis_port}"

    @property
    def economic_feature_list(self) -> list[str]:
        return [f.strip() for f in self.economic_features.split(",") if f.strip()]

    @model_validator(mode="after")
    def _psi_order(self) -> "Settings":
        if not (
            self.drift_psi_threshold_medium
            < self.drift_psi_threshold_high
            < self.drift_psi_threshold_critical
        ):
            raise ValueError("PSI thresholds must satisfy: medium < high < critical")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton. Call get_settings.cache_clear() in tests."""
    return Settings()  # type: ignore[call-arg]
