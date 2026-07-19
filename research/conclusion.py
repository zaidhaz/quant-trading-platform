"""Pre-registered, objective decision rule for the mandatory scientific
conclusion.

"Pre-registered" means exactly this: the rule below is fixed in code before
it is ever evaluated against real evidence, so the verdict is computed
mechanically from the metrics, not chosen after the fact to fit a preferred
narrative. **Do not edit these thresholds after seeing a real-data result**
to make the conclusion come out differently — that would defeat the entire
point of writing it down here first, and would be exactly the kind of
post-hoc rationalization this whole research pipeline exists to avoid.

Decision rule — ALL FOUR must hold, for every symbol, for "supported":

1. Full-history Sharpe ratio (primary timeframe) > 0.
2. Monte Carlo bootstrap 5th-percentile annualized return > 0 — the edge
   must survive a bad-luck resampling of the realized trade distribution,
   not just look good on the single historical path that happened.
3. More than half of the rolling out-of-sample validation windows have
   positive net return — the edge can't be concentrated in one lucky
   historical stretch.
4. Fewer than 30% of the ±10%-perturbed robustness parameters are flagged
   fragile — the result can't be a knife-edge artifact of the exact default
   parameter values.

Any single failure on any symbol makes the overall verdict "not supported."
There is no partial credit and no "leans supported" — a pre-registered
binary rule that bends isn't one.

**The mandated unsoftened binary sentence is only ever emitted when every
symbol's data came from `source="real"`** (see `research/data_loader.py`).
On synthetic data, this module still executes the rule (to prove the
mechanism works end-to-end) but reports "INSUFFICIENT EVIDENCE" instead of
either sentence — issuing a real-sounding verdict on data known to contain
no real market structure would not be "not softening the conclusion," it
would be fabricating one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SHARPE_THRESHOLD = 0.0
MONTE_CARLO_5TH_PERCENTILE_THRESHOLD = 0.0
ROLLING_POSITIVE_FRACTION_THRESHOLD = 0.5
FRAGILE_FRACTION_THRESHOLD = 0.30

SUPPORTED_SENTENCE = "The hypothesis is supported by the available evidence."
NOT_SUPPORTED_SENTENCE = "The hypothesis is not supported by the available evidence."


@dataclass(frozen=True, slots=True)
class SymbolChecks:
    symbol: str
    sharpe: float
    sharpe_pass: bool
    monte_carlo_5th_percentile: float
    monte_carlo_pass: bool
    rolling_positive_fraction: float
    rolling_pass: bool
    fragile_fraction: float
    robustness_pass: bool

    @property
    def all_pass(self) -> bool:
        return (
            self.sharpe_pass
            and self.monte_carlo_pass
            and self.rolling_pass
            and self.robustness_pass
        )


@dataclass(frozen=True, slots=True)
class Verdict:
    supported: bool
    per_symbol: dict[str, SymbolChecks] = field(default_factory=dict)


def evaluate(
    sharpe_by_symbol: dict[str, float],
    monte_carlo_5th_percentile_by_symbol: dict[str, float],
    rolling_positive_fraction_by_symbol: dict[str, float],
    fragile_fraction_by_symbol: dict[str, float],
) -> Verdict:
    per_symbol: dict[str, SymbolChecks] = {}
    for symbol in sharpe_by_symbol:
        sharpe = sharpe_by_symbol[symbol]
        mc_5th = monte_carlo_5th_percentile_by_symbol[symbol]
        rolling_frac = rolling_positive_fraction_by_symbol[symbol]
        fragile_frac = fragile_fraction_by_symbol[symbol]
        per_symbol[symbol] = SymbolChecks(
            symbol=symbol,
            sharpe=sharpe,
            sharpe_pass=sharpe > SHARPE_THRESHOLD,
            monte_carlo_5th_percentile=mc_5th,
            monte_carlo_pass=mc_5th > MONTE_CARLO_5TH_PERCENTILE_THRESHOLD,
            rolling_positive_fraction=rolling_frac,
            rolling_pass=rolling_frac > ROLLING_POSITIVE_FRACTION_THRESHOLD,
            fragile_fraction=fragile_frac,
            robustness_pass=fragile_frac < FRAGILE_FRACTION_THRESHOLD,
        )
    supported = bool(per_symbol) and all(c.all_pass for c in per_symbol.values())
    return Verdict(supported=supported, per_symbol=per_symbol)


def format_verdict(verdict: Verdict, all_data_is_real: bool) -> str:
    lines = [
        "### Pre-registered decision rule",
        "",
        f"A symbol passes only if ALL FOUR hold: Sharpe > {SHARPE_THRESHOLD}, "
        f"Monte Carlo 5th-percentile annualized return > "
        f"{MONTE_CARLO_5TH_PERCENTILE_THRESHOLD:.0%}, more than "
        f"{ROLLING_POSITIVE_FRACTION_THRESHOLD:.0%} of rolling out-of-sample "
        f"windows positive, and fewer than {FRAGILE_FRACTION_THRESHOLD:.0%} of "
        "robustness-perturbed parameters flagged fragile.",
        "",
        "| Symbol | Sharpe | MC 5th pct return | Rolling win-window frac | "
        "Fragile frac | Pass |",
        "|---|---|---|---|---|---|",
    ]
    for c in verdict.per_symbol.values():
        lines.append(
            f"| {c.symbol} | {c.sharpe:.2f} ({'OK' if c.sharpe_pass else 'FAIL'}) | "
            f"{c.monte_carlo_5th_percentile:.2%} ({'OK' if c.monte_carlo_pass else 'FAIL'}) | "
            f"{c.rolling_positive_fraction:.0%} ({'OK' if c.rolling_pass else 'FAIL'}) | "
            f"{c.fragile_fraction:.0%} ({'OK' if c.robustness_pass else 'FAIL'}) | "
            f"{'PASS' if c.all_pass else 'FAIL'} |"
        )

    lines.append("")
    if all_data_is_real:
        sentence = SUPPORTED_SENTENCE if verdict.supported else NOT_SUPPORTED_SENTENCE
        lines.append(f"**{sentence}**")
    else:
        mechanical = "SUPPORTED" if verdict.supported else "NOT SUPPORTED"
        lines.append(
            "**INSUFFICIENT EVIDENCE — real Binance data was not available for at "
            "least one symbol in this run (see §0/§1). Per the pre-registered rule "
            f"above, the mechanical verdict on the *actual (synthetic)* inputs used "
            f"in this run would have been: {mechanical} — shown only to prove the "
            "decision-rule code runs correctly end-to-end. This is NOT a scientific "
            "conclusion about the real-world hypothesis and must not be read as "
            "one.**"
        )
    return "\n".join(lines)
