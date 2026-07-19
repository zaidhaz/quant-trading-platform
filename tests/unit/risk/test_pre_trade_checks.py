from risk.limits import RiskLimits
from risk.pre_trade_checks import evaluate


def test_approves_when_within_all_limits() -> None:
    decision = evaluate(
        quantity=1.0, entry_price=100.0, stop_loss=95.0, equity=100_000.0, limits=RiskLimits()
    )
    assert decision.approved
    assert decision.quantity == 1.0


def test_rejects_non_positive_quantity() -> None:
    decision = evaluate(
        quantity=0.0, entry_price=100.0, stop_loss=95.0, equity=100_000.0, limits=RiskLimits()
    )
    assert not decision.approved
    assert decision.quantity == 0.0


def test_rejects_when_notional_exceeds_max() -> None:
    limits = RiskLimits(max_position_notional=500.0)
    decision = evaluate(
        quantity=10.0, entry_price=100.0, stop_loss=95.0, equity=100_000.0, limits=limits
    )
    assert not decision.approved
    assert "max_position_notional" in decision.reason


def test_rejects_when_leverage_exceeds_max() -> None:
    limits = RiskLimits(max_leverage=2.0)
    decision = evaluate(
        quantity=100.0, entry_price=100.0, stop_loss=95.0, equity=1_000.0, limits=limits
    )
    assert not decision.approved
    assert "leverage" in decision.reason


def test_scales_down_quantity_when_risk_per_trade_exceeded() -> None:
    limits = RiskLimits(max_risk_per_trade_pct=0.01)
    # stop distance 5, quantity 100 -> risk = 500 = 5% of 10,000 equity, way over 1% cap.
    decision = evaluate(
        quantity=100.0, entry_price=100.0, stop_loss=95.0, equity=10_000.0, limits=limits
    )

    assert decision.approved
    assert decision.quantity < 100.0
    implied_risk = abs(100.0 - 95.0) * decision.quantity
    assert implied_risk == 100.0  # 1% of 10,000


def test_no_stop_loss_skips_risk_per_trade_scaling() -> None:
    decision = evaluate(
        quantity=1.0, entry_price=100.0, stop_loss=None, equity=100_000.0, limits=RiskLimits()
    )
    assert decision.approved
    assert decision.quantity == 1.0
