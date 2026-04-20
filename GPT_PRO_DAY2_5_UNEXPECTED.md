# Day 2.5 Diagnostics — Direction Signal Dead, Volatility Signal Surfacing

**Question: is extending Day 3 pre-registration to include a volatility target target-snooping, or is it a legitimate pivot per your Round 6 (b) allowance?**

## Context

Per your 5-day MVP plan, I built:
- Day 1: intraday labels (signed_ret_pct, abs_ret_pct, realized_var from t→15:55)
- Day 2: 30 features in 4 families (F1 flow, F2 concentration, F3 slow state, F4 interaction)

Before running the pre-registered Day 3 baselines, I did a diagnostic pass — correlations and sign concordance between features and the 3 labels. This was not optimization search. I ran no thresholds, no signal construction, no PnL. Just Pearson/Spearman, sign agreement, and a quintile table.

## What I found

### 1. Direction is dead

Max |Pearson r| over 11 features × 3 targets = **0.0278**. Max sign concordance with `signed_ret_pct` = **52.07%**. All features cluster in the 50–52% band. If I run the four Day 3 baselines exactly as pre-registered against `signed_ret_pct`, they will almost certainly land near coin-flip.

| Feature | r vs signed_ret_pct | Sign concordance |
|---------|--------------------:|-----------------:|
| atm_gex_skew | +0.028 | 52.07% |
| flow_delta_net_30m | –0.005 | 51.44% |
| flow_gamma_net_15m | +0.019 | 51.44% |
| interaction_sign | –0.008 | 50.32% |
| interaction_weighted | +0.003 | 50.32% |

The F4 interaction term — the explicit thesis test — showed the weakest correlation of all. That is a clean falsification of "dealer state × concentration × signed flow predicts intraday direction."

### 2. Volatility did NOT stay dead — it showed up

Quintile analysis on the best-correlated feature (`atm_gex_skew` vs `signed_ret_pct`) inadvertently surfaced a clean monotonic relationship in a different place:

| gex_skew quintile | n | mean |signed_ret| (intraday abs return) |
|-------------------|---|------------------------------------------|
| Q1 (lowest gex_skew) | 377 | 0.232% |
| Q2 | 376 | 0.250% |
| Q3 | 376 | 0.238% |
| Q4 | 376 | 0.175% |
| Q5 (highest gex_skew) | 377 | 0.111% |

Q5 abs return is **~50% lower than Q1**. Intraday realized variance shows the same compression: Q5 average `realized_var ≈ 0` while Q1–Q4 average ≈ 1e-5.

This is the signature you predicted in Round 6: Dim–Eraker–Vilkov find MM net gamma is **negatively related to future intraday volatility**, and my atm_gex_skew (call_gamma_OI − put_gamma_OI) is a direct proxy for that state variable.

### 3. Direction was never predicted by this feature set; volatility is

So the empirical result is the exact asymmetry the 2024 paper describes. The feature family that has no directional content has clean volatility content.

## The question

Your Round 6 ranking said:
> **(a) Rebuild for intraday. (b) Only if you redefine it as same-day post-signal volatility, not next-day volatility.**

The current plan was (a) alone. (b) was a conditional fallback.

My plan was to pre-register four Day 3 baselines against three targets. The pre-registration was:
1. flow-only → signed_ret_pct
2. state-only → signed_ret_pct
3. interaction-only → signed_ret_pct
4. inverse-B3 → signed_ret_pct (sanity benchmark)

All against `signed_ret_pct`. Volatility targets (`abs_ret_pct`, `realized_var`) were in the label parquet but not in the baselines.

**Question 1**: Given diagnostic evidence that direction is ~zero but volatility is visibly non-flat, is it target-snooping to extend Day 3 to also run these 4 baselines against `abs_ret_pct` and `realized_var`?

Arguments for extending (not snooping):
- The labels were pre-computed before the diagnostic.
- Adding more targets triples the multiple-testing burden but I can control for it with Bonferroni / SPA.
- Your Round 6 (b) explicitly preserved volatility as a legitimate alternative target.
- Not adding it means I run 4 baselines I already know will fail.

Arguments against extending (snooping):
- I peeked at the data first.
- Choosing volatility because I saw signal is, by definition, data-contingent.
- Pre-registration is weaker if the choice of target depends on diagnostic output.

**Question 2**: If extension is acceptable, what's the minimally biased way to report it?

Three options:
- **Split result**: run and report (signed_ret_pct) and (abs_ret_pct / realized_var) as two independent pre-registrations, Bonferroni-corrected with family size 2.
- **Unified pre-registration**: run all 12 tests (4 baselines × 3 targets) with Bonferroni family size 12.
- **Confirmation sample**: hold out the last 6 months as untouched OOS, tune on the first 3.5 years, then report on the held-out block.

**Question 3**: If the observed r = 0.028 for direction and the Q1–Q5 gap of ~0.12 percentage points of abs return is real, what minimum Sharpe would a short-volatility strategy need to hit to be economically interesting, after accounting for:
- straddle/strangle bid–ask spread at 15:00 on SPXW 0DTE (empirically ~5% of premium per round-trip),
- gamma risk on the short leg as expiry approaches,
- the compression of Q5 being driven partly by the characteristic that high gex_skew days are themselves already low-vol days (confounder, not causal),
- the sample being overwhelmingly post-2022 low-vol (bull market + subdued IV),
- the trade being at least once per signal-firing day across 920+ evaluation days.

My guess is the threshold is Sharpe 1.0 after realistic costs. If the realized edge maps back to Sharpe 0.3 after costs, it is not worth pursuing.

**Question 4**: Given the diagnostic found volatility signal, does my five-day plan still apply, or does it re-rank? Specifically:

- Day 3 original: run 4 baselines on direction.
- Day 3 revised: run 4 baselines on direction + 4 on volatility (12 tests).
- Day 4: minute-resolution plumbing tests (unchanged).
- Day 5: stop/go memo (scope may change — now also about which target family to carry forward).

Does the stop/go criterion also need to be rewritten? Originally:
- sign-consistent across years,
- positive on ≥1 intraday target,
- not driven by one quarter,
- positive after crude cost haircut.

Does this still hold for a volatility strategy, where "sign-consistent" isn't the right framing (vol prediction is magnitude, not sign)?

**Question 5**: If I continue, should I also add a **short-volatility sanity benchmark** (analog to inverse-B3 for direction)? Something like "always short ATM straddle at 15:00, hold to 15:55" — if my state-conditional short-straddle beats this unconditional short-straddle benchmark by >0.3 Sharpe, edge is attributable to the state filter.

## What I want back

Ranked go/no-go for extending Day 3 to volatility targets. Concrete answer on multiple-testing treatment. Pushback on my "r = 0.028 is noise but Q1–Q5 gap is real" framing — are those consistent, or am I cherry-picking a quintile transformation to rescue a dead linear signal?

I need the brutal version. If extending is snooping, say so, and I'll run the dead-direction baselines as pre-registered and stop.
