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
    api_max_body_bytes: int = Field(default=256 * 1024, ge=1024, le=10 * 1024 * 1024)
    login_verification_limit_per_minute: int = Field(default=120, ge=10, le=10000)
    login_source_limit_per_minute: int = Field(default=60, ge=5, le=10000)
    login_max_concurrent_verifications: int = Field(default=2, ge=1, le=32)
    login_throttle_max_keys: int = Field(default=2048, ge=128, le=100000)
    login_failure_audit_limit_per_minute: int = Field(default=20, ge=1, le=1000)
    login_failure_audit_retention_days: int = Field(default=90, ge=1, le=3650)
    login_failure_audit_max_rows: int = Field(default=10000, ge=100, le=1000000)
    llm_max_concurrent_generations: int = Field(default=2, ge=1, le=32)
    llm_max_user_concurrent_generations: int = Field(default=1, ge=1, le=8)
    llm_user_requests_per_hour: int = Field(default=20, ge=1, le=1000)
    llm_user_tokens_per_day: int = Field(default=100000, ge=6144, le=100000000)
    llm_global_tokens_per_day: int = Field(default=1000000, ge=6144, le=1000000000)
    llm_max_tracked_users: int = Field(default=10000, ge=100, le=1000000)
    llm_chat_cooldown_seconds: int = Field(default=2, ge=0, le=3600)
    llm_weekly_cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    llm_team_summary_cooldown_seconds: int = Field(default=60, ge=0, le=86400)
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
