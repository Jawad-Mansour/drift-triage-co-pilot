from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr

    # Platform + Agent
    platform_url: str = "http://platform:8001"
    agent_url: str = "http://agent:8002"
    agent_api_key: SecretStr

    # Retry
    max_retries: int = 5

    @property
    def redis_url(self) -> str:
        pw = self.redis_password.get_secret_value()
        return f"redis://:{pw}@{self.redis_host}:{self.redis_port}"


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()  # type: ignore[call-arg]
