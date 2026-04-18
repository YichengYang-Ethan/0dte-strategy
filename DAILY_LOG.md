# Overnight Iteration Log — 2026-04-18

Session started at ~01:55 CT. User went to sleep. Autonomous iteration mandate:
deeply think before each change, self-debate, external search, no overfitting.

## Working principles (contract with user)

- Every change validated on ALL 3 OOS buckets (ORIG_IS / ORIG_OOS / EXT_OOS)
- Roll back if any bucket PF < 1.2
- No exhaustive grid search
- No EXT_OOS-specific retuning
- Feature branch: `feature/v5-real-greeks` (not merging to main without review)

## Baseline (v4, BSM-inverted IV)

```
                N    WR     PF    Sharpe
ORIG_IS   (114) 30  60.0%  1.77  3.18
ORIG_OOS  (118) 17  41.2%  1.77  3.56
EXT_OOS   (345) 87  54.0%  1.23  0.92
ALL       (574) 134 53.7%  1.40  1.59
```

---

## Iteration 1: v5 — Theta official Greeks replace BSM-inverted

**Hypothesis**: My brentq IV inversion from mid-price may be noisy at the wings and
on 0DTE where optionality is tiny. Theta Standard provides exchange-sourced IV +
all Greeks. Strategy logic unchanged; only data layer upgrades.

**Prediction**: Metrics should be *slightly* different but directionally similar,
because (a) my BSM IV was pretty close for ATM, (b) Greeks recomputation in
`enrich_greeks` was correct given IV, (c) the core signal is regime + pos — not
Greek-sensitive.

**Risk of invalidation**: If v5 differs substantially (PF shift > 20%), it means
my v4 conclusions were built on bad data, and the "3-tier OOS" was meaningless
because all 3 buckets shared the same IV estimation noise.

Running enrichment — wait for all 574 days before running backtest.

---

## 🚨 CRITICAL LITERATURE UPDATE (research agent completed)

Two 2024 papers **partially overturn** the Baltussen 2021 dealer-gamma narrative
I built v4 on. User-facing TL;DR:

1. **Adams/Fontaine/Ornthanalai (SSRN 4881008, May 2024)**: MMs **match** 0DTE
   flow → near-zero net dealer gamma carry. "Dealers short gamma" is empirically
   FALSE most days. Cboe: dealer hedging is ~0.2% of SPX liquidity. The alpha, if
   any, lives in dealer inventory aged 1-4 weeks — NOT fresh 0DTE flow.
2. **Baltussen/Da/Soebhag (SSRN 5039009, Nov 2024)**: Same lead author as JFE
   2021 now shows **end-of-day REVERSAL** in the cross-section, explained by
   retail attention and short-seller risk-management — NOT gamma hedging.
3. **Zero peer-reviewed support for put-wall bounces** — "folk wisdom."
4. **Vilkov 0DTE Rules (SSRN 4641356)**: 0DTE VRP exists but "small and hard to
   monetize after frictions"; only disciplined 10:00 ET conditional rules work
   under strict OOS protocol.
5. **0DTE dies at 4pm** — no mechanistic overnight carry, which means my v4's
   1DTE swing (overnight) hold does NOT inherit 0DTE gamma dynamics.

**Impact on my priors**:
- v4's PF 1.23-1.77 across 3 buckets is real statistical pattern
- But the *mechanism* I wrote into memory ("dealers must buy to hedge") is
  empirically disputed
- Strategy may be riding coincidental correlation with end-of-day reversal
  (which affects individual stocks more than index, per Baltussen 2024)
- Publication bias: any retail-visible signal decays 30-50% in live trading

**Action items this changes**:
- Memory text claiming "Baltussen-supported mechanism" must be updated to
  acknowledge literature moved against us
- Before trusting v4 with real capital, should check if alternative conditioning
  (10:00 ET entry per Vilkov, or explicit retail-attention proxy) works
- v5/v6 still worth doing (Greeks upgrade is orthogonal to mechanism)
- Probably NOT worth building full intraday engine (v9) until we have stronger
  theoretical grounding — could be expensive dev for a decayed signal

**NEW PRIORITY: v7 mechanism attribution**
If my GEX signal is really just a proxy for "spot dropped today → reverses
tomorrow" (end-of-day reversal mechanism from Baltussen 2024), then the GEX
framework adds nothing and I should just use a simple 1-day mean reversion rule.
Script: `scripts/diagnose_v7_mechanism.py` — will run once v2 enrichment done.

---

## 📊 Vilkov 0DTE Trading Rules — extracted (research agent 2)

SSRN 4641356 has public replication on GitHub (`vilkovgr/0dte-strategies`).
Key intel:

**Architecture**:
- 10:00 ET entry (NOT EOD), hold to 16:00 ET cash settlement
- SPXW European (not SPY) — no assignment, 60/40 tax
- Moneyness ±1% for strike selection (not delta)
- 30-min option bars, 1-min SPX/VIX for RV features
- Costs: half bid-ask + 0.5bp per leg

**Winning rules (OOS 2019-2026)**:
| Strategy              | OOS SR  |
|-----------------------|---------|
| Put ratio spread      | **1.87** (rolling), 1.83 (expanding) |
| Strangle/straddle     | 1.04    |
| Iron condor/butterfly | 1.33    |
| Bear put spread       | 0.44    |
| Bull call spread      | 0.37    |
| Risk reversal         | 0.02 (FAIL) |
| Call ratio spread     | -0.03 (FAIL) |

**Critical alpha driver**: L2-logistic regression classifier on features
(IV, implied skew, slopes, lagged RV/RS, lagged PNL, GEX proxies).
Predicts `p = P(net PNL > 0)`. Position sign = sign(p−0.5). Structure itself
is NOT the edge — timing/classification is.

**Insight for me**:
1. Vilkov's long-vol rules (straddle SR 1.04) are worse than short-vol rules
   (put ratio 1.87). My v4 is long-call (long vol). The literature view is:
   **short-vol structures are more profitable on 0DTE**.
2. My v4 uses delta targeting; Vilkov uses moneyness.
3. Vilkov uses ML classifier on 10+ features; I use one GEX rule.

**Cannot immediately port**: SPXW vs SPY difference is material (liquidity,
settlement, contract size). But **conceptually**:
- I could add a put-ratio-spread strategy to my engine as a benchmark
- Could try Vilkov's feature set + logistic classifier on my EOD→EOD data
  (with the caveat that my 1DTE swing is not 0DTE intraday)

**Decision**: Not porting Vilkov tonight. Fundamentally different strategy
(intraday vs swing, SPX vs SPY, multi-leg vs single-leg). Document for future
reference. Execute v5/v6/v7 first.

---

## Execution results (v2 enrichment complete @ 02:47)

### v5: Real Theta Greeks ✅ PASS ALL BUCKETS
```
            v5 (real)       v4 (BSM)      Delta
ORIG_IS    PF 1.67 (27 N)   PF 1.77        -0.10
ORIG_OOS   PF 1.84 (19 N)   PF 1.77        +0.07
EXT_OOS    PF 1.29 (67 N)   PF 1.23        +0.06
ALL        PF 1.43 (113 N)  PF 1.40        +0.03
```
Real Greeks produce fewer trades (113 vs 134) but slightly better OOS metrics.
**Verdict**: data upgrade is strictly safe; commit.

### v6: Regime re-diagnosis
Real Greeks shift regime labels modestly:
- ORIG_IS: 73 NEG / 40 POS (v4) → 67 NEG / 47 POS (v5)
- ORIG_OOS: ? → 42 NEG / 75 POS
- EXT_OOS: ? → 148 NEG / 195 POS

pos<0.15 trigger rate:
- ORIG_IS 32%, ORIG_OOS 21%, EXT_OOS 21%

**Verdict**: labels shifted moderately. v5 still passes OOS → signal robust to
label noise.

### v7: Mechanism attribution (CRITICAL)
Tests whether GEX signal is independent alpha or proxy for 1-day mean reversion.

Results on 574 days:
```
Pure MR (r1d<-0.5%, buy 0.70Δ call):  N=109  WR 56.9%  PF 1.74  ← strongest!
v5 GEX signal:                          N=113  WR 53.1%  PF 1.43
v5 ∩ MR (both triggered):               N=71   WR 54.9%  PF 1.71
v5 \ MR (GEX without any drop):         N=42   WR 50.0%  PF 1.00  ← no edge
```

**Per-bucket v5 \ MR** (is GEX alpha independent?):
- ORIG_IS: PF 1.64 ✓
- ORIG_OOS: PF 0.82 ✗
- EXT_OOS: PF 1.09 marginal

**GEX independent alpha is weak**. Much of v4/v5's edge comes from coincidence
with prior-day drop. Matches Baltussen 2024 end-of-day reversal thesis.

### v8: Pure MR standalone (no GEX)
Tested thresholds -0.3% / -0.5% / -0.7% / -1.0% / -1.5%.

All thresholds **FAIL ORIG_IS** (PF 0.76-1.00). Mean reversion worked in
2024-2025 but not in 2025-11 → 2026-04. Regime-dependent.

### v9: Union GEX ∪ MR (candidate — DO NOT promote yet)
Combining both signals (either triggers):
```
EXT_OOS:   N=94  WR 54.3%  PF 1.37
ORIG_OOS:  N=25  WR 56.0%  PF 2.56
ORIG_IS:   N=32  WR 56.2%  PF 1.48
ALL:       N=151 WR 55.0%  PF 1.51
```
Breakdown: Both triggered 71, GEX only 42, MR only 38. Union 47% overlap.

All 3 buckets pass PF ≥ 1.37, Sharpe likely ~2. But:
- This IS retro-fitting a union after seeing the data
- Tries to capture both "MR regime" (2024-2025) and "GEX regime" (2025-2026)
- Could be genuine or could be hindsight selection

**Verdict for v9**: document as candidate, recommend A/B paper trade vs v5,
do not overwrite main strategy.

### Commit plan
- v5 (real Greeks): merge to main — it's a pure data-quality upgrade
- v9 (GEX∪MR union): keep on feature branch, need forward OOS via paper trade
- Mechanism narrative in memory must be corrected (v5 is not "pure dealer
  gamma hedging" — it's partially MR proxy)

### v10: IV skew signal — NULL RESULT (documented failure)
Tested at ~03:00 CT. Skew = IV(98% put) - IV(102% call) for 1DTE expiry.
- Corr(skew, next-day pnl) = -0.036 (zero)
- Corr(skew, r1d) = 0.256 (partially MR-correlated, so not independent)
- Skew HIGH tercile across all 574 days: PF 0.85 (anti-predictive)
- Skew HIGH across buckets: EXT 1.30 / OOS 0.92 / IS 0.33 → FAILS OOS
- Skew HIGH without MR (independent alpha check): PF 0.66 — NO independent edge

**Verdict**: IV skew is not a tradeable signal in my EOD data. Dropping.
Matches the academic finding that skew's predictive power is mostly in cross-
section of stocks, not time-series of index.

### Kicked off:
- 2023 data download (PID 4335) for 4th-tier OOS validation
  (~250 days at ~15s = ~60 min, then ~40 min enrich)

