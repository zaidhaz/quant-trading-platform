"""Cross-validation against Backtrader (github.com/mementum/backtrader), an
established, widely-used backtesting library — run under identical data, fees,
slippage, and a simple long-only SMA-crossover benchmark strategy.

Methodology: SMA(10)/SMA(30) crossover signals are precomputed *once* with pandas
and fed as plain entry/exit decisions into both engines, rather than letting each
engine compute its own moving average. This deliberately isolates what's being
validated — order execution timing, fee/slippage application, and P&L accounting —
from indicator computation, where different libraries' EMA/SMA seeding conventions
can differ for reasons that have nothing to do with backtest correctness.

Skipped entirely if `backtrader` isn't installed — it's a validation-only dependency,
not a runtime dependency of the platform (not in pyproject.toml's `main` deps).

See docs/BACKTRADER_COMPARISON.md for the full write-up of what this found.
"""

from __future__ import annotations

import pandas as pd
import pytest

bt = pytest.importorskip("backtrader")

from backtesting.data_feed import DataFeed  # noqa: E402
from backtesting.engine import BacktestConfig, BacktestEngine  # noqa: E402
from core.enums import SignalDirection  # noqa: E402
from core.types import Position, Symbol  # noqa: E402
from risk.limits import RiskLimits  # noqa: E402
from strategies.base_strategy import Strategy  # noqa: E402
from strategies.context import StrategyContext  # noqa: E402
from strategies.signal import Setup  # noqa: E402
from tests.fixtures.synthetic import make_ohlcv  # noqa: E402

SYMBOL = Symbol(base="BTC", quote="USDT")
INITIAL_CAPITAL = 100_000.0
FEE_RATE = 0.001  # 10 bps
SLIPPAGE_BPS = 5.0
QTY = 1.0
FAST, SLOW = 10, 30


def build_dataset(n: int = 500, seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    df = make_ohlcv(n, drift=0.0008, volatility=0.006, seed=seed, start="2024-01-01", freq="1h")
    fast = df["close"].rolling(FAST).mean()
    slow = df["close"].rolling(SLOW).mean()
    prev_fast, prev_slow = fast.shift(1), slow.shift(1)
    golden = (prev_fast <= prev_slow) & (fast > slow)
    death = (prev_fast >= prev_slow) & (fast < slow)
    signal = pd.Series(0, index=df.index)
    signal[golden] = 1
    signal[death] = -1
    return df, signal


class _SignalDrivenStrategy(Strategy):
    """Consumes precomputed signals rather than calling context.features — see
    module docstring for why."""

    def __init__(self, signal: pd.Series, qty: float = QTY) -> None:
        super().__init__()
        self._signal = signal.to_numpy()
        self._qty = qty

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        if self._signal[context.index] == 1:
            return Setup(
                direction=SignalDirection.LONG,
                reference_price=context.price,
                reasoning="sma_golden_cross",
            )
        return None

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        return True

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        return bool(self._signal[context.index] == -1)

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        return None

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        return None

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        return self._qty

    def confidence(self, context: StrategyContext, setup: Setup) -> float:
        return 100.0


def run_my_engine(df: pd.DataFrame, signal: pd.Series) -> tuple[float, list[dict]]:
    feed = DataFeed.from_candles(SYMBOL, "1h", df, None)
    config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        taker_fee_rate=FEE_RATE,
        slippage_bps=SLIPPAGE_BPS,
        risk_limits=RiskLimits(),
    )
    result = BacktestEngine(_SignalDrivenStrategy(signal), feed, config).run()
    trades = [
        {
            "entry_ts": t.entry_ts,
            "entry_price": t.entry_price,
            "exit_ts": t.exit_ts,
            "exit_price": t.exit_price,
            "net_pnl": t.net_pnl,
            "fees": t.fees,
        }
        for t in result.closed_trades
    ]
    return result.final_equity, trades


class _SignalCrossoverBT(bt.Strategy):  # type: ignore[misc]
    params = (("signal_by_ts", None), ("qty", QTY))

    def __init__(self) -> None:
        self.fills: list[dict] = []

    def next(self) -> None:
        ts = pd.Timestamp(self.datas[0].datetime.datetime(0), tz="UTC")
        sig = self.p.signal_by_ts.get(ts, 0)
        if not self.position:
            if sig == 1:
                self.buy(size=self.p.qty)
        elif sig == -1:
            self.close()

    def notify_order(self, order: object) -> None:
        if order.status == order.Completed:  # type: ignore[attr-defined]
            self.fills.append(
                {
                    "side": "BUY" if order.isbuy() else "SELL",  # type: ignore[attr-defined]
                    "dt": pd.Timestamp(bt.num2date(order.executed.dt), tz="UTC"),  # type: ignore[attr-defined]
                    "price": order.executed.price,  # type: ignore[attr-defined]
                    "qty": abs(order.executed.size),  # type: ignore[attr-defined]
                    "comm": order.executed.comm,  # type: ignore[attr-defined]
                }
            )


def run_backtrader(df: pd.DataFrame, signal: pd.Series) -> tuple[float, list[dict]]:
    signal_by_ts = {pd.Timestamp(ts): int(v) for ts, v in signal.items()}
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(_SignalCrossoverBT, signal_by_ts=signal_by_ts, qty=QTY)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=FEE_RATE)
    cerebro.broker.set_slippage_perc(perc=SLIPPAGE_BPS / 10_000, slip_open=True)
    strat = cerebro.run()[0]
    final_equity = cerebro.broker.getvalue()

    fills = strat.fills
    trades = []
    for i in range(0, len(fills) - 1, 2):
        entry, exit_ = fills[i], fills[i + 1]
        gross = (exit_["price"] - entry["price"]) * entry["qty"]
        net = gross - entry["comm"] - exit_["comm"]
        trades.append(
            {
                "entry_ts": entry["dt"],
                "entry_price": entry["price"],
                "exit_ts": exit_["dt"],
                "exit_price": exit_["price"],
                "net_pnl": net,
                "fees": entry["comm"] + exit_["comm"],
            }
        )
    return final_equity, trades


@pytest.mark.parametrize("seed", [7, 1, 42, 123])
def test_matches_backtrader_on_every_completed_round_trip(seed: int) -> None:
    df, signal = build_dataset(seed=seed)

    my_equity, my_trades = run_my_engine(df, signal)
    bt_equity, bt_trades = run_backtrader(df, signal)

    # Backtrader's benchmark strategy in this comparison never force-closes a
    # still-open position at the end of data (my engine deliberately does — see
    # docs/BACKTRADER_COMPARISON.md) — so my engine may have exactly one more
    # closed trade than Backtrader when the data ends mid-position.
    assert len(my_trades) - len(bt_trades) in (0, 1)

    # Every trade both engines actually completed as a round trip must match to
    # float precision — this is the core claim being validated.
    for mine, theirs in zip(my_trades, bt_trades, strict=False):
        assert mine["entry_ts"] == theirs["entry_ts"]
        assert mine["exit_ts"] == theirs["exit_ts"]
        assert mine["entry_price"] == pytest.approx(theirs["entry_price"], abs=1e-6)
        assert mine["exit_price"] == pytest.approx(theirs["exit_price"], abs=1e-6)
        assert mine["net_pnl"] == pytest.approx(theirs["net_pnl"], abs=1e-6)

    if len(my_trades) == len(bt_trades):
        # No dangling position at the end -> equities must match exactly.
        assert my_equity == pytest.approx(bt_equity, abs=1e-6)
    else:
        # A dangling position was force-closed on my side only -> my engine paid
        # one extra round of fee + slippage that Backtrader's pure unrealized
        # mark-to-market (getvalue(), no force-close) never incurred. The gap must
        # be small (bounded by a couple of single-trade cost legs at these price
        # levels/position size) and in that direction — not an arbitrary residual.
        assert -2.0 < (my_equity - bt_equity) <= 1e-6
