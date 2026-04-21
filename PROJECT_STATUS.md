# Project Status — 2026-04-19

## Current State: **1DTE research archived, pivoting to 0DTE**

After ~10 days of research + overnight iteration + two rounds of GPT Pro review, this branch (`feature/v5-real-greeks`) contains the complete state of the 1DTE swing strategy investigation. The **1DTE approach is being archived** and the project is pivoting to **intraday 0DTE** (see rationale below).

## What was built (1DTE swing — archived)

- **Data pipeline**: 825 days of SPY option chain (2023-01-03 → 2026-04-17), enriched with Theta Data Standard Greeks + IV + spot
- **Backtest engine**: EOD → next-EOD swing mode with 4 signal-mode multiplexer (gex / mr / gex_or_mr / gex_and_mr)
- **Signal generator**: v5 rule — `if NEGATIVE_GAMMA and position_in_range < 0.15 → buy 0.70Δ 1DTE call`
- **Fill simulator**: mid + 35% spread with time-of-day widening + theta decay
- **Validation**: 4-tier OOS (ORIG_IS / ORIG_OOS / EXT_OOS / Y2023) + bootstrap PF CIs
- **Paper trade logger**: daily signal → entry → fill cycle, ready for IB paper

## Key findings (1DTE)

1. **v5 signal fails Y2023 as a long-call trade** (PF 0.78) — all signal modes fail in 2023
2. **v11 regime-switch combo** (short straddle in low-vol + v5 long-call in high-vol) marginally passes all 4 OOS buckets
3. **Instrument sanity check** (GPT Pro Day 4 task) found that the v5 signal **does predict next-day SPY spot return**:
   - SPOT 100-share: PF 1.67 (all 825d), Y2023 PF **1.17** ✅
   - 0.70Δ call: PF 1.25, Y2023 PF 0.78 ❌
   - ATM+$5 spread: PF 1.06, Y2023 PF 0.70 ❌
4. Conclusion: v5 signal has marginal delta-one edge; the long-call wrapper eats ~41% of it (after delta-adjustment); the +$5 spread eats ~95%

## Why 1DTE is being archived

### Mechanism half-debunked
The original Baltussen et al. (JFE 2021) "hedging demand intraday momentum" thesis is partially overturned by Adams/Fontaine/Ornthanalai (SSRN 4881008, 2024 Fed paper): MMs actually MATCH 0DTE flow in 2024-26; net dealer gamma carry ≈ 0; "dealers short gamma → pinning" is largely retail folklore post-2023. This matches v5's Y2023 failure exactly.

### Time-scale mismatch
EOD snapshot data used to predict mechanisms that are fundamentally intraday (dealer rebalancing, flow bursts, IV shocks). The signal survives in spot only as a weak conditional drift, not as a clean gamma-mechanism edge.

### Overnight gap risk
1DTE swing holds 16 hours across the overnight gap, exposing the position to news, earnings, geopolitical events — risks that cannot be hedged from EOD data alone.

### Payoff geometry suboptimal
1DTE long calls require spot to cross the strike meaningfully to overcome theta + IV decay. The per-trade payoff is roughly symmetric with modest expectancy. True 0DTE with convex payoff (70% WR / +100-1500% wins / −40% losses) has better fundamental expectancy if the signal captures actual intraday mechanism.

## GPT Pro Round 1–3 summary

- `GPT_PRO_REVIEW_REQUEST.md`: initial brief (rejected OI-delta proxy, ranked variants A/B/C)
- `GPT_PRO_VERDICT.md`: Round 1 verdict (instrument > feature problem, 10 blind spots)
- `GPT_PRO_FOLLOWUP.md`: instrument sanity check results
- `GPT_PRO_ROUND3.md`: 12 new facts from the reference operator's full chat history + 3 paths

Round 3 recommended D: ship Path A + start intraday recorder. User overruled: logic of 0DTE (MM-active-push + 0DTE gamma explosion + no overnight risk) is cleaner than 1DTE, and the friend's (the reference operator's) framework is coherent enough to warrant direct engineering rather than parallel validation.

## Artifacts preserved for potential future reference

- `src/backtest/engine.py` — swing_1dte mode
- `src/gex/calculator.py` — GEX + VEX formulas (still valid for intraday)
- `src/gex/greeks.py` — BSM Vanna/Charm (Theta Standard Greeks preferred for intraday)
- `src/signal/generator.py` — v5 rule
- `scripts/validate_v5.py`, `validate_4tier.py`, `bootstrap_pf.py` — validation harness
- `scripts/test_regime_switch.py` — v11 combo
- `scripts/instrument_sanity_check.py` — the breakthrough diagnostic
- `scripts/paper_trade.py` — daily runner (will be adapted for 0DTE)
- `data/historical/spy/*.parquet` — 825 days of v2-enriched data (still useful for EOD context in 0DTE backtests)
- `DAILY_LOG.md` — full overnight iteration narrative

## Next phase: 0DTE intraday bot (separate scope)

See `ROADMAP_0DTE.md` (to be created) for the new project plan.

## Commit strategy

Merge `feature/v5-real-greeks` into `main` with a tag like `v1-1dte-archive` before pivoting. Future 0DTE work will start a new branch (`feature/0dte-intraday`) from that tag.
