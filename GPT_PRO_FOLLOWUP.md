# Follow-up to GPT Pro — Instrument Sanity Check Results + Round 2 Questions

Thank you for the first-round review. Your Day 4 task ("instrument sanity check") was the highest-EV item on the list. I ran it and the results are genuinely surprising. I need your help interpreting them and picking the next step.

## What I tested

For every day the v5 signal fired (`NEGATIVE_GAMMA regime AND position_in_range < 0.15`), I recorded three parallel next-day P&Ls on the same signal:

- **L1 SPOT**: 100 shares SPY, close-to-close
- **L2 CALL**: 0.70Δ 1DTE long call (current production instrument)
- **L3 SPREAD**: ATM call debit spread, long ATM + short ATM+$5

Signal count: **172** (across 825 days 2023-01-03 → 2026-04-17).

## Results — this is the key table

| Bucket | L1 SPOT PF | L1 WR | L1 Sharpe | L2 CALL PF | L2 Sharpe | L3 SPREAD PF |
|--------|-----------:|------:|----------:|-----------:|----------:|-------------:|
| Y2023 | **1.17** | 44.8% | 0.97 | 0.78 | -1.59 | 0.70 |
| EXT_OOS (2024-01 → 2025-05) | **1.43** | 55.2% | 1.67 | 1.29 | 1.16 | 1.19 |
| ORIG_OOS (2025-05 → 2025-10) | **4.13** | 60.0% | 8.51 | 1.84 | 3.73 | 1.33 |
| ORIG_IS (2025-10 → 2026-04) | **2.66** | 70.4% | 5.92 | 1.67 | 3.08 | 1.40 |
| **ALL (825d)** | **1.67** | **54.7%** | **2.50** | 1.25 | 1.11 | 1.06 |

Per-trade means: **SPOT +$107**, CALL +$44, SPREAD +$6 (per 100-share / 1-contract).

One-sample t-test on SPOT per-trade return: **t = 2.06**, p ≈ 0.04 (two-sided).

## The finding, stated plainly

- The signal **does** predict next-day SPY spot direction.
- It is the **only instrument that stays positive across all 4 OOS buckets**, including Y2023.
- The long 0.70Δ 1DTE call eats roughly **60% of the spot edge** (+107 → +44 per-unit).
- The ATM+$5 debit spread eats **~95% of it** (+107 → +6).
- Y2023 specifically: spot wins (+$1,186 total), call loses (-$1,898), spread loses (-$1,715). This looks like exactly the "expensive options in trending/low-vol regime" failure mode you suggested.

## So the project redirect appears to be:

Move from *"find a better signal feature"* to *"find a better instrument to express the existing signal"*.

## Questions for this round

### Q1. Is the SPOT edge real, or am I fooling myself with multiple testing?

I have tested on this dataset roughly 8–10 variant signals, plus 3 instrument layers, plus 4 bucket slices. That's a lot of comparisons. The SPOT t=2.06 is barely past the 0.05 threshold. Under any reasonable Bonferroni / FDR correction, does this survive?

What is the right way to test this cleanly now? My thinking:
- Day-level block bootstrap on per-trade spot return for CI on PF and mean
- Compare v5-signal-days vs random-signal-days with same count, matched by bucket
- Stratify by macro-event flag (CPI/FOMC/NFP/OPEX/ex-div) to check the edge isn't concentrated on event days

Any other tests you'd require before believing the SPOT edge?

### Q2. If SPOT edge is real, what is the right instrument to express it?

Four candidates I'm considering:

**A. Direct SPOT shares**
- Pros: captures the full edge, no theta/IV drag.
- Cons: no leverage, bad capital efficiency for a 0DTE/1DTE overnight hold, PDT rules on small accounts.

**B. Delta-1 synthetic = long ATM call + short ATM put, same expiry**
- Pros: replicates spot with roughly 5–10x capital efficiency, theta ≈ neutral (long call θ and short put θ partially cancel).
- Cons: requires naked short put (high margin), early-assignment risk (SPY is American), pin risk at expiry, dividend-cost embedded in put-call parity.

**C. Small-moneyness debit call spread (e.g. ±$2 wide)**
- Pros: cheap, defined risk, captures more of the spot move than wide spreads.
- Cons: still eats theta at expiry, and the L3 ±$5 data already shows spread bleeds against the spot edge.

**D. Regime-adaptive instrument**
- If `ATM_IV < X`: use long 0.70Δ call (cheap convexity).
- If `ATM_IV >= X`: use delta-1 synthetic or spot.
- Pros: avoids expensive-option regime where long call loses.
- Cons: adds another parameter X → overfit risk.

Given the data above, which expression would you push me toward? Anything I'm missing (e.g. long SPY future as delta-1, using short put alone given bullish edge)?

### Q3. Why does the debit spread ALSO fail Y2023?

A debit spread should track spot direction more tightly than a naked call, because the long leg's delta-1 exposure is partially hedged by the short leg's negative delta. But the ±$5 spread posts Y2023 PF 0.70 despite spot PF 1.17 in the same window.

Is this because:
- ±$5 is wide enough that short leg's delta is tiny → spread behaves almost like a lone long call?
- Bid-ask spread on the short leg bleeds the debit disproportionately on 1DTE?
- The short leg's pin risk / assignment on ITM expiry adds hidden drag?

What spread width would you predict captures the spot edge without excessive theta bleed? 1-wide? ATM ± 1 standard deviation of overnight move?

### Q4. Should the paper-trade plan change?

Original Day 7 prescription: paper-trade frozen v11 until 30–50 live signals.

New evidence suggests v11's long-call instrument is specifically where the edge leaks. Should I:
1. **Paper-trade v5 on SPOT shares instead** (delta-1 expression of the proven-good signal)?
2. **Paper-trade v11 as originally planned** (honor the freeze, collect ground-truth on current production)?
3. **Paper-trade both in parallel** (2 signals per day-trigger, ~N ≈ 30–50 each)?

I'm tempted by option 3 because I can run both on the same signal stream essentially for free, but it's implicitly a new A/B test and increases the total hypotheses under simultaneous evaluation.

### Q5. Does this change your "fundamental mismatch" concern?

Your earlier concern: I'm using EOD data + overnight 1DTE long call to chase an intraday MM-gamma edge. The three layers all use the *same EOD-data signal*, but the SPOT layer specifically avoids the overnight-option expression problem. If I express the signal via SPOT (or delta-1 synthetic), the "overnight long call" part of the mismatch goes away — only the "EOD data" part remains.

Does this narrow the mismatch enough that the research tree becomes defensible? Or do you still think the edge is likely manufactured and will dissolve under harsher validation (block bootstrap + Bonferroni + event-stratification)?

### Q6. Any new blind spots given these numbers?

Specifically:
- Is the SPOT PF 4.13 in ORIG_OOS a red flag for look-ahead? (That bucket's spot Sharpe 8.51 is extraordinary.)
- Should I worry that 54.7% WR on spot with 172 trades is a small-sample coincidence?
- Am I underestimating the dividend-adjusted return on a 1-day SPY hold (quarterly dividends are small but not zero at 1-day horizon)?

## What I want back

- **Verdict on Q1**: is the SPOT edge real after the corrections you'd require?
- **Ranked recommendation on Q2**: which instrument (A/B/C/D) for v12?
- **Diagnosis of Q3**: why spread also fails Y2023
- **Paper trade revision (Q4)**: 1, 2, or 3?
- **Q5 reassessment**: does SPOT expression rescue the project, or is it still EOD-data-dependent and fragile?
- **Q6 red flags**: specifically the ORIG_OOS Sharpe 8.51 and the small N

Please stay brutal. If the right answer is "this is still probably noise, stop the search and paper-trade spot with small size," say so.
