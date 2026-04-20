# GPT Pro 0DTE Verdict — Fresh Window Research (2026-04-19)

## Core one-liner

> **Kill the "MM puppet master" story. Keep the "dealer state + flow concentration + liquidity regime" thesis. Treat this as a 6–12 week falsification spike, not a production build.**

## Thesis rewrite (committed)

### ❌ REJECTED — folklore version
"MMs push price toward the strike where they make the most money, because they hold huge option positions themselves."

No peer-reviewed or working-paper evidence supports MM **active** P&L-optimizing pushing. This is retail folklore.

### ✅ ACCEPTED — academic version
"Dealer state + gamma sign + flow concentration + liquidity conditions can bend intraday returns and volatility under specific regimes, via hedging feedback and inventory channels — not intentional steering."

## Supporting literature

- **Barbon & Buraschi "Gamma Fragility"**: negative gamma × illiquidity → momentum; positive gamma → reversal. Hedging-feedback channel, not steering.
- **Dim-Eraker-Vilkov (SSRN 4692190)**: MM inventory gamma average POSITIVE, negatively related to future intraday vol. Positive gamma strengthens reversal.
- **Adams-Fontaine-Ornthanalai (SSRN 4881008, 2024 Fed)**: MMs match 0DTE flow; 0DTE availability LOWERS SPX volatility on average. Opposite of "forced destabilizing hedging" narrative.
- **Egebjerg & Kokholm**: OMM net-position changes closely linked to subsequent SPX futures returns (mechanical transmission, highly conditional).
- **Amaya et al.**: gamma reduces vol on average; when negative, can raise daily realized vol up to 3.3 ann pts, 30-min vol 6.4 ann pts.
- **Dong (AEA 2026)**: underlying impact concentrated in single-leg LOB trades, rises with delta/moneyness, negligible for auctions and multi-leg trades.
- **Hu-Kirilova-Muravyev-Ryu**: OMMs use rapid inventory turnover + trade matching, NOT blind delta hedging. S&P OMMs trade volume 32× net position change.
- **Doshi (2025)**: intraday order-flow volatility (not delta-hedging needs) is primary driver of spreads in short/ultra-short options.

## Data constraints — what's actually observable

### ✅ Available via Theta Options Pro ($160/mo)
- Every OPRA NBBO quote
- Every option trade with size/exchange/condition codes
- 1-min Greeks (exchange-sourced)
- Streaming OI (daily updates, NOT intraday)

### ❌ NOT available (and cannot be substituted)
- Participant-tagged buy/sell/open/close (Cboe Open-Close only)
- True market-maker capacity
- Ground-truth aggressor labels (~60-76% accuracy with quote/tick rule, worse on auctions)
- Full depth-of-book history
- Intraday OI (daily updates only per OCC/Theta docs)

### ⚠️ Naive aggressor signing is FAR worse than assumed
- Grauer-Schuster-Uhrig-Homburg: stock rules perform considerably worse in options (sophisticated customers use limits)
- New auction paper: quote rule can misclassify ~95% of specific auction trade class
- After auction-aware corrections: 62% → 76% overall, 56% → 81% for <1 week to expiry
- SEC/DERA: OPRA has sequencing issues — the quote AFTER a trade can appear BEFORE it in the stream

## Required feature set (minimum viable)

### ❌ DO NOT build
- "Live OI surge" detector (fake — OI is daily)
- "MM target price predictor" (folklore)
- "Max-pain push detector" (no evidence)

### ✅ DO build
1. **Prior-close OI/GEX/Vanna anchor by strike** (slow prior state, NOT live truth)
2. **Live signed flow proxy by strike** over 5m + 15m windows
3. **Flow concentration / entropy across strikes** (top-N strike concentration)
4. **Spot-to-strike distance + strike-crossing flags**
5. **ATM IV change + front-end skew change**
6. **Spread %, spread widening rate, order-flow volatility regime**
7. **Trade-condition segmentation**: single-leg LOB vs auction vs multi-leg (per Dong)

Aggregation windows: **5m + 15m** primary. 1m for triggers only (noisy). 30m for context only.

## Execution design (SPX via IB)

### Time windows
- **Regular SPX**: 8:30 AM – 3:15 PM CT
- **Expiring SPXW/EOM**: **3:00 PM CT cutoff** (15 min earlier, must handle explicitly)
- Research slice: 8:45-11:30 AM CT + 12:30-2:30 PM CT
- Avoid first 10-15 min and last 10-15 min
- Avoid macro release windows (CPI/FOMC/NFP)

### Order types
- ❌ Raw market (fake depth hunting)
- ❌ Passive midpoint (adverse selection or never fills)
- ✅ **Marketable limit with hard price cap**
- ✅ **IB Adaptive algo** (after paper verification)
- ✅ **Time-based reprice** (don't hold working orders indefinitely)

### IB combo order constraints (critical)
- Smart-combo orders DO NOT support OCA groups
- Smart-combo child orders unsupported
- Combo orders only support reduce-on-fill without block OCA
- **Spreads/butterflies: manage exit in code via state machine, NOT broker-native**
- **Directly routed combo vs SmartRouted**: directly routed = single transaction; Smart = may leg separately

## Economics math (Q4)

### Stylized assumption: 55% WR / +60% winner / −40% loser / 10% slippage
- Net per trade: +50% winner, −50% loser
- Expectancy: `0.55 × 0.50 + 0.45 × (−0.50) = +0.05` (+5% premium per trade)
- Naive iid Sharpe ceiling: **2.8-3.6** at 3-5 trades/day (FANTASY ceiling)

### Edge fragility
- Winner slips to +40% (loss −50%): expectancy goes **negative**
- Winner +45% / loser −55%: expectancy **zero**
- Small live degradation wipes edge → default, not edge case

### Sample size reality
- 95% CI exclude 0: **380 iid trades**
- 80% power to detect edge: **780 iid trades**
- Due to day-clustering: **effective sample lower than raw count**
- **500-800 frozen-param signals** for first serious statement
- **30-50 signals**: smoke test only, NOT validation

### Drawdown (Monte Carlo, 5% premium per trade)
- Median 1-year max DD: **36%**
- 95th pct: **>50%**
- Median longest losing streak: 8 trades
- 95th pct: 11 trades

## Validation methodology

- **Primary resampling unit: DAYS, not trades** (intra-day not independent)
- **Outer**: rolling/anchored walk-forward on day blocks
- **Inner**: purged/embargoed CV or CPCV on day blocks
- **Bootstrap**: stationary (Politis-Romano) with avg block length 1-3 days
- **Data-snooping correction**: White RC or Hansen SPA if testing many variants
- **Regime slicing (mandatory)**: VIX quartile, realized vol quartile, macro-event days, OPEX/roll, first-hour/mid/last-hour

Starter CV configurations:
- Fast: 20-40d train / 5-10d test
- Slow: 60d train / 20d test (check if edge survives)

## 6-phase roadmap (reordered from my draft)

| Week | Phase | Key point |
|------|-------|-----------|
| 1-2 | Recorder + Market-state QA | NOT just save parquet — message-drop detection + heartbeat + OPRA condition-code preservation |
| 2-4 | Replay engine + feature lab | Deterministic bar/event replay + quote/trade re-sequencing |
| 4-5 | Execution simulator calibration | Don't use "mid+35%" — calibrate fills from quote history |
| 5-6 | Falsification baselines | Test dumb baselines FIRST (signed flow only, prior-close GEX only, intraday momentum) |
| 6-8 | IB execution state machine | entry/replace/cancel/partial/time-stop/3PM cutoff/disconnect/kill-switch |
| 8-10 | Frozen-parameter paper trade | NO tuning, just record |
| 10-12 | Decision review | "iterate or kill", NOT "deploy" |

## 8 red flags — self-check during build

1. **Tape leakage**: performance collapses after OPRA re-sequencing fix
2. **Aggressor-sign fragility**: signal flips between quote/tick/auction-aware signing
3. **Fill inflation**: assumed midpoint fills, combo OCA, ignored 3PM cutoff
4. **Wrong trade-type mix**: signal works equally on auction/multi-leg (should only work on single-leg LOB per Dong)
5. **Story without increment**: removing options-flow features leaves most performance intact (= SPX trend system in disguise)
6. **Outlier dependence**: top 10 trades or top 5 days drive most P&L
7. **Over-specialization**: requires many symbol/strike/time-specific overrides
8. **Narrative excess**: bot "explanation" richer than inputs it actually receives

## Pre-committed kill criteria (MUST not negotiate)

| Phase | Kill condition |
|-------|---------------|
| Week 1-4 | Cannot deterministically reconstruct chain state around signals |
| Week 4-5 | Flow proxy unstable across signing variants after corrections |
| **100 paper trades** | Realized expectancy ≤ 0 after fills, OR avg winner < +45% with avg loser worse than −55% |
| **250 paper trades** | PF < 1.1, OR dumb baseline performs similarly, OR top 10 trades > 50% of P&L |
| **500 signals** | 95% CI lower bound of mean return per trade ≤ 0 after realistic costs |
| Any phase | Actual round-trip cost > 20% premium OR > 25% of modeled gross edge |

## Final brutal pushback from GPT Pro

> "Highest-probability failure mode is NOT 'the code is hard.'
> It is: 'the mechanism is real but weaker than the story, and too weak to survive live fills.'
> That's the kind of project that consumes 12 weeks and leaves you with beautiful plots and no tradable edge."

## Committed thesis (replaces original)

**ORIGINAL (rejected)**: "Build the MM-manipulation bot."

**REWRITTEN (committed)**: "Can option-flow concentration, strike proximity, IV-surface shifts, and liquidity regime proxies produce a small, execution-robust intraday SPX edge?"

If this rewritten thesis does not excite the builder, abandon now in favor of a simpler intraday ES/SPX strategy.
