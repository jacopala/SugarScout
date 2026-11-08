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

    # --- Hackathon demo -------------------------------------------------------------
    # Protects every mutating endpoint (X-Demo-Key header). Empty disables the check,
    # which is only allowed locally.
    demo_access_code: str = ""
    demo_child_name: str = "Alex"
    demo_child_age_band: str = "8-10"
    # The fake CGM writes one reading per tick (real timestamps, sped-up dynamics).
    sim_tick_seconds: int = 5
    sim_enabled: bool = True
    sim_history_days: int = 14

    # Rules (demo-scaled defaults; the doc's placeholders for thresholds).
    rule_urgent_low: int = 54
    rule_low: int = 70
    rule_low_consecutive: int = 2
    rule_high: int = 250
    rule_high_consecutive: int = 4
    rule_rapid_drop_mg_dl: int = 25
    rule_rapid_drop_window: int = 4
    rule_data_gap_seconds: int = 30
    sms_cooldown_seconds: int = 60

    # Twilio (trial account is fine). Missing values => SMS runs in dry-run mode.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    parent_phone: str = ""
    # Twilio TRIAL accounts may only send predefined templates (error 572006 otherwise).
    # Set e.g. "sms_account_alerts" on a trial; leave empty once the account is upgraded.
    twilio_trial_template: str = ""

    # NVIDIA API catalog (OpenAI-compatible).
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nemotron_chat_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    nemotron_analysis_model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    llm_timeout_s: float = 20.0
    # Nemotron 3.5 models reason by default; off keeps chat replies fast and the token
    # budget for the answer (sent as chat_template_kwargs.enable_thinking).
    llm_enable_thinking: bool = False

    @property
    def twilio_configured(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_auth_token
            and self.twilio_from
            and self.parent_phone
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.nvidia_api_key)

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
