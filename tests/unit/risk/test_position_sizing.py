from risk.position_sizing import confidence_scaled, fixed_fractional, volatility_target


def test_fixed_fractional_risks_exact_fraction_of_equity() -> None:
    qty = fixed_fractional(equity=10_000, entry_price=100, stop_price=95, risk_per_trade=0.01)
    # risking 1% of 10,000 = 100, stop distance = 5 -> qty = 20
    assert qty == 20.0


def test_fixed_fractional_zero_when_equity_non_positive() -> None:
    assert fixed_fractional(equity=0, entry_price=100, stop_price=95, risk_per_trade=0.01) == 0.0


def test_fixed_fractional_zero_when_stop_equals_entry() -> None:
    assert (
        fixed_fractional(equity=10_000, entry_price=100, stop_price=100, risk_per_trade=0.01) == 0.0
    )


def test_volatility_target_scales_inversely_with_atr() -> None:
    tight = volatility_target(equity=10_000, atr=1.0, risk_per_trade=0.01, atr_mult=2.0)
    wide = volatility_target(equity=10_000, atr=5.0, risk_per_trade=0.01, atr_mult=2.0)
    assert tight > wide


def test_confidence_scaled_full_size_at_max_confidence() -> None:
    assert confidence_scaled(base_quantity=10.0, confidence=100.0) == 10.0


def test_confidence_scaled_floor_applies_at_zero_confidence() -> None:
    assert confidence_scaled(base_quantity=10.0, confidence=0.0, floor=0.25) == 2.5


def test_confidence_scaled_never_below_floor() -> None:
    assert confidence_scaled(base_quantity=10.0, confidence=1.0, floor=0.3) == 3.0
