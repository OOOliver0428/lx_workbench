from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MVP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./data/mvp.db"
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8787, ge=1, le=65535)
    session_cookie_name: str = "mvp_session"
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    cookie_secure: bool = False
    allowed_hosts_csv: str = "127.0.0.1,localhost"
    cors_origins_csv: str = ""
    log_level: str = "INFO"
    llm_config_secret: str = ""
    llm_timeout_seconds: float = Field(default=60, ge=5, le=180)
    llm_test_token_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_model: str = "MiniMax-M2.7"
    minimax_access_mode: str = "auto"
    minimax_timeout_seconds: float = Field(default=60, ge=5, le=180)

    @property
    def allowed_hosts(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts_csv.split(",") if item.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
