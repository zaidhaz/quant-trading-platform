"""Event-driven backtesting engine.

Drives the exact same `strategies` + `risk` + `portfolio` code used live, with
`BrokerSimulator` standing in for a live `execution` adapter behind conceptually the
same fill-producing role. Realistic costs: trading fees, funding, and configurable
slippage are all applied to every fill.

Execution timing (see docs/VALIDATION_REPORT.md for the full audit finding this
fixed): a strategy's entry/exit *decision* is made using a bar's close (fully known
at that point), but the resulting order is not filled until the *next* bar's open —
mirroring the real-world delay between "the candle just closed" and "the order is
actually live in the market." Filling at the same close used to generate the signal
is a well-known source of optimistic backtest bias. Stop-loss/take-profit exits are
the one exception: they're checked against the *current* bar's high/low using a
level that was fixed *before* the bar started, so no such delay applies — that is
a real, immediately-actionable protective order, not a new decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from backtesting.broker_simulator import BacktestCosts, BrokerSimulator
from backtesting.data_feed import DataFeed
from backtesting.event_simulator import EventSimulator
from backtesting.slippage_models import FixedBpsSlippage, SlippageModel
from core.enums import ExitReason, OrderSide, PositionSide, SignalDirection
from core.event_bus import EventBus
from core.events import CandleEvent, FillEvent, RiskRejectedEvent, SignalEvent
from core.exceptions import InsufficientDataError
from core.types import Position, Symbol
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
    slippage_bps: float = 2.0  # ignored if `slippage_model` is set
    slippage_model: SlippageModel | None = None  # overrides slippage_bps's FixedBpsSlippage
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
    ruined: bool = False


@dataclass(slots=True)
class _PendingOrder:
    """A decision made on bar i's close, to be executed at bar i+1's open."""

    kind: str  # "open" | "close"
    order_side: OrderSide
    quantity: float
    correlation_id: str
    position_side: PositionSide | None = None  # open only
    stop_loss: float | None = None  # open only
    take_profit: float | None = None  # open only
    exit_reason: ExitReason | None = None  # close only


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
        slippage = self.config.slippage_model or FixedBpsSlippage(self.config.slippage_bps)
        self.broker = BrokerSimulator(BacktestCosts(self.config.taker_fee_rate, slippage))
        self.regime_df = market_state.compute(
            feed.candles, self.features, feed.symbol, feed.timeframe
        )
        self.signals: list[SignalEvent] = []
        self._pending_order: _PendingOrder | None = None
        self.ruined = False

        self.bus.subscribe(CandleEvent, self._on_candle)

    def run(self) -> BacktestResult:
        EventSimulator(self.bus).run(self.feed)
        self._pending_order = None  # a decision on the last bar has no "next bar" to fill at
        if not self.ruined:
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
            ruined=self.ruined,
        )

    def _on_candle(self, event: CandleEvent) -> None:
        if self.ruined or event.bar_index < self.config.warmup_bars:
            return

        symbol = self.feed.symbol

        # 1. Execute whatever was decided on the previous bar, at THIS bar's open.
        if self._pending_order is not None:
            self._execute_pending_order(event)

        mark_price = event.close
        position = self.portfolio.get_position(symbol)

        # 2. Funding accrual on a position that's open going into this bar.
        funding_rate_now = self.feed.funding_events.iloc[event.bar_index]
        if position is not None and not pd.isna(funding_rate_now):
            self.portfolio.apply_funding(symbol, mark_price, float(funding_rate_now))
            position = self.portfolio.get_position(symbol)

        # Strategy-facing funding is the forward-filled "currently in effect" rate
        # (`feed.funding_rate`), not `funding_events` above -- that sparse series
        # only exists to tell the engine *when* to actually charge funding, and is
        # NaN on all but the exact ~1-in-8-hours funding bars, which would make
        # per-trade funding-rate instrumentation nearly always empty.
        funding_rate_effective = self.feed.funding_rate.iloc[event.bar_index]
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
            funding_rate=(
                None if pd.isna(funding_rate_effective) else float(funding_rate_effective)
            ),
        )

        # 3. Same-bar protective exits (stop/take-profit), or queue a new decision
        #    (entry / strategy-driven exit) for execution next bar.
        if position is not None:
            self._evaluate_exit(context, position, event)
        else:
            self._evaluate_entry(context, event)

        # 4. Record equity; a non-positive balance halts the simulation (see
        #    docs/VALIDATION_REPORT.md — no liquidation/margin-call mechanic exists,
        #    so we stop rather than let equity go arbitrarily negative).
        recorded_equity = self.portfolio.record_equity(event.ts, {symbol.canonical: mark_price})
        if recorded_equity <= 0:
            self._handle_ruin(event)

    # ---- entries -----------------------------------------------------------

    def _evaluate_entry(self, context, event: CandleEvent) -> None:
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
            # `setup.metadata` lets a strategy contribute its own instrumentation
            # (e.g. Liquidity Exhaustion Reversal's sweep/displacement/absorption
            # features, see docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §6) on
            # top of the small fixed set every strategy gets for free. Strategy
            # keys win on collision (more specific than the generic snapshot).
            features_snapshot={**self._snapshot_common_features(context), **setup.metadata},
        )
        self.signals.append(signal_event)
        self.bus.publish(signal_event)

        if not self._stop_take_profit_are_sane(
            setup.direction, setup.reference_price, stop_loss, take_profit
        ):
            self.bus.publish(
                RiskRejectedEvent(
                    ts=event.ts,
                    symbol=event.symbol,
                    strategy_id=self.strategy_id,
                    signal_id=signal_event.event_id,
                    reason=(
                        f"stop_loss={stop_loss} / take_profit={take_profit} invalid for a "
                        f"{setup.direction.value} entry at {setup.reference_price} — "
                        "rejected rather than opening a nonsensical position"
                    ),
                    correlation_id=signal_event.correlation_id,
                )
            )
            return

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

        self._pending_order = _PendingOrder(
            kind="open",
            order_side=_ENTRY_ORDER_SIDE[setup.direction],
            quantity=decision.quantity,
            correlation_id=signal_event.event_id,
            position_side=_DIRECTION_TO_SIDE[setup.direction],
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def _stop_take_profit_are_sane(
        direction: SignalDirection,
        entry_price: float,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> bool:
        """A stop/target on the wrong side of entry is a strategy bug (e.g. a sign
        error in an ATR offset) that would otherwise silently produce a position
        that "stops out" the instant it opens, or a target that can never pay out.
        Reject rather than execute it."""
        if direction == SignalDirection.LONG:
            if stop_loss is not None and stop_loss >= entry_price:
                return False
            if take_profit is not None and take_profit <= entry_price:
                return False
        else:
            if stop_loss is not None and stop_loss <= entry_price:
                return False
            if take_profit is not None and take_profit >= entry_price:
                return False
        return True

    # ---- exits ---------------------------------------------------------------

    def _evaluate_exit(self, context, position: Position, event: CandleEvent) -> None:
        # Stop-loss and take-profit both use levels fixed before this bar started,
        # so they're checked (and filled) intrabar, same-bar. Stop is checked first:
        # a bar that breaches both is conservatively assumed to have hit the stop
        # first. A strategy-driven exit is a *new* decision made from this bar's
        # close, so — consistent with entries — it's deferred to next bar's open.
        stop_fill = self._resolve_stop_loss(position, event)
        if stop_fill is not None:
            self._close_same_bar(position, stop_fill, event, ExitReason.STOP_LOSS)
            return
        take_profit_fill = self._resolve_take_profit(position, event)
        if take_profit_fill is not None:
            self._close_same_bar(position, take_profit_fill, event, ExitReason.TAKE_PROFIT)
            return
        if self.strategy.check_exit(context, position):
            self._pending_order = _PendingOrder(
                kind="close",
                order_side=_EXIT_ORDER_SIDE[position.side],
                quantity=position.quantity,
                correlation_id=f"exit-{event.symbol.native()}-{event.ts.isoformat()}",
                exit_reason=ExitReason.STRATEGY_EXIT,
            )

    def _close_same_bar(
        self, position: Position, exit_price: float, event: CandleEvent, reason: ExitReason
    ) -> None:
        self._close(
            position,
            exit_price,
            event.ts,
            reason,
            event.symbol,
            bar_volume=event.volume,
            bar_low=event.low,
            bar_high=event.high,
        )

    def _close(
        self,
        position: Position,
        exit_price: float,
        ts: datetime,
        reason: ExitReason,
        symbol: Symbol,
        bar_volume: float = 0.0,
        bar_low: float | None = None,
        bar_high: float | None = None,
    ) -> None:
        side = _EXIT_ORDER_SIDE[position.side]
        fill_price, fee = self.broker.fill(
            side,
            position.quantity,
            exit_price,
            bar_volume=bar_volume,
            bar_low=bar_low,
            bar_high=bar_high,
        )
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

    def _execute_pending_order(self, event: CandleEvent) -> None:
        order = self._pending_order
        self._pending_order = None
        if order is None:
            return
        symbol = event.symbol

        if order.kind == "open":
            assert order.position_side is not None  # always set by _evaluate_entry for "open"
            fill_price, fee = self.broker.fill(
                order.order_side,
                order.quantity,
                event.open,
                bar_volume=event.volume,
                bar_low=event.low,
                bar_high=event.high,
            )
            self.portfolio.open_position(
                symbol,
                order.position_side,
                fill_price,
                order.quantity,
                event.ts,
                order.stop_loss,
                order.take_profit,
                entry_fee=fee,
            )
            self.bus.publish(
                FillEvent(
                    ts=event.ts,
                    symbol=symbol,
                    strategy_id=self.strategy_id,
                    order_id=order.correlation_id,
                    side=order.order_side,
                    quantity=order.quantity,
                    price=fill_price,
                    fee=fee,
                    is_position_open=True,
                    correlation_id=order.correlation_id,
                )
            )
        else:
            position = self.portfolio.get_position(symbol)
            if position is None:
                return  # defensive: shouldn't happen, but never fill a close with nothing open
            fill_price, fee = self.broker.fill(
                order.order_side,
                order.quantity,
                event.open,
                bar_volume=event.volume,
                bar_low=event.low,
                bar_high=event.high,
            )
            trade = self.portfolio.close_position(
                symbol, fill_price, event.ts, fee, order.exit_reason or ExitReason.STRATEGY_EXIT
            )
            self.bus.publish(
                FillEvent(
                    ts=event.ts,
                    symbol=symbol,
                    strategy_id=self.strategy_id,
                    order_id=order.correlation_id,
                    side=order.order_side,
                    quantity=order.quantity,
                    price=fill_price,
                    fee=fee,
                    funding_cost=trade.funding,
                    is_position_close=True,
                    exit_reason=order.exit_reason,
                    correlation_id=order.correlation_id,
                )
            )

    # ---- stop/take-profit resolution (with gap-through handling) -------------

    @staticmethod
    def _resolve_stop_loss(position: Position, event: CandleEvent) -> float | None:
        """None if not triggered this bar. Otherwise the fill price — a stop can't
        fill better than the bar's open if the market already gapped past it before
        the bar started trading (a stop order never guarantees its exact price)."""
        stop = position.stop_loss
        if stop is None:
            return None
        if position.side == PositionSide.LONG:
            if event.open <= stop:
                return event.open
            if event.low <= stop:
                return stop
        else:
            if event.open >= stop:
                return event.open
            if event.high >= stop:
                return stop
        return None

    @staticmethod
    def _resolve_take_profit(position: Position, event: CandleEvent) -> float | None:
        """None if not triggered this bar. Modeled as a limit order: a favorable gap
        fills at the (better) open rather than being capped at the target level,
        since a limit order guarantees at least its price, often better on a gap."""
        target = position.take_profit
        if target is None:
            return None
        if position.side == PositionSide.LONG:
            if event.open >= target:
                return event.open
            if event.high >= target:
                return target
        else:
            if event.open <= target:
                return event.open
            if event.low <= target:
                return target
        return None

    # ---- misc ------------------------------------------------------------------

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

    def _handle_ruin(self, event: CandleEvent) -> None:
        self.ruined = True
        self._pending_order = None
        symbol = self.feed.symbol
        position = self.portfolio.get_position(symbol)
        if position is not None:
            self._close_same_bar(position, event.close, event, ExitReason.RUIN)
            self._sync_last_equity_point_to_realized_cash()

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
            bar_volume=float(last_row["volume"]),
            bar_low=float(last_row["low"]),
            bar_high=float(last_row["high"]),
        )
        self._sync_last_equity_point_to_realized_cash()

    def _sync_last_equity_point_to_realized_cash(self) -> None:
        """`record_equity()` for the bar a forced close happens on runs *before*
        that close (it's step 4 of `_on_candle`; the close itself is a followup
        action, not a new bar) — so without this, `equity_curve[-1]` would still
        show the pre-close *unrealized* mark-to-market value, silently
        inconsistent with the fee/slippage-adjusted trade that's actually in
        `closed_trades`. An external comparison against Backtrader surfaced this:
        Backtrader's `getvalue()` never force-closes, so it's a pure mark-to-market
        number — the two are only comparable once this engine's own reported
        numbers are internally consistent with each other. See
        docs/BACKTRADER_COMPARISON.md."""
        curve = self.portfolio.equity_curve
        if curve:
            ts, _ = curve[-1]
            curve[-1] = (ts, self.portfolio.cash)
