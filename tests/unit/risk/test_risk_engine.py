from risk.limits import RiskLimits
from risk.risk_engine import RiskEngine


def test_confidence_scaling_disabled_by_default() -> None:
    engine = RiskEngine(RiskLimits())
    decision = engine.evaluate(
        suggested_quantity=10.0,
        entry_price=100.0,
        stop_loss=95.0,
        confidence=10.0,
        equity=1_000_000.0,
    )
    assert decision.quantity == 10.0


def test_confidence_scaling_reduces_low_confidence_size() -> None:
    engine = RiskEngine(RiskLimits(), use_confidence_scaling=True, confidence_floor=0.25)
    decision = engine.evaluate(
        suggested_quantity=10.0,
        entry_price=100.0,
        stop_loss=95.0,
        confidence=10.0,
        equity=1_000_000.0,
    )
    assert decision.quantity == 2.5


def test_still_enforces_hard_limits_after_confidence_scaling() -> None:
    engine = RiskEngine(RiskLimits(max_position_notional=100.0), use_confidence_scaling=True)
    decision = engine.evaluate(
        suggested_quantity=10.0,
        entry_price=100.0,
        stop_loss=95.0,
        confidence=100.0,
        equity=1_000_000.0,
    )
    assert not decision.approved
