"""Unit tests for the pre-registered scientific decision rule
(`research/conclusion.py`) — the mechanism that gates the mandated binary
"supported"/"not supported" sentence strictly on real data, and computes it
mechanically (no post-hoc threshold tweaking) from the four pre-registered
checks."""

from __future__ import annotations

from research import conclusion as conc


def _passing_inputs(symbols=("BTCUSDT",)):
    return (
        {s: 1.5 for s in symbols},  # sharpe
        {s: 0.05 for s in symbols},  # monte carlo 5th percentile
        {s: 0.75 for s in symbols},  # rolling positive fraction
        {s: 0.10 for s in symbols},  # fragile fraction
    )


class TestEvaluate:
    def test_all_checks_passing_yields_supported(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.supported is True
        assert verdict.per_symbol["BTCUSDT"].all_pass is True

    def test_negative_sharpe_fails_that_symbol_and_overall(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        sharpe["BTCUSDT"] = -0.2

        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.supported is False
        assert verdict.per_symbol["BTCUSDT"].sharpe_pass is False
        assert verdict.per_symbol["BTCUSDT"].all_pass is False

    def test_negative_monte_carlo_5th_percentile_fails(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        mc5["BTCUSDT"] = -0.01

        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.supported is False
        assert verdict.per_symbol["BTCUSDT"].monte_carlo_pass is False

    def test_rolling_fraction_at_or_below_half_fails(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        rolling["BTCUSDT"] = 0.5  # strictly greater than 0.5 required

        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.per_symbol["BTCUSDT"].rolling_pass is False
        assert verdict.supported is False

    def test_fragile_fraction_at_or_above_threshold_fails(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        fragile["BTCUSDT"] = 0.30  # strictly less than 0.30 required

        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.per_symbol["BTCUSDT"].robustness_pass is False
        assert verdict.supported is False

    def test_one_symbol_failing_fails_the_overall_verdict_even_if_other_passes(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs(("BTCUSDT", "ETHUSDT"))
        sharpe["ETHUSDT"] = -1.0

        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        assert verdict.per_symbol["BTCUSDT"].all_pass is True
        assert verdict.per_symbol["ETHUSDT"].all_pass is False
        assert verdict.supported is False

    def test_empty_input_is_not_supported(self) -> None:
        verdict = conc.evaluate({}, {}, {}, {})
        assert verdict.supported is False
        assert verdict.per_symbol == {}


class TestFormatVerdict:
    def test_real_data_supported_emits_the_exact_mandated_sentence(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        text = conc.format_verdict(verdict, all_data_is_real=True)

        assert f"**{conc.SUPPORTED_SENTENCE}**" in text
        assert conc.NOT_SUPPORTED_SENTENCE not in text

    def test_real_data_not_supported_emits_the_exact_mandated_sentence(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        sharpe["BTCUSDT"] = -1.0
        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        text = conc.format_verdict(verdict, all_data_is_real=True)

        assert f"**{conc.NOT_SUPPORTED_SENTENCE}**" in text
        assert conc.SUPPORTED_SENTENCE not in text

    def test_synthetic_data_never_emits_the_mandated_binary_sentence(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        text = conc.format_verdict(verdict, all_data_is_real=False)

        assert conc.SUPPORTED_SENTENCE not in text
        assert conc.NOT_SUPPORTED_SENTENCE not in text
        assert "INSUFFICIENT EVIDENCE" in text
        assert "mechanical verdict" in text.lower()

    def test_synthetic_data_still_reports_the_mechanical_verdict_for_transparency(self) -> None:
        sharpe, mc5, rolling, fragile = _passing_inputs()
        verdict = conc.evaluate(sharpe, mc5, rolling, fragile)

        text = conc.format_verdict(verdict, all_data_is_real=False)

        assert "SUPPORTED" in text  # the labeled, non-binding mechanical verdict
