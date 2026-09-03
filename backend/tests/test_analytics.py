"""Performance metrics, checked against hand-computed values."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analytics import (
    PerformanceReport,
    TradeRecord,
    build_report,
    calmar_ratio,
    expectancy,
    max_drawdown,
    profit_factor,
    returns,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)


def curve(*values) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


def trades(*pnls) -> list[TradeRecord]:
    return [TradeRecord("BTCUSDT", Decimal(str(p))) for p in pnls]


class TestReturns:
    def test_period_returns_hand_computed(self):
        # 100 -> 110 is +10%; 110 -> 99 is -10%
        assert returns(curve(100, 110, 99)) == [Decimal("0.1"), Decimal("-0.1")]

    def test_total_return_hand_computed(self):
        assert total_return(curve(100, 150)) == Decimal("0.5")
        assert total_return(curve(100, 50)) == Decimal("-0.5")

    def test_a_single_point_has_no_return(self):
        assert total_return(curve(100)) == 0
        assert returns(curve(100)) == []


class TestDrawdown:
    def test_a_monotonically_rising_curve_has_none(self):
        assert max_drawdown(curve(100, 110, 120, 130)) == 0

    def test_measured_from_the_running_peak_not_the_start(self):
        """A curve that doubles then halves is 50% down, not flat."""
        assert max_drawdown(curve(100, 200, 100)) == Decimal("0.5")

    def test_hand_computed(self):
        # Peak 120, trough 90 -> (120-90)/120 = 0.25
        assert max_drawdown(curve(100, 120, 90, 110)) == Decimal("0.25")

    def test_keeps_the_worst_of_several_declines(self):
        assert max_drawdown(curve(100, 90, 100, 60, 100)) == Decimal("0.4")

    def test_empty_curve_is_zero(self):
        assert max_drawdown([]) == 0


class TestSharpe:
    def test_a_flat_curve_scores_zero_not_infinity(self):
        """No variation means no risk to reward, not perfect skill."""
        assert sharpe_ratio(curve(100, 100, 100, 100)) == 0

    def test_steady_gains_score_positive(self):
        assert sharpe_ratio(curve(100, 101, 102, 103, 104)) > 0

    def test_steady_losses_score_negative(self):
        assert sharpe_ratio(curve(100, 99, 98, 97, 96)) < 0

    def test_more_volatile_path_to_the_same_place_scores_lower(self):
        smooth = curve(100, 102, 104, 106, 108)
        choppy = curve(100, 115, 95, 120, 108)
        assert sharpe_ratio(smooth) > sharpe_ratio(choppy)

    def test_annualisation_scales_with_the_interval(self):
        c = curve(100, 101, 102, 103, 104)
        assert sharpe_ratio(c, "1h") > sharpe_ratio(c, "1d")

    def test_too_few_points_returns_zero(self):
        assert sharpe_ratio(curve(100)) == 0


class TestSortino:
    def test_upside_volatility_is_not_penalised(self):
        """Sortino's whole point: only downside deviation is risk."""
        upside_only = curve(100, 130, 160, 200)
        assert sortino_ratio(upside_only) == 0  # no downside deviation at all

    def test_downside_is_penalised(self):
        assert sortino_ratio(curve(100, 95, 105, 90, 110)) != 0

    def test_sortino_exceeds_sharpe_for_upward_skew(self):
        c = curve(100, 120, 118, 145, 143, 175)
        assert sortino_ratio(c) > sharpe_ratio(c)


class TestTradeStatistics:
    def test_win_rate_hand_computed(self):
        assert win_rate(trades(100, -50, 200, -25)) == Decimal("0.5")

    def test_break_even_counts_as_a_loss(self):
        """A trade that returns nothing after costs was not a win."""
        assert win_rate(trades(100, 0)) == Decimal("0.5")

    def test_no_trades_is_zero_not_an_error(self):
        assert win_rate([]) == 0

    def test_profit_factor_hand_computed(self):
        # Gross profit 300, gross loss 100 -> 3.0
        assert profit_factor(trades(100, 200, -100)) == Decimal("3")

    def test_profit_factor_is_undefined_without_losses(self):
        """None rather than infinity: reporting a number there would mislead."""
        assert profit_factor(trades(100, 200)) is None

    def test_profit_factor_below_one_signals_a_losing_system(self):
        assert profit_factor(trades(50, -200)) < 1

    def test_expectancy_is_average_pnl_per_trade(self):
        assert expectancy(trades(100, -50, 200, -50)) == Decimal("50")

    def test_calmar_is_return_over_drawdown(self):
        # +50% return, 25% max drawdown -> 2.0
        assert calmar_ratio(curve(100, 120, 90, 150)) == Decimal("2")

    def test_calmar_is_undefined_without_drawdown(self):
        assert calmar_ratio(curve(100, 110, 120)) is None


class TestReport:
    def test_assembles_every_metric(self):
        report = build_report(curve(100, 120, 90, 150), trades(100, -50, 200))
        assert isinstance(report, PerformanceReport)
        assert report.starting_equity == Decimal("100")
        assert report.ending_equity == Decimal("150")
        assert report.total_return == Decimal("0.5")
        assert report.total_trades == 3
        assert report.winning_trades == 2
        assert report.losing_trades == 1

    def test_summary_renders_undefined_values_as_na(self):
        report = build_report(curve(100, 110, 120), trades(100, 200))
        text = report.summary()
        assert "Profit factor   : n/a" in text
        assert "Calmar ratio    : n/a" in text

    def test_handles_an_empty_run(self):
        report = build_report([], [])
        assert report.total_return == 0
        assert report.total_trades == 0
        assert report.profit_factor is None

    @pytest.mark.parametrize("interval", ["1m", "1h", "1d"])
    def test_every_supported_interval_annualises(self, interval):
        report = build_report(curve(100, 101, 102, 103), trades(10), interval)
        assert report.sharpe_ratio != 0
