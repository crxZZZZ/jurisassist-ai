from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JURIS_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://jurisassist:change-this-local-password@127.0.0.1:5432/jurisassist"
    )
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen3:4b"
    embeddings_model: str = "intfloat/multilingual-e5-small"
    data_dir: Path = Path("data")
    origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]
    cookie_secure: bool = False
    environment: str = "local"
    prompt_version: str = "v2"
    log_level: str = "INFO"
    session_hours: int = 12
    llm_timeout: int = 120
    job_lease_seconds: int = 600
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pages: int = 50
    max_document_chars: int = 180_000
    max_jobs_per_user: int = 3
    source_check_hours: int = 24
    source_stale_days: int = 7
    worker_metrics_url: str = "http://127.0.0.1:8001"
    worker_metrics_host: str = "127.0.0.1"

    @model_validator(mode="after")
    def production_cookies(self):
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("Production requires JURIS_COOKIE_SECURE=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
