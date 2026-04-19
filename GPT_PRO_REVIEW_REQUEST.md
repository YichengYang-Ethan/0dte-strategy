# GPT Pro Review Request — 0DTE Strategy v12 Design

## Context

I'm Ethan, a UIUC student building a 0DTE SPY options swing strategy (EOD → next-EOD, 1DTE). I've spent ~10 days + 1 overnight iteration on this. Current status:

- **824 days of SPY option chain data** (2023-01-03 → 2026-04-16), enriched with Theta Data Standard official Greeks + IV + spot
- **Per-day parquet**, ~1,960 rows each, covering 5 nearest expirations × all strikes
- **Strategy v5** (rule-based): `if NEG_GAMMA regime and position_in_range < 0.15 → buy 0.70Δ 1DTE call`
- **Validated with 4-tier OOS**: ORIG_IS / ORIG_OOS / EXT_OOS / Y2023 (2023 is the true never-seen OOS)
- **All signal modes FAIL Y2023** (PF 0.75–0.91). Every mode's bootstrap 95% CI for PF includes < 1.
- **Best so far**: v11 regime-switch combo passes all 4 buckets marginally (Y2023 PF=1.07, EXT_OOS PF=1.09)

## The new information

A UIUC friend (Joey) runs a similar-looking 0DTE bot, claimed ~70% WR. I extracted his architecture over WeChat today. Three layers:

1. **Raw features** (I have all 11): GEX total, GEX skew, call-wall, put-wall, ATM IV, Vanna total, bid-ask spread, DTE, volume, price range HLC, order-book L1/L2, symbol blacklist
2. **Aggregation + combination features** (he has, I don't): *net flow* (aggressor-side signed volume from massive.com WebSocket data, ~$200/mo), plus "hand-picked aggregation windows × combination crosses" he says tuned via grid search on historical weights
3. **Per-symbol specialization** (he has, I don't): different feature subsets per ticker

Joey is NOT a trained quant — he's a CS/Stat undergrad who writes code via GPT and tunes parameters by hand. He has no formal OOS discipline ("要过拟合到什么程度完全看自己把控"). His 70% WR is self-reported, no statistical evidence.

### Joey's explicit trading thesis (just revealed)

Joey's core thesis is **"MM pinning"**:
- "I basically follow the market maker"
- "My job is to predict what the market maker will do"
- "MMs provide liquidity but also want to make money"
- "They push the price toward the strike where they make the most money"
- "Because they hold huge option positions themselves"
- "Longs and shorts use options to 'hijack' the MM → MM then pushes the price"

Translated into academic language: **customer OI concentration at a strike → MM is short gamma → MM delta-hedging is mechanically attracted to that strike → price pins there.** This is the SpotGamma / Barbon-Buraschi "Gamma Fragility" narrative.

**My concern**: Adams/Fontaine/Ornthanalai (SSRN 4881008, May 2024) used regulatory data and found that **MMs actually MATCH 0DTE customer flow** — net dealer gamma carry is essentially zero most days. The "dealers are short gamma → pinning" narrative may be retail folklore that doesn't hold post-2023 when 0DTE volumes exploded.

**Two-sided question to GPT Pro**:
1. Is Joey's MM-pinning thesis empirically valid in 2024-2026 SPY 0DTE? Or is Adams 2024 correct that MMs match flow, making this thesis obsolete?
2. If the thesis is partially valid, in which market regimes does it still work? My Y2023 failure (PF 0.75-0.91 across all signal modes) might be exactly the "MMs match flow" regime where pinning breaks.

## What I want to build (v12 candidate)

I want to borrow his "layer 2" idea (aggregation + cross features) but stay inside what my EOD data supports. Three variants I'm considering:

### Variant A — IV shock filter
```python
iv_shock = today_atm_iv - yesterday_atm_iv   # absolute daily IV change
# Gate: |iv_shock| > 2% AND v5 signal fires → trade
```
Rationale: Joey said "7175 IV 极度暴涨 + gamma 敞口 → target zone". IV is exchange-sourced, low noise, good time-alignment at EOD.

### Variant B — Volume/OI turnover skew
```python
call_vol_oi = Σ(volume_call) / Σ(oi_call)   # ATM ±5%
put_vol_oi  = Σ(volume_put)  / Σ(oi_put)
turnover_skew = call_vol_oi - put_vol_oi
```
Rationale: volume is the only direct-flow proxy I have; high turnover = attention; directional skew = sentiment.

### Variant C — Vanna-weighted IV skew change
```python
skew_change = (iv_25dp_today - iv_25dc_today) - (iv_25dp_yest - iv_25dc_yest)
```
Rationale: IV skew steepening = crowd paying up for downside → Karsan vanna rally paper.

## Original v12a I had in mind BUT RULED OUT

**OI delta as net-flow proxy**:
```python
oi_delta = today_oi - yesterday_oi  # per (strike, right, expiry)
flow_skew = Σ oi_delta[call] - Σ oi_delta[put]   # ATM band
```

**Why I ruled it out** (want GPT Pro to validate):
1. OI Δ measures *open vs close*, not *buy vs sell aggressor*. Same +OI can be bullish (customer buy-to-open call) or bearish (customer sell-to-open call / dealer short). **Sign is ambiguous.**
2. Sanity check on 3 random day-pairs showed no predictive relationship:
   ```
   2023-05-26→30: skew -286k, next-day return +0.04%
   2024-08-07→08: skew  -16k, next-day +2.31%
   2025-10-17→20: skew -120k, next-day +1.04%
   ```
3. SPY put OI is structurally > call OI (hedging demand), so skew is always negative — no meaningful zero-crossing.
4. EOD time resolution cannot capture intraday "dealer flip" that Joey's tick-level data catches.

## Questions I need GPT Pro to answer

### 1. Am I right to reject OI delta?
Or is there a signed decomposition trick I'm missing? (e.g., unusual OI move at OTM strike ≠ portfolio hedge, more likely directional speculation?)

### 2. Of variants A / B / C, which is best?
Criteria: (a) theoretical grounding in 0DTE microstructure literature, (b) robustness under regime shifts (my data includes 2023 trending, 2024-25 choppy, 2026-Q1 correction), (c) low overfit risk given I already have 11 raw features + only 824 days.

### 3. Is adding ANY feature worth it right now?
Given:
- v5 with a single rule already failed Y2023
- I have 824 trading days (not huge for rule search)
- Joey's edge likely comes from (a) $200/mo realtime flow data I can't replicate, (b) years of hand-tuning intuition
- Bootstrap CIs on existing variants all include PF < 1

Should I instead:
- Paper-trade v11 for 3-6 months (collect live observations)?
- Pivot to Vilkov 2023's SR=1.87 put-ratio-spread on SPX with ML classifier?
- Accept that 0DTE swing with EOD data is fundamentally under-informed, and go intraday (requires data upgrade ≥ $200/mo)?

### 4. Walk-forward validation methodology
Joey does "grid search on historical weights with subjective stopping". I currently do:
- Fixed-date splits (ORIG_IS/ORIG_OOS/EXT_OOS/Y2023)
- Bootstrap 1000x resampling for PF CIs
- 4-tier check that any candidate must beat PF ≥ 1.2 on all 4 buckets

Should I use:
- **Expanding-window walk-forward** (train on 60-day rolling, test on next 20)?
- **Combinatorial purged CV** (Lopez de Prado)?
- **Nested CV** (outer: time splits, inner: param search)?

### 5. Feature engineering boundary
If I add 1-2 features on top of v5's rule, what's the right framework?
- Pure rule (if X and Y then trade)
- Linear weight (w1·GEX + w2·IV_shock > threshold)
- Logistic regression on trade/no-trade
- Boosted tree (overkill?)

Given N ≈ 30-130 trades per bucket, is anything beyond linear defensible?

### 6. What am I missing entirely?
Blind spots — things a real quant practitioner would immediately flag that I'm unaware of. Specific concerns:
- Data leakage in my existing v5 pipeline? (see `src/backtest/engine.py`, `scripts/validate_v5.py`)
- Survivorship in my 824-day sample? (SPY didn't go bankrupt, but regime selection bias)
- Execution realism: my FillSimulator uses mid + 35% spread, is that realistic for 0DTE 0.70Δ calls?

## Files to review

- `MORNING_SUMMARY.md` — overnight iteration results + v5/v11 performance tables
- `DAILY_LOG.md` — full narrative of what I tried (8-10 signal variants, all failed Y2023)
- `src/backtest/engine.py` — backtest engine with signal_mode multiplexer
- `src/gex/calculator.py` — GEX (SpotGamma S²·0.01) + VEX (vanna × OI × 100 × S × k × 0.01) formulas
- `src/gex/greeks.py` — BSM Vanna/Charm computation
- `src/signal/generator.py` — v5 rule (NEG_GAMMA + pos<0.15)
- `scripts/validate_4tier.py` — 4-tier OOS test harness
- `scripts/bootstrap_pf.py` — bootstrap PF CIs
- `scripts/test_regime_switch.py` — v11 regime-switch combo
- `scripts/paper_trade.py` — daily paper trade runner
- `src/data/enrich_v2.py` — Theta Standard enrichment
- `src/data/historical.py` — Theta OI downloader

Data schema per parquet (824 files):
```
timestamp, strike, right (C/P), expiry (YYYYMMDD), 
open_interest, spot,
bid, ask, close, volume,
delta, gamma, theta_greek (→theta), vega, vanna, charm,
iv, underlying_price
```

## What I want back from GPT Pro

1. **Verdict on OI delta ruling-out** — am I right?
2. **Ranked recommendation** of variants A/B/C (or a 4th variant I missed)
3. **Go/no-go on adding features now** vs paper-trading v11 vs pivoting
4. **Methodology prescription** for walk-forward / CV
5. **Blind-spot audit** — what am I missing that's obvious to a practitioner
6. **Concrete next 1-week plan** given all of the above

I'd rather hear "stop building and paper-trade" than get validation for more overfitting. Please be brutal.
