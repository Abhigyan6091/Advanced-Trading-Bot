"""Settings loading and derived values."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import BrokerKind, Settings


def settings(**overrides) -> Settings:
    base = dict(
        postgres_user="u",
        postgres_password="p",
        postgres_db="d",
        postgres_host="h",
        postgres_port=5432,
    )
    return Settings(**{**base, **overrides})


class TestDefaults:
    def test_paper_is_the_default_broker(self):
        assert settings().broker is BrokerKind.PAPER

    def test_live_trading_is_off_by_default(self):
        assert settings().allow_live_trading is False

    def test_no_credentials_needed_for_paper(self):
        s = settings()
        assert not s.testnet_credentials_present
        assert s.broker is BrokerKind.PAPER


class TestDerived:
    def test_database_url_is_assembled_from_parts(self):
        assert settings().database_url == "postgresql+psycopg://u:p@h:5432/d"

    def test_credentials_require_both_halves(self):
        assert not settings(binance_api_key="k").testnet_credentials_present
        assert not settings(binance_api_secret="s").testnet_credentials_present
        assert settings(binance_api_key="k", binance_api_secret="s").testnet_credentials_present


class TestValidation:
    def test_log_level_is_normalised(self):
        assert settings(log_level="debug").log_level == "DEBUG"

    def test_bad_log_level_is_rejected(self):
        with pytest.raises(ValueError, match="log_level must be one of"):
            settings(log_level="chatty")

    def test_money_settings_are_decimal(self):
        s = settings(paper_starting_balance="50000")
        assert isinstance(s.paper_starting_balance, Decimal)
        assert s.paper_starting_balance == Decimal("50000")

    def test_unknown_broker_is_rejected(self):
        with pytest.raises(ValueError):
            settings(broker="live")
