"""Application settings, loaded from environment variables (and `.env` in local dev)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class DbSslMode(StrEnum):
    DISABLE = "disable"
    REQUIRE = "require"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Env = Env.LOCAL
    service_name: str = "api"
    log_level: str = "INFO"
    log_json: bool = True

    # Database (Tiger Cloud in staging/production, TimescaleDB image locally).
    # Accepts postgres://, postgresql:// or postgresql+asyncpg:// URLs.
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://sugarscout:sugarscout@localhost:55432/sugarscout")
    )
    db_ssl_mode: DbSslMode = DbSslMode.DISABLE
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0
    db_statement_timeout_ms: int = 5_000

    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173"

    worker_heartbeat_key: str = "worker:heartbeat"

    @model_validator(mode="after")
    def _require_tls_outside_local(self) -> Settings:
        if self.env in (Env.STAGING, Env.PRODUCTION) and self.db_ssl_mode is not DbSslMode.REQUIRE:
            raise ValueError("DB_SSL_MODE must be 'require' in staging and production")
        return self

    @property
    def async_database_url(self) -> str:
        """The database URL normalized for SQLAlchemy's asyncpg driver.

        Any `sslmode` query parameter is stripped because asyncpg does not accept it;
        TLS is controlled by `db_ssl_mode` instead.
        """
        url = str(self.database_url)
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix) :]
        if "?" in url:
            base, query = url.split("?", 1)
            params = [p for p in query.split("&") if p and not p.startswith("sslmode=")]
            url = base + ("?" + "&".join(params) if params else "")
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
