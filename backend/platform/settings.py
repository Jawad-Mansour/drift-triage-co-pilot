from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "postgres"
    postgres_user: str = "drift"
    postgres_password: SecretStr
    postgres_db: str = "drift_triage"
    postgres_port: int = 5432

    mlflow_tracking_uri: str = "http://mlflow:5000"
    agent_url: str = "http://agent:8002"
    agent_api_key: SecretStr

    drift_window_size: int = 500
    drift_psi_threshold_high: float = 0.2

    model_name: str = "BankMarketingXGB"

    @property
    def database_url(self) -> str:
        pw = self.postgres_password.get_secret_value()
        return f"postgresql+asyncpg://{self.postgres_user}:{pw}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache(maxsize=1)
def get_settings() -> PlatformSettings:
    return PlatformSettings()  # type: ignore[call-arg]
