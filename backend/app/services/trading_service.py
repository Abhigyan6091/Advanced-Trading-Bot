"""Application service: the pipeline, wired to persistence.

The one place where a run of the trading pipeline is turned into stored rows.
Every signal is recorded, every decision is recorded, and orders and fills are
recorded when they exist — so the dashboard's history is complete rather than a
log of successes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.brokers import Broker, PaperBroker
from app.core.config import BrokerKind, Settings, get_settings
from app.core.logging import get_logger
from app.db.repositories import (
    AuditRepository,
    FillRepository,
    InstrumentRepository,
    OrderRepository,
    RiskDecisionRepository,
    SignalRepository,
)
from app.domain import Instrument, Signal
from app.portfolio import Portfolio, PortfolioSnapshot
from app.risk import RiskEngine, RiskLimits
from app.trading import TradeOutcome, TradingPipeline

log = get_logger(__name__)


def build_broker(settings: Settings, instruments: dict[str, Instrument]) -> Broker:
    """Construct the configured broker.

    Paper is the default and needs nothing. Testnet requires credentials, and
    their absence is reported here rather than as an authentication failure on
    the first order.
    """
    if settings.broker is BrokerKind.TESTNET:
        if not settings.testnet_credentials_present:
            raise ValueError(
                "BROKER=testnet requires BINANCE_API_KEY and BINANCE_API_SECRET. "
                "Use BROKER=paper to run without credentials."
            )
        from app.brokers import BinanceTestnetBroker

        return BinanceTestnetBroker(
            settings.binance_api_key or "", settings.binance_api_secret or ""
        )

    return PaperBroker(
        commission_rate=settings.paper_commission_rate,
        slippage_bps=settings.paper_slippage_bps,
        instruments=instruments,
    )


class TradingService:
    """Runs signals through the pipeline and persists everything they produce.

    Known constraint, deferred to Phase 8: this service (and the PaperBroker
    it builds) is currently constructed fresh per call -- correct for
    scripts.seed, which holds one long-lived instance for an entire replay,
    but wrong for a request-scoped web session, where a second construction
    loses the broker's in-memory idempotency table and any marks set on it.
    No API route calls handle_signal today (the dashboard's routes are
    read-only, and manual submission is explicitly not wired -- see the Trade
    page), so this is not yet reachable in practice. A live trading loop
    needs a process-lifetime broker/session rather than a per-request one;
    that decision belongs with Phase 8's authentication and execution-service
    design, not bolted on ahead of it.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        limits: RiskLimits | None = None,
        broker: Broker | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()

        self.signals = SignalRepository(session)
        self.decisions = RiskDecisionRepository(session)
        self.orders = OrderRepository(session)
        self.fills = FillRepository(session)
        self.instruments_repo = InstrumentRepository(session)
        self.audit = AuditRepository(session)

        instruments = {i.symbol: i for i in self.instruments_repo.all_instruments()}
        self.instruments = instruments

        self.broker = broker or build_broker(self.settings, instruments)
        self._ml_model = None
        if self.settings.ml_risk_enabled:
            from app.ml import get_default_model

            self._ml_model = get_default_model()
        self.risk_engine = RiskEngine(limits or RiskLimits(), ml_model=self._ml_model)

        # The portfolio is rebuilt from the stored fill ledger, so restarting
        # the process cannot lose or invent a position.
        self.portfolio = Portfolio.from_fills(
            self.fills.all_fills(), self.settings.paper_starting_balance
        )
        self.pipeline = TradingPipeline(
            risk_engine=self.risk_engine,
            broker=self.broker,
            portfolio=self.portfolio,
            instruments=instruments,
        )

    # --- public API ----------------------------------------------------

    def handle_signal(
        self,
        signal: Signal,
        *,
        quantity: Decimal | None = None,
        volatility: Decimal | None = None,
    ) -> TradeOutcome:
        """Run one signal end to end and persist the whole trail."""
        ml_features = self._compute_ml_features(signal) if self._ml_model else None
        outcome = self.pipeline.handle_signal(
            signal, quantity=quantity, volatility=volatility, ml_features=ml_features
        )
        self._persist(outcome)
        return outcome

    def _compute_ml_features(self, signal: Signal) -> dict[str, Decimal] | None:
        """Market features for the ML check, from recently stored bars.

        Only queried when a model is actually loaded -- with ML disabled or
        absent this adds no database round trip at all.
        """
        from app.marketdata import BarRepository
        from app.ml.features import MIN_BARS, compute_market_features

        bars = BarRepository(self.session).get_bars(
            signal.symbol, limit=MIN_BARS, end_time=signal.bar_close_time
        )
        return compute_market_features(bars)

    def set_mark(self, symbol: str, price: Decimal) -> None:
        # Threads the pipeline's simulated clock, when one is set (a replay
        # driven by scripts.seed), into the portfolio's day-rollover tracking
        # -- otherwise "today" for the daily-loss check would be wall-clock
        # time while every fill is stamped with a simulated one.
        self.portfolio.set_mark(symbol, price, when=self.pipeline.now)
        if isinstance(self.broker, PaperBroker):
            self.broker.set_mark(symbol, price)

    def set_time(self, when: datetime | None) -> None:
        """Advance the simulation clock across the whole pipeline."""
        self.pipeline.set_time(when)

    def snapshot(self) -> PortfolioSnapshot:
        return self.portfolio.snapshot()

    # --- persistence ---------------------------------------------------

    def _persist(self, outcome: TradeOutcome) -> None:
        # Signals are stored whether or not they were actionable: a strategy
        # cannot be evaluated from its trades alone.
        self.signals.save(outcome.signal)

        if outcome.decision is not None:
            self.decisions.save(outcome.decision)
            self.audit.record(
                action=f"risk.{outcome.decision.action.value.lower()}",
                entity_type="risk_decision",
                entity_id=str(outcome.decision.id),
                detail={
                    "symbol": outcome.signal.symbol,
                    "score": str(outcome.decision.score),
                    "reasons": list(outcome.decision.reasons),
                },
            )

        if outcome.order is not None:
            self.orders.save(outcome.order)
            self.audit.record(
                action="order.submitted",
                entity_type="order",
                entity_id=outcome.order.client_order_id,
                detail={
                    "symbol": outcome.order.symbol,
                    "side": outcome.order.side.value,
                    "quantity": str(outcome.order.quantity),
                },
            )

        for fill in outcome.fills:
            self.fills.save(fill)

        self.session.flush()
