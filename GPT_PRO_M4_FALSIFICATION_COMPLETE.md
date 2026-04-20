# M4 Falsification Complete — All 3 Baselines Failed

**Same window as prior rounds.** Following your verdict to kill Baseline 1 and do the "plumbing hardening," I rebuilt leak-safe primitives and ran all three M4 dumb baselines. They all failed. Need pivot recommendation.

## What was done

### Plumbing hardening (per your prescription)
- `src/pipeline/leak_safe.py`: cutoff-respecting primitives
  - `close_spot_leak_safe(day, cutoff="15:55")`
  - `compute_day_flow_leak_safe(day, cutoff="15:55")`
  - `rolling_zscore_shifted(series, window=60, shift=1)`
  - `future_poison_test(day, computation)`: scrambles post-cutoff data, verifies computation unchanged
- 5-test verification harness: **all pass**
  - T1 Future-poison × 10 stratified days: PASS
  - T2 Cutoff monotonicity (10:00 → 15:55): PASS
  - T3 Rolling z-score future-independence: PASS
  - T4 As-of recomputation: diff 2.22e-16
  - T5 Close-spot varies across cutoffs: PASS ($5271.63 @15:50 → $5279.37 @15:59)

### All 3 M4 baselines rebuilt on leak-safe plumbing

| Baseline | Signal | N | WR | Dir Acc | Mean | **Sharpe** | PF | vs Uncond |
|----------|--------|---|-----|---------|------|-----------|-----|-----------|
| Unconditional long SPX | — | 921 | 54.8% | — | +0.060% | **0.93** | — | 0.00 |
| B1 v3 signed flow | quote-rule on single-leg LOB, rolling z | 592 | 53.7% | 52.0% | +0.025% | **0.41** | 1.08 | −0.53 |
| B2 GEX skew | OI × gamma, call_side − put_side, rolling z | 540 | 53.0% | 52.1% | −0.013% | **−0.22** | 0.96 | −1.15 |
| B3 30-min EOD momentum | spot return last 30 min, rolling z | 489 | 46.4% | 48.0% | −0.115% | **−1.59** | 0.75 | −2.53 |

All three baselines use:
- Strict 15:55 ET cutoff for signal computation
- True close-to-close target (last underlying_price ≤ 15:55)
- Rolling 60d shift-1 z-score normalization
- Threshold |z| ≥ 0.5
- 921 evaluation days (after 60d warmup)

Data window: 952 trading days, 2022-07-01 → 2026-04-17, ATM ±3% SPXW chain, 28.7M quote rows, 336.6M tick trades.

## Key observations

### 1. Unconditional-long SPX is the ceiling (Sharpe 0.93)
The window (2022-H2 → 2026-Q1) is a strong bull market. SPX roughly doubled. No directional signal beat "do nothing."

### 2. B3 (intraday momentum) is actively anti-predictive (Sharpe −1.59, WR 46%)
Last 30-min EOD momentum predicts **REVERSAL**, not continuation. Inverse signal would be +1.59 Sharpe — but this is classic Heston 2006 intraday mean reversion, not a novel discovery.

### 3. Quote-rule signed flow adds nothing over unconditional (B1 v3: 0.41 vs 0.93)
Consistent with your Round 5 warning that option-trade classification rules perform much worse than stock rules.

### 4. GEX skew is approximately random (Sharpe −0.22, Dir Acc 52.1%)
Barbon-Buraschi "gamma fragility" mechanism does not yield directional edge at this daily horizon. It may still yield volatility predictions (Dim-Eraker-Vilkov 2024), but this baseline tested direction.

## Two uncomfortable possibilities

1. **The "dealer state + flow concentration" thesis is correct but not at this horizon.** 0DTE is intraday in its academic foundations. Forcing a daily horizon on it is the original Round 4 warning from you — "you are using EOD data to predict an intraday mechanism."

2. **The mechanism is real but the target is wrong.** GEX skew doesn't predict direction; it predicts realized volatility. Intraday momentum reverses, so short-vol trades might capture that reversal edge without picking a direction.

## Questions

### Q1. Given all 3 M4 baselines failed at daily direction, is the right pivot:
**(a) Abandon overnight-daily, rebuild for intraday** — genuinely 0DTE horizon, ~2-week engineering re-write of the engine, features re-derived from raw 1-min/tick streams that are already on disk.
**(b) Keep daily horizon but pivot from direction to volatility** — test: next-day realized vol as target, not return sign. Short-vol wrappers (straddles, butterflies) instead of delta-one bets.
**(c) Abandon options entirely and pursue the inverse of B3** — the −1.59 Sharpe of B3 is 1.59 real Sharpe of well-known intraday mean reversion. Not a novel alpha, but demonstrably a real pattern.
**(d) Kill the whole project.** Data is clean, plumbing is trustworthy, no edge found with this data at this horizon on these signals. Accept and move on.

### Q2. Is the "unconditional long SPX has Sharpe 0.93 on this window" a fatal evaluation bias?
The window starts mid-2022 (near bear-market bottom) and ends 2026-Q1 (all-time highs). Any directional long-biased strategy can look good. Any market-neutral strategy competes with 0.93 just by existing. Should I be using a different benchmark — e.g. excess over same-day-opening-spy-long, or a VIX-normalized risk-parity target?

### Q3. Should I re-run M4 with targets that aren't directional returns?
- Next-day realized volatility (predict |log return|)
- Next-day range (high − low)
- Intraday realized vol (close-to-close is too coarse for options microstructure)

Each target requires a different baseline suite. Is that worth doing before pivoting to (a) or (b) above?

### Q4. What's the shortest path to a falsification-clean intraday rebuild?
If (a) is the right pivot, what's the minimum viable intraday baseline that would give a falsification read within 1 week of engineering?

### Q5. One thing I want your honest opinion on
This result — 3/3 baselines fail after careful validation — is the expected outcome for most research efforts. The process succeeded: identified a leakage bug, hardened the plumbing, falsified the hypothesis cleanly. But there's also a version of this where the correct next step is "the signal isn't in this data; go find different data."

Specifically: the recorded universe is ATM ±3% on SPXW 0DTE, 1-min quote + tick trade + 1-min Greeks + daily OI. What's the **most informative piece of additional data** I could add before running M5? Something like:
- Cboe Open-Close participant classification (costs money)
- SPX futures intraday tape (free, different stream)
- VIX term structure intraday (free)
- Actual cross-strike flow concentration metrics (already in data but not extracted)

If the answer is "nothing; the data is sufficient and the horizon is wrong," say so.

## What I want back

- Ranked recommendation for Q1 (pivot direction)
- Yes/no on Q2 (is bull-market-bias a fatal framing issue)
- Yes/no on Q3 (try volatility targets before pivoting)
- If Q4 is the right pivot, concrete 1-week plan
- Honest answer on Q5

Brutal as always. If the right answer is "the data is telling you the edge isn't there at this horizon, stop looking," I need to hear it.
