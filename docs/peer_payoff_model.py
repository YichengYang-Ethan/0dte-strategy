"""
the reference operator's 0DTE bot payoff model — reference baseline.

Encodes the 18 parameter observations extracted from Field research 2026-04-20
(see docs/peer_bot_extracted_specs.md), CROSS-VALIDATED with V2
empirical test 2026-04-21 on 951 trading days of 0.20Δ SPXW 0DTE
call data. See docs/validation_summary_2026_04_21.md for the full
audit.

V2 findings that shaped this model:
  - the reference operator's +300% typical win is REAL: unconditional median win at
    -40% stop is +378% on the 952-day SPXW 0DTE dataset.
  - the reference operator's -40% stop is mathematically CORRECT: PF 1.28 vs 0.97
    without stop (+32% PF improvement). Not overfit.
  - the reference operator's 70% WR is IMPOSSIBLE with +300%/-40% payoff — that would
    imply PF 17.5, which no 0DTE strategy achieves live. Realistic
    signal-conditional WR is 25-35%.

So the model shape is:
  - Winner size is NEARLY INVARIANT across regimes. Unconditional
    median winner at -40% stop = +378%. Regime conditioning moves
    it only modestly.
  - Regime effect is primarily on WIN RATE, not winner size.
  - Losers are effectively FIXED at -40% by the stop rule (mechanical).

This is a significant shift from the pre-V2 version of this file,
which assumed weak-trend winners collapsed to +80%. V2 data does not
support that claim.
"""

from dataclasses import dataclass, field
from typing import Literal

Regime = Literal["strong_trend", "squeeze", "chop", "weak_trend", "event_day"]
Side = Literal["win", "loss"]


@dataclass(frozen=True)
class the reference operatorPayoffModel:
    # --- Sizing (data point #2) ---
    kelly_fraction: float = 0.25                # 1/4 Kelly
    equity_fraction_max: float = 1.00           # he sizes "by position percentage"

    # --- Fill policy (data point #3, #4) ---
    entry_fill: str = "limit_at_ask"
    exit_fill: str = "limit_at_bid"
    no_fill_behavior: str = "undefined"         # data point #4 — the gap

    # --- Exit (data point #7) ---
    loss_cap: float = -0.40                     # -40% of premium, hard stop
    # V2 evidence: 89.8% of unconditional 0.20Δ trades hit this stop.
    # Loss distribution is effectively a point mass at -40%.

    # --- Payoff: winner size (data point #8 + V2 empirical) ---
    # Unconditional median winner at -40% stop = +378%.
    # Signal gating primarily shifts WR, not median winner size.
    # Regime-specific winner sizes are DE-EMPHASIZED here.
    typical_win_gross: float = 3.78             # V2 median (was +300% assumed)

    # --- Payoff: win rate by regime (primary regime effect) ---
    # Unconditional WR at -40% stop = 9.7% (V2 finding)
    # Signal gating shifts this upward. the reference operator's self-report (70%) is
    # mathematically impossible with this payoff — real range is 25-35%.
    win_rate_by_regime: dict[Regime, float] = field(default_factory=lambda: {
        "strong_trend": 0.35,   # estimated top-quartile signal gating
        "squeeze":      0.40,   # the reference operator's best regime ("咔咔好几单")
        "chop":         0.25,   # modest gating effect
        "weak_trend":   0.12,   # minimal signal value; near-baseline
        "event_day":    0.30,   # ambiguous — could be high or low
    })
    # Unconditional (no signal) baseline for reference:
    unconditional_win_rate: float = 0.097      # V2 empirical (full-day hold)

    # --- Signal lift benchmarks (empirical 2026-04-21) ---
    # Unconditional hit rate of "+300% before -40% stop within 60min":
    target_hit_rate_60min: float = 0.033       # check0 empirical
    target_hit_rate_full_day: float = 0.097    # V2 empirical
    # R1-R5 signal must lift these by enough to clear BE (16.7% for full-day).
    # Required 60min lift for 20% WR: 6.1x. For 30% WR: 9.1x.

    # --- Costs (data point #11) ---
    slippage_usd_per_contract: float = 1.00
    commission_usd_open: float = 1.00
    commission_usd_close: float = 1.00

    # --- Frequency & holding (data point #13, #14) ---
    trades_per_day_range: tuple[int, int] = (3, 5)
    holding_minutes_range: tuple[int, int] = (10, 60)

    # --- Risk (data point #9) ---
    daily_loss_cap: float | None = None          # the reference operator has none
    kill_switch: None = None                     # the reference operator has none

    # --- Session (data point #17) ---
    no_trade_minutes_after_open: int = 15
    # V3 update: the reference operator's rule has NO microstructure support. Option-level
    # spread/vol in first 15 min matches core session. His rule may be
    # about GEX-primitive stability, not option quote stability.

    # --- Regime behaviors (data point #18) ---
    squeeze_stacking: bool = True
    squeeze_extended_holding: bool = True

    # --- Universe (data point #15, #16) ---
    universe: tuple[str, ...] = ("SPX", "SPY", "QQQ", "NVDA", "TSLA", "MRVL")
    concurrent_positions: bool = True

    # --- Typical contract premium (inference, see specs doc) ---
    premium_usd_estimate: float = 10.00

    @property
    def cost_per_round_trip(self) -> float:
        return (self.slippage_usd_per_contract
                + self.commission_usd_open
                + self.commission_usd_close)

    def net_payoff_pct(self, side: Side) -> float:
        """Net return as % of premium invested, after slippage+commission.

        Winner / loser sizes are now regime-independent (V2 finding).
        """
        gross_pct = self.typical_win_gross if side == "win" else self.loss_cap
        gross_usd = gross_pct * self.premium_usd_estimate
        net_usd = gross_usd - self.cost_per_round_trip
        return net_usd / self.premium_usd_estimate

    def break_even_win_rate(self) -> float:
        """Minimum WR needed to break even, net of costs.

        Regime-independent now that winner/loser sizes are fixed.
        """
        w = self.net_payoff_pct("win")
        l = abs(self.net_payoff_pct("loss"))
        return l / (l + w)

    def profit_factor(self, regime: Regime) -> float:
        """PF given this regime's expected WR."""
        wr = self.win_rate_by_regime[regime]
        w = self.net_payoff_pct("win")
        l = abs(self.net_payoff_pct("loss"))
        num = wr * w
        den = (1 - wr) * l
        return num / den if den > 0 else float("inf")

    def expected_value_per_trade(self, regime: Regime) -> float:
        """EV as % of premium, given regime WR."""
        wr = self.win_rate_by_regime[regime]
        w = self.net_payoff_pct("win")
        l = self.net_payoff_pct("loss")
        return wr * w + (1 - wr) * l

    def signal_lift_required(self, desired_wr: float,
                              window: str = "60min") -> float:
        """Multiplicative lift over unconditional hit-rate our signal must
        deliver to reach desired_wr in the given holding window.

        Examples:
          R0.signal_lift_required(0.20, "60min") → 6.06x
          R0.signal_lift_required(0.30, "full_day") → 3.09x

        Use this as the quantitative R1-R5 bar: if our current primitives
        cannot lift the unconditional 3.3% / 9.7% baseline by at least
        this factor on out-of-sample data, R3 engineering is not worth
        the cost.
        """
        baseline = (self.target_hit_rate_60min if window == "60min"
                    else self.target_hit_rate_full_day)
        return desired_wr / baseline


# ---------------------------------------------------------------------------
# The benchmark: this is what our R3-R5 system has to beat.
# ---------------------------------------------------------------------------

R0 = the reference operatorPayoffModel()


def summary_table() -> str:
    """Summary showing BE WR (regime-independent) and regime PF."""
    lines = [
        f"Break-even WR (regime-independent): "
        f"{R0.break_even_win_rate() * 100:.1f}%",
        f"Net win:  +{R0.net_payoff_pct('win') * 100:.1f}%",
        f"Net loss: {R0.net_payoff_pct('loss') * 100:.1f}%",
        f"Unconditional WR (V2): {R0.unconditional_win_rate * 100:.1f}%",
        "",
        f"{'Regime':<15} {'Assumed WR':>10} {'Expected PF':>12} {'EV %':>8}",
        "-" * 48,
    ]
    for regime in ("strong_trend", "squeeze", "chop", "weak_trend", "event_day"):
        wr = R0.win_rate_by_regime[regime]
        pf = R0.profit_factor(regime)
        ev = R0.expected_value_per_trade(regime) * 100
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        lines.append(f"{regime:<15} {wr*100:>9.0f}% {pf_str:>12} {ev:>7.1f}%")
    return "\n".join(lines)


if __name__ == "__main__":
    print("the reference operator 0DTE bot — reference payoff (V2-calibrated 2026-04-21)")
    print()
    print(summary_table())
    print()
    print("V2 empirical baseline on 951 days of unconditional 0.20Δ calls:")
    print(f"  WR = {R0.unconditional_win_rate*100:.1f}%  PF = 1.28  "
          f"median_win = +378%  median_loss = -40%")
    print()
    print("the reference operator's 70% self-reported WR is mathematically impossible with")
    print(f"  +378%/-40% payoff (would imply PF = 17.5). Realistic signal-")
    print(f"  conditional WR is 25-40% depending on regime.")
    print()
    print("Kill-switch question:  the reference operator has none. Our R3 must add "
          "adaptive-Kelly downgrade.")
    print("No-fill question:      the reference operator undefined. Our R3 must add exit "
          "state machine with timeout + market fallback.")
    print("Weak-trend question:   V4 FALSIFIED the 30-min open-range "
          "prospective classifier (precision 34% < 55%). Regime gating "
          "is harder than claimed in strategy_delta_vs_peer.md §5.")
