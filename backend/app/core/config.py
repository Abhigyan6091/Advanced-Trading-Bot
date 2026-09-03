"""Typed application settings, loaded once from the environment."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerKind(str, Enum):
    """Which execution venue the platform routes orders to.

    There is deliberately no ``LIVE`` member. Real-money execution is not
    implemented, so it cannot be selected by misconfiguration.
    """

    PAPER = "paper"
    TESTNET = "testnet"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- application ---------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Strategic Trade Analyzer"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    #: Origins allowed to call the API from a browser. The dashboard runs on
    #: a different origin in development, so this cannot be empty there; it is
    #: an explicit allowlist rather than a wildcard so credentials stay safe.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- database ------------------------------------------------------
    postgres_user: str = "sta"
    postgres_password: str = "sta_dev_password"
    postgres_db: str = "sta"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # --- execution -----------------------------------------------------
    broker: BrokerKind = BrokerKind.PAPER
    allow_live_trading: bool = False

    binance_api_key: str | None = None
    binance_api_secret: str | None = None

    # --- paper broker --------------------------------------------------
    paper_starting_balance: Decimal = Decimal("100000")
    paper_commission_rate: Decimal = Decimal("0.0004")
    paper_slippage_bps: Decimal = Decimal("2")

    # --- authentication ----------------------------------------------------
    #: Signing secret for access tokens. The default is only ever reached in
    #: a fresh dev checkout; production must set a real secret via
    #: JWT_SECRET, or every token becomes forgeable by anyone who reads this
    #: source file.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_expiry_minutes: int = 60 * 12

    #: Bootstrap admin, created on startup if it does not already exist and
    #: both are set. Leave unset in an environment where users are created
    #: another way; nothing else depends on this account existing.
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    # --- AI Analyst ----------------------------------------------------------
    anthropic_api_key: str | None = None
    ai_analyst_model: str = "claude-opus-5"
    #: Hard ceiling on tool-calling turns per question, independent of any
    #: token budget -- the loop stops even if Claude keeps requesting tools.
    ai_analyst_max_tool_turns: int = 6

    # --- ML-assisted risk ------------------------------------------------
    #: Whether the risk engine may load a trained adverse-outcome model. Even
    #: when true, the model only engages if one has actually been trained and
    #: saved to disk (see scripts.train_risk_model) -- a fresh checkout has no
    #: model file, so this flag alone never changes behaviour by itself.
    ml_risk_enabled: bool = True

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return v

    @model_validator(mode="after")
    def _production_must_not_use_the_dev_secret(self) -> Settings:
        if self.app_env == "production" and self.jwt_secret == "dev-only-insecure-secret-change-me":
            raise ValueError(
                "JWT_SECRET must be set to a real secret in production -- "
                "refusing to start with every token forgeable from public source."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def testnet_credentials_present(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process and cached."""
    return Settings()
