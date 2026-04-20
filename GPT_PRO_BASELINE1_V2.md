# Baseline 1 Post-Mortem — Edge Was Leakage

**Update on the prior Baseline 1 brief.** While awaiting review, self-audited for the two most likely bugs. One was benign, the other destroyed the result. The "Sharpe 3.45" is gone. New Sharpe after fixes: **0.05**.

## What I checked

### Check A: Tariff filter (2025-04-07..10)
Not a bug. Signals legitimately did not fire on those days because the year's std was inflated by the tariff-week's own extreme signed-flow values, which compressed each day's z-score below the |0.5| threshold. The 4 extreme days self-normalized each other out. The filter code was correct; excluding them produced identical numbers because none were in the signal-firing subset.

This does reveal a second-order problem — yearly z-score is weakly self-referential — which led me to Check B.

### Check B: Close-to-close definition (the real bug)
In v1, `spot_D = median(underlying_price)` across that day's 1-min Greeks bars. The median includes the final 30 minutes of the session, which is after the moment at which I'd be making the trading decision.

So `next_day_ret_pct = (spot_{D+1} − spot_D) / spot_D` was comparing:
- spot_D = central tendency of day D including late-day
- spot_{D+1} = central tendency of day D+1 including late-day
This "median center" implicitly includes early afternoon and end-of-day bars of D+1 — bars I ostensibly have no business seeing yet because I'm supposed to exit at D+1's close.

**More damningly, the median for day D includes the last-30-minute bars — which means my "day D trade signal" is computed from trades that occurred AFTER the signal time I claimed (EOD of D).** Part of the day-D "median spot" came from bars that happened after the market moves those bars themselves captured.

### Also fixed: z-score
Replaced `(x − year.mean()) / year.std()` with `(x − rolling_60d.mean().shift(1)) / rolling_60d.std().shift(1)` — strict walk-forward with 60-day window, no same-day contamination.

## Results after fixes

| Version | Signal | Return | N | WR | Mean | Sharpe | PF |
|---------|--------|--------|---|-----|------|--------|-----|
| v1 (original) | year z-score | median-spot | 575 | 61.4% | +0.199% | **3.41** | 1.82 |
| v1.5 | year z-score | true close | 575 | 51.0% | +0.004% | **0.06** | 1.01 |
| v2 (final) | rolling 60d z (shift-1) | true close | 598 | 52.0% | +0.003% | **0.05** | 1.01 |

Direction accuracy: v1 51.7%, v2 51.8% (coin flip 50%).

Excess Sharpe vs unconditional long SPX:
- v1: +2.49 (**manufactured**)
- v2: -0.87 (**actively worse than doing nothing**)

The shift from v1 → v1.5 changed only the return definition and Sharpe collapsed from 3.41 to 0.06. That 3.35 Sharpe of "edge" was return-side leakage from the median-spot definition. The additional z-score fix (v1.5 → v2) moved Sharpe from 0.06 to 0.05 — confirming that the z-score leak was minor relative to the spot-definition leak.

## Revised belief

Naive quote-rule signed flow on single-leg electronic SPXW 0DTE trades has **no detectable edge** for next-day SPX close-to-close direction. WR 52%, direction accuracy 51.8%, basically coin flip.

This is consistent with the prior round's warning about quote-rule misclassification in options, and also consistent with the "if signal survives only in leaky evaluation, it's not real" framing.

## New questions

### Q1. Does the Sharpe 3.41 → 0.05 collapse pattern look like something you've seen before?
I'd like to calibrate: is "median-of-day as spot" a well-known leakage pattern, or is this an especially stupid mistake? The fix felt obvious in hindsight; asking whether this is common enough to build a lint rule against.

### Q2. Given naive signed flow failed, what's the most informative next step?
Three candidates I'm considering for M4 baseline 2/3:
- **Baseline 2**: Prior-close GEX/Vanna anchor — purely positional state, no trade classification needed, no aggressor signing
- **Baseline 3**: Intraday 15-min momentum — SPX-only, no option data at all (pure spot/futures signal)
- **Variant of Baseline 1**: Use only `condition = 145` (BID_AGGRESSOR) and `146` (ASK_AGGRESSOR) trades, which have exchange-attested aggressor side, not quote-rule inferred. Likely tiny sample size but clean.

Which is the highest-EV thing to run next?

### Q3. Should I re-examine v2 at different thresholds before declaring it dead?
v2 used threshold |z| ≥ 0.5. I did not try 0.3, 0.75, 1.0, 1.5. If I did, some threshold might "just happen" to look better, but this is also exactly where data-snooping kills research. What's the disciplined way to handle this?

### Q4. Is a dataset-wide sanity-check baseline worth writing now?
Something like "random day direction + unconditional long + lagged 1-day momentum + OPEX Friday only" — a grid of trivial baselines to verify our measurement pipeline itself is sound, before running more complex signals. The v1 → v2 collapse makes me worried that other pipelines have latent leakage.

### Q5. One nagging question I can't shake
The v2 Sharpe is 0.05 (essentially zero), but the unconditional long-SPX Sharpe is 0.91 over the same window. So the signal-based strategy actively underperforms "always long" by a full 0.87 Sharpe. On a finite window covering a strong bull market, I expect "always long" to be the ceiling, but **0.87 Sharpe below it** — and WR 52% with essentially random direction — suggests the signal is marginally anti-informative. Is this plausibly just finite-sample noise, or does it suggest the quote-rule aggressor classification is actively wrong more than 50% of the time on single-leg electronic 0DTE?

### Q6. Meta-question on M4 pipeline discipline
Given v1 had a leakage bug that produced a plausible-looking 3.4 Sharpe, what's the minimum set of sanity checks every future baseline should include BEFORE I believe any number?
- Close-to-close = strict last-bar or earlier, no aggregation that includes the prediction horizon
- Z-score / normalization = shifted by ≥1 bar, walk-forward only
- Signal vs unconditional long excess Sharpe > 0 as a required floor
- Direction accuracy > 52% as a floor for genuinely predictive signals
- Block bootstrap CI lower bound > 0 before believing anything

What else should be on that checklist?

## What I want back

Quick answers to Q1-Q6. Q1 is a calibration question ("how common is this mistake"), Q2 asks for ranking of next-step candidates, Q5 is the one that actually keeps me up: is quote-rule aggressor classification net-wrong in 0DTE, or is this just noise?

Don't need a multi-page deep dive — this is a mid-course correction, not a fresh analysis.
