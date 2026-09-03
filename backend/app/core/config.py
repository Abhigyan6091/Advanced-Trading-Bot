"""Typed application settings, loaded once from the environment."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import computed_field, field_validator
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

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def testnet_credentials_present(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process and cached."""
    return Settings()
