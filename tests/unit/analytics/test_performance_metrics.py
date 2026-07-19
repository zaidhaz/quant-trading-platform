import math
from datetime import UTC, datetime, timedelta

import pytest

from analytics import performance_metrics as pm
from core.enums import ExitReason, PositionSide
from core.types import Symbol
from portfolio.position_tracker import ClosedTrade

SYMBOL = Symbol(base="BTC", quote="USDT")
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_trade(
    net_pnl: float,
    entry_price: float = 100.0,
    stop_loss: float | None = None,
    quantity: float = 1.0,
    entry_ts: datetime = T0,
    exit_ts: datetime = T0 + timedelta(hours=2),
    exit_reason: ExitReason = ExitReason.STRATEGY_EXIT,
    side: PositionSide = PositionSide.LONG,
) -> ClosedTrade:
    return ClosedTrade(
        symbol=SYMBOL,
        side=side,
        entry_price=entry_price,
        exit_price=entry_price + net_pnl,
        quantity=quantity,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        fees=0.0,
        funding=0.0,
        exit_reason=exit_reason,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        stop_loss=stop_loss,
    )


def test_net_return() -> None:
    curve = [(T0, 100.0), (T0 + timedelta(days=1), 150.0)]
    assert pm.net_return(curve) == 0.5


def test_net_return_empty_curve_is_zero() -> None:
    assert pm.net_return([]) == 0.0


def test_cagr_doubling_over_exactly_one_year() -> None:
    curve = [(T0, 100.0), (T0 + timedelta(days=365), 200.0)]
    assert pm.cagr(curve) == pytest.approx(1.0, rel=1e-3)


def test_sharpe_ratio_matches_hand_computed_value() -> None:
    curve = [
        (T0, 100.0),
        (T0 + timedelta(days=1), 110.0),
        (T0 + timedelta(days=2), 104.5),
        (T0 + timedelta(days=3), 114.95),
    ]
    # returns: 0.10, -0.05, 0.10 -> mean 0.05, sample std (ddof=1) ~= 0.0866025
    expected = (0.05 / 0.08660254037844387) * math.sqrt(365)
    assert pm.sharpe_ratio(curve, "1d") == pytest.approx(expected, rel=1e-6)


def test_sharpe_ratio_zero_when_no_variance() -> None:
    curve = [(T0, 100.0), (T0 + timedelta(days=1), 110.0), (T0 + timedelta(days=2), 121.0)]
    assert pm.sharpe_ratio(curve, "1d") == 0.0


def test_sortino_ratio_matches_hand_computed_value() -> None:
    curve = [
        (T0, 100.0),
        (T0 + timedelta(days=1), 110.0),
        (T0 + timedelta(days=2), 104.5),
        (T0 + timedelta(days=3), 114.95),
    ]
    # downside deviation = sqrt(mean([0, -0.05, 0]^2)) = sqrt(0.0025/3)
    downside_dev = math.sqrt(0.0025 / 3)
    expected = (0.05 / downside_dev) * math.sqrt(365)
    assert pm.sortino_ratio(curve, "1d") == pytest.approx(expected, rel=1e-6)


def test_max_drawdown_computed_from_peak() -> None:
    curve = [
        (T0, 100.0),
        (T0 + timedelta(days=1), 120.0),
        (T0 + timedelta(days=2), 90.0),
        (T0 + timedelta(days=3), 110.0),
    ]
    assert pm.max_drawdown(curve) == pytest.approx(0.25)


def test_profit_factor() -> None:
    trades = [make_trade(10), make_trade(-5), make_trade(20), make_trade(-10)]
    assert pm.profit_factor(trades) == pytest.approx(30 / 15)


def test_profit_factor_infinite_when_no_losses() -> None:
    trades = [make_trade(10), make_trade(5)]
    assert pm.profit_factor(trades) == float("inf")


def test_win_rate() -> None:
    trades = [make_trade(10), make_trade(-5), make_trade(20), make_trade(-10)]
    assert pm.win_rate(trades) == 0.5


def test_win_rate_empty_is_zero() -> None:
    assert pm.win_rate([]) == 0.0


def test_average_r_multiple_ignores_trades_without_stop() -> None:
    trades = [
        make_trade(10, entry_price=100, stop_loss=95),  # risk 5 -> R = 2.0
        make_trade(-5, entry_price=100, stop_loss=95),  # risk 5 -> R = -1.0
        make_trade(50, entry_price=100, stop_loss=None),  # excluded
    ]
    assert pm.average_r_multiple(trades) == pytest.approx(0.5)


def test_consecutive_wins_and_losses() -> None:
    trades = [make_trade(p) for p in (10, 20, -5, -10, -15, 30)]
    result = pm.consecutive_wins_losses(trades)
    assert result == {"max_consecutive_wins": 2, "max_consecutive_losses": 3}


def test_trade_distribution_counts_and_holding_time() -> None:
    trades = [
        make_trade(
            10,
            exit_reason=ExitReason.TAKE_PROFIT,
            side=PositionSide.LONG,
            exit_ts=T0 + timedelta(hours=1),
        ),
        make_trade(
            -5,
            exit_reason=ExitReason.STOP_LOSS,
            side=PositionSide.SHORT,
            exit_ts=T0 + timedelta(hours=3),
        ),
    ]
    dist = pm.trade_distribution(trades)
    assert dist["count"] == 2
    assert dist["by_exit_reason"] == {"take_profit": 1, "stop_loss": 1}
    assert dist["by_side"] == {"long": 1, "short": 1}
    assert dist["avg_holding_hours"] == pytest.approx(2.0)


def test_trade_distribution_empty() -> None:
    dist = pm.trade_distribution([])
    assert dist["count"] == 0


def test_monthly_returns_spans_two_months() -> None:
    curve = [
        (datetime(2024, 1, 1, tzinfo=UTC), 100.0),
        (datetime(2024, 1, 31, tzinfo=UTC), 110.0),
        (datetime(2024, 2, 28, tzinfo=UTC), 121.0),
    ]
    result = pm.monthly_returns(curve)
    assert len(result) == 1  # one pct-change between two month-end observations
    assert result.iloc[0] == pytest.approx(0.1)


def test_summarize_includes_every_required_metric() -> None:
    curve = [(T0, 100.0), (T0 + timedelta(days=1), 110.0), (T0 + timedelta(days=2), 105.0)]
    trades = [make_trade(10, stop_loss=95), make_trade(-5, stop_loss=95)]

    summary = pm.summarize(curve, trades, "1d")

    for key in (
        "net_return",
        "cagr",
        "sharpe_ratio",
        "sortino_ratio",
        "profit_factor",
        "win_rate",
        "average_r_multiple",
        "max_drawdown",
        "max_consecutive_wins",
        "max_consecutive_losses",
        "monthly_returns",
        "trade_distribution",
    ):
        assert key in summary
