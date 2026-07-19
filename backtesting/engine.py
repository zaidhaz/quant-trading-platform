"""Event-driven backtesting engine.

Drives the exact same `strategies` + `risk` + `portfolio` code used live, with
`BrokerSimulator` standing in for a live `execution` adapter behind conceptually the
same fill-producing role. Realistic costs: trading fees, funding, and configurable
slippage are all applied to every fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from backtesting.broker_simulator import BacktestCosts, BrokerSimulator
from backtesting.data_feed import DataFeed
from backtesting.event_simulator import EventSimulator
from backtesting.slippage_models import FixedBpsSlippage
from core.enums import ExitReason, OrderSide, PositionSide, SignalDirection
from core.event_bus import EventBus
from core.events import CandleEvent, FillEvent, RiskRejectedEvent, SignalEvent
from core.exceptions import InsufficientDataError
from core.types import Position
from features.feature_engine import FeatureEngine
from market_regime import market_state
from portfolio.portfolio_manager import PortfolioManager
from portfolio.position_tracker import ClosedTrade
from risk.limits import RiskLimits
from risk.risk_engine import RiskEngine
from strategies.base_strategy import Strategy
from strategies.context import build_context

_DIRECTION_TO_SIDE = {
    SignalDirection.LONG: PositionSide.LONG,
    SignalDirection.SHORT: PositionSide.SHORT,
}
_ENTRY_ORDER_SIDE = {SignalDirection.LONG: OrderSide.BUY, SignalDirection.SHORT: OrderSide.SELL}
_EXIT_ORDER_SIDE = {PositionSide.LONG: OrderSide.SELL, PositionSide.SHORT: OrderSide.BUY}


@dataclass(slots=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    taker_fee_rate: float = 0.0004
    slippage_bps: float = 2.0
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    use_confidence_scaling: bool = False
    warmup_bars: int = 0


@dataclass(slots=True)
class BacktestResult:
    strategy_id: str
    symbol_native: str
    timeframe: str
    equity_curve: list[tuple[datetime, float]]
    closed_trades: list[ClosedTrade]
    signals: list[SignalEvent]
    initial_capital: float
    final_equity: float


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        feed: DataFeed,
        config: BacktestConfig | None = None,
        strategy_id: str | None = None,
        feature_engine: FeatureEngine | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.strategy = strategy
        self.feed = feed
        self.config = config or BacktestConfig()
        self.strategy_id = strategy_id or type(strategy).__name__
        self.features = feature_engine or FeatureEngine()
        self.bus = bus or EventBus()

        self.portfolio = PortfolioManager(self.config.initial_capital)
        self.risk_engine = RiskEngine(self.config.risk_limits, self.config.use_confidence_scaling)
        self.broker = BrokerSimulator(
            BacktestCosts(self.config.taker_fee_rate, FixedBpsSlippage(self.config.slippage_bps))
        )
        self.regime_df = market_state.compute(
            feed.candles, self.features, feed.symbol, feed.timeframe
        )
        self.signals: list[SignalEvent] = []

        self.bus.subscribe(CandleEvent, self._on_candle)

    def run(self) -> BacktestResult:
        EventSimulator(self.bus).run(self.feed)
        self._force_close_at_end()
        equity_curve = self.portfolio.equity_curve
        return BacktestResult(
            strategy_id=self.strategy_id,
            symbol_native=self.feed.symbol.native(),
            timeframe=self.feed.timeframe,
            equity_curve=equity_curve,
            closed_trades=self.portfolio.closed_trades,
            signals=self.signals,
            initial_capital=self.config.initial_capital,
            final_equity=equity_curve[-1][1] if equity_curve else self.config.initial_capital,
        )

    def _on_candle(self, event: CandleEvent) -> None:
        if event.bar_index < self.config.warmup_bars:
            return

        symbol = self.feed.symbol
        mark_price = event.close
        position = self.portfolio.get_position(symbol)

        funding_rate_now = self.feed.funding_events.iloc[event.bar_index]
        if position is not None and not pd.isna(funding_rate_now):
            self.portfolio.apply_funding(symbol, mark_price, float(funding_rate_now))
            position = self.portfolio.get_position(symbol)  # refresh after funding accrual

        equity = self.portfolio.equity({symbol.canonical: mark_price})
        context = build_context(
            self.feed.candles,
            self.features,
            symbol,
            self.feed.timeframe,
            self.regime_df,
            event.bar_index,
            equity,
            position,
        )

        if position is None:
            self._try_entry(context, event)
        else:
            self._check_exit(context, position, event)

        self.portfolio.record_equity(event.ts, {symbol.canonical: mark_price})

    def _try_entry(self, context, event: CandleEvent) -> None:
        try:
            setup = self.strategy.detect_setup(context)
        except InsufficientDataError:
            return
        if setup is None or not self.strategy.check_entry(context, setup):
            return

        stop_loss = self.strategy.stop_loss(context, setup)
        take_profit = self.strategy.take_profit(context, setup)
        suggested_size = self.strategy.position_size(context, setup)
        confidence = self.strategy.confidence(context, setup)
        reasoning = self.strategy.reasoning(context, setup)

        signal_event = SignalEvent(
            ts=event.ts,
            symbol=event.symbol,
            strategy_id=self.strategy_id,
            direction=setup.direction,
            confidence=confidence,
            reasoning=reasoning,
            entry_price=setup.reference_price,
            equity_at_signal=context.equity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            suggested_size=suggested_size,
            regime_snapshot=context.regime.current().as_dict(),
            features_snapshot=self._snapshot_common_features(context),
        )
        self.signals.append(signal_event)
        self.bus.publish(signal_event)

        decision = self.risk_engine.evaluate(
            suggested_size, setup.reference_price, stop_loss, confidence, context.equity
        )
        if not decision.approved:
            self.bus.publish(
                RiskRejectedEvent(
                    ts=event.ts,
                    symbol=event.symbol,
                    strategy_id=self.strategy_id,
                    signal_id=signal_event.event_id,
                    reason=decision.reason or "rejected",
                    correlation_id=signal_event.correlation_id,
                )
            )
            return

        side = _ENTRY_ORDER_SIDE[setup.direction]
        fill_price, fee = self.broker.fill(side, decision.quantity, setup.reference_price)
        self.portfolio.open_position(
            event.symbol,
            _DIRECTION_TO_SIDE[setup.direction],
            fill_price,
            decision.quantity,
            event.ts,
            stop_loss,
            take_profit,
            entry_fee=fee,
        )
        self.bus.publish(
            FillEvent(
                ts=event.ts,
                symbol=event.symbol,
                strategy_id=self.strategy_id,
                order_id=signal_event.event_id,
                side=side,
                quantity=decision.quantity,
                price=fill_price,
                fee=fee,
                is_position_open=True,
                correlation_id=signal_event.correlation_id,
            )
        )

    def _check_exit(self, context, position: Position, event: CandleEvent) -> None:
        # Conservative, documented ordering: a strategy-driven exit (evaluated at
        # bar close) is checked first, then stop-loss, then take-profit — a bar that
        # breaches both stop and target is assumed to have hit the stop first.
        exit_reason: ExitReason | None = None
        if self.strategy.check_exit(context, position):
            exit_reason = ExitReason.STRATEGY_EXIT
        elif position.stop_loss is not None and self._stop_hit(position, event):
            exit_reason = ExitReason.STOP_LOSS
        elif position.take_profit is not None and self._take_profit_hit(position, event):
            exit_reason = ExitReason.TAKE_PROFIT

        if exit_reason is None:
            return

        exit_price = self._exit_price(position, event, exit_reason)
        self._close(position, exit_price, event.ts, exit_reason, event.symbol)

    def _close(
        self, position: Position, exit_price: float, ts: datetime, reason: ExitReason, symbol
    ) -> None:
        side = _EXIT_ORDER_SIDE[position.side]
        fill_price, fee = self.broker.fill(side, position.quantity, exit_price)
        trade = self.portfolio.close_position(symbol, fill_price, ts, fee, reason)
        self.bus.publish(
            FillEvent(
                ts=ts,
                symbol=symbol,
                strategy_id=self.strategy_id,
                order_id=f"close-{symbol.native()}-{ts.isoformat()}",
                side=side,
                quantity=position.quantity,
                price=fill_price,
                fee=fee,
                funding_cost=trade.funding,
                is_position_close=True,
                exit_reason=reason,
            )
        )

    @staticmethod
    def _snapshot_common_features(context) -> dict[str, float]:
        """Best-effort snapshot of the indicators most journal entries care about,
        for the trade journal's "all calculated features" field — independent of
        which specific ones the strategy itself queried."""
        snapshot: dict[str, float] = {}
        for key, indicator, kwargs in (
            ("ema_10", "ema", {"period": 10}),
            ("ema_50", "ema", {"period": 50}),
            ("rsi_14", "rsi", {"period": 14}),
            ("atr_14", "atr", {"period": 14}),
            ("adx_14", "adx", {"period": 14}),
        ):
            try:
                snapshot[key] = context.features.get(indicator, **kwargs)
            except InsufficientDataError:
                continue
        return snapshot

    @staticmethod
    def _stop_hit(position: Position, event: CandleEvent) -> bool:
        # Only called after the caller has already checked position.stop_loss is not None.
        assert position.stop_loss is not None
        if position.side == PositionSide.LONG:
            return event.low <= position.stop_loss
        return event.high >= position.stop_loss

    @staticmethod
    def _take_profit_hit(position: Position, event: CandleEvent) -> bool:
        assert position.take_profit is not None
        if position.side == PositionSide.LONG:
            return event.high >= position.take_profit
        return event.low <= position.take_profit

    @staticmethod
    def _exit_price(position: Position, event: CandleEvent, reason: ExitReason) -> float:
        if reason == ExitReason.STOP_LOSS:
            assert position.stop_loss is not None
            return position.stop_loss
        if reason == ExitReason.TAKE_PROFIT:
            assert position.take_profit is not None
            return position.take_profit
        return event.close

    def _force_close_at_end(self) -> None:
        symbol = self.feed.symbol
        position = self.portfolio.get_position(symbol)
        if position is None or self.feed.candles.empty:
            return
        last_row = self.feed.candles.iloc[-1]
        self._close(
            position,
            float(last_row["close"]),
            self.feed.candles.index[-1].to_pydatetime(),
            ExitReason.END_OF_BACKTEST,
            symbol,
        )
