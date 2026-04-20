# Baseline 1 Results — Review Request

**Either window works. Extended thinking. Brutal honesty.** This looks too good; I need help deciding whether it's real edge, a known artifact, or a bug I missed.

## Setup

- **Data**: SPXW 0DTE from Theta Data Pro v3, 952 trading days (2022-07-01 → 2026-04-17)
- **Universe**: ATM ±3% strikes only, ~62 contracts/day median, scales from ~45 (2022) to ~82 (2026)
- **Total**: 28.7M quote rows (1-min), 336.6M trade rows (tick)

## Baseline design

**Signal**: for each same-day trade,
1. Filter to `condition ∈ {0, 18}` (single-leg electronic LOB) per Dong AEA 2026
2. Classify aggressor via quote rule: `side = sign(trade_price - last_1min_mid)` at the (strike, right, minute) bucket
3. Aggregate: `net_signed_vol = Σ side×size on calls − Σ side×size on puts`
   - Positive = bullish SPX pressure (call-buying + put-selling)
4. Z-score `net_signed_vol` by year (volume grew 3.5× 2022→2026, so per-year normalization)
5. Fire signal when `|z| ≥ 0.5`:
   - `z ≥ 0.5` → predict SPX up tomorrow (go long)
   - `z ≤ -0.5` → predict SPX down tomorrow (go short)

**Target**: `next_day_ret_pct = (spot_{D+1} − spot_D) / spot_D`, where `spot_D` is the **median** of `underlying_price` field across the day's 1-min Greeks bars (approximate close-to-close, not exact).

**Return attribution**: signal direction × next-day spot return. No bid-ask, no slippage, no commissions. Pure directional overlay on SPX spot.

## Results

### Direction accuracy (sign of prediction vs sign of realized next-day return)
- Volume-signed: **59.2%** correct (n=951)
- Premium-signed: **56.4%** correct
- Coin-flip baseline: 50%

### Trade performance (only when signal fires, |z| ≥ 0.5)
| Signal | N | WR | Mean/trade | Total | Sharpe | PF |
|--------|---|-----|-----------|-------|--------|-----|
| Vol-signed | 588 | 61.4% | +0.202% | +118.64% | **3.45** | 1.83 |
| Premium-signed | 561 | 59.9% | +0.174% | +97.59% | 2.75 | 1.62 |

### By year (vol-signed)
| Year | N | WR | Mean/trade | Sharpe | PF |
|------|---|-----|-----------|--------|-----|
| 2022 (H2) | 80 | 56.2% | +0.105% | 1.23 | 1.21 |
| 2023 | 156 | 67.3% | +0.292% | **6.52** | 3.02 |
| 2024 | 157 | 58.6% | +0.182% | 3.61 | 1.87 |
| 2025 | 155 | 60.0% | +0.154% | 2.51 | 1.61 |
| 2026 YTD | 40 | 65.0% | +0.304% | 5.35 | 2.38 |

### By IV regime (vol-signed, yearly IV terciles)
| Regime | N | WR | Mean/trade | Sharpe | PF |
|--------|---|-----|-----------|--------|-----|
| low_vol | 197 | 62.9% | +0.144% | 4.11 | 2.01 |
| mid_vol | 203 | 61.1% | +0.235% | 4.97 | 2.25 |
| high_vol | 188 | 60.1% | +0.227% | 2.71 | 1.56 |

### Unconditional baseline (always long SPX next day)
- Mean: +0.071% per day, WR 54.3%, Sharpe **1.20**

### Signal distribution
- Long: 296 days, Short: 292 days, No signal: 363 days

## Red flags I already see (I'm suspicious)

1. **Sharpe 3.45 vs unconditional 1.20** — 2.9× improvement over a bullish period baseline; the unconditional 1.20 is already high because the window happens to cover 3 big-up years.
2. **Zero execution friction modeled** — no bid-ask, no slippage, no fees. Every per-day return of +0.202% is gross. Round-trip options-wrapper or futures-wrapper fees would reduce this materially; SPX spot isn't even directly tradable.
3. **2023 Sharpe = 6.52** — "sirens on" single-year anomaly. Possibly driven by specific macro episodes (SVB, banking crisis, dovish pivot).
4. **Tariff sensitivity check returned identical numbers** — excluding 2025-04-07..10 produced exactly the same Sharpe and PF as full sample. Either there's a filter bug, OR no signals fired those days; I haven't verified which.
5. **Median-spot approximation of close-to-close** — `spot` field in my aggregation is median `underlying_price` across the day, not the 15:59 last tick. Likely small distortion but unverified.
6. **Data snooping on threshold 0.5** — I didn't try 0.25 / 0.75 / 1.0. Any multi-threshold evaluation would require Bonferroni/White RC correction.
7. **951 trades is not "independent"** — daily returns cluster in regime blocks. Effective N is probably much smaller (maybe 30-50 regime blocks).
8. **Quote-rule aggressor signing is known-noisy in options** — prior round identified that options trade-classification rules can misclassify 30%+ of trades. I'm treating signed flow as a clean signal, which it isn't.

## Questions

### Q1. Given all 8 red flags, what's the realistic haircut on Sharpe 3.45?
If I correctly model friction, fix the close-to-close definition, do Bonferroni on threshold search, use block bootstrap on dependent daily returns, and acknowledge ~30% aggressor misclassification — what's a plausible post-haircut Sharpe? 0.5? 1.0? 1.5?

### Q2. Is the 2023 Sharpe 6.52 a smoking gun of look-ahead, or is it plausibly real?
I don't believe I have time leakage (signal uses only day D's trades, return is D→D+1). But 6.52 in one year is hard to believe. Is there a known mechanism where 2023's specific regime (SVB → AI rally → dovish pivot) would genuinely produce this result for a signed-flow signal?

### Q3. What validation MUST be done before any of these numbers are trusted?
Rank in priority order:
- [ ] Fix close-to-close definition (use last-minute `underlying_price`, not median)
- [ ] Fix the tariff-exclusion bug / confirm signals didn't fire
- [ ] Day-level block bootstrap for Sharpe CI (block length?)
- [ ] Walk-forward (60 train / 20 test?) with re-fit threshold
- [ ] Bonferroni on threshold grid {0.25, 0.5, 0.75, 1.0}
- [ ] White RC / Hansen SPA across variant signals
- [ ] Friction model: 5 bp / 10 bp / 20 bp round-trip sensitivity
- [ ] Compare to "always long the unconditional mean direction" shuffled baseline
- [ ] Stratified permutation test: shuffle signals within year/regime, does edge survive?

### Q4. Is quote-rule signed flow in 0DTE options fundamentally too noisy to trust?
Your prior round said "stock rules perform considerably worse in options; option auction paper shows 95% misclassification on some subclass; corrected overall 62% → 76% accuracy." I'm using the naive quote rule on condition={0,18} filtered trades. If true accuracy is 70%, net signed flow is (2×0.70 − 1) = 0.40 — meaningful but noisy. Does that level of noise preclude a real Sharpe 3+ result, forcing the conclusion that my result is artifact?

### Q5. Any obvious bugs in the pipeline that would inflate Sharpe?
Things to check:
- Sign convention: buy-call and sell-put are both "bullish SPX"; I compute net as `calls_signed − puts_signed` with `side = sign(price − mid)` for each leg. Correct?
- Z-score within year: is this self-referential bias (each year knows its own mean)?
- "Median spot" leakage: median includes 15:55-16:00 bars, so my "signal-time" spot is actually post-close spot. Correct concern?
- Aggregation: I sum signed trades across all filtered single-leg electronic trades for the entire day. Some of those happen in the first 30 minutes; some in the last 30 minutes. Any reason this timing matters for next-day prediction?

### Q6. If I must make a go/no-go decision today with no further validation, what is it?
Three options:
- **Kill**: probability this is real > 0.5 isn't good enough; Sharpe 3.45 is too clean, likely artifact; stop.
- **Validate then decide**: do the Q3 list; commit to killing if post-validation Sharpe < 1.0.
- **Continue as-is**: the edge might be real-enough to paper-trade immediately; frictions will erode but still positive EV.

Which should a rational practitioner pick?

## What I want back

- Quantitative answer to Q1 (haircut estimate)
- Verdict on Q2 (plausible mechanism for 2023 or red flag?)
- Prioritized Q3 list
- Q4 principle answer (is signed-flow-based edge in 0DTE even achievable at this Sharpe?)
- Any bugs caught in Q5
- Q6 decision recommendation

If the right answer is "this is almost certainly an artifact, go back and fix the plumbing, don't waste time on downstream validation yet," say so.

Context assumption: the prior round in the same project already established the committed thesis and roadmap; this is a research-phase M4 baseline result. The goal is falsification, not deployment.
