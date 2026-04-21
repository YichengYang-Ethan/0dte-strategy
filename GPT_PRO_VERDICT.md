# GPT Pro Review Verdict — 2026-04-18

## TL;DR (3 sentences)

1. **Mismatch**: trying to extract intraday MM-gamma edge from EOD snapshots via overnight 1DTE SPY calls. The 0DTE literature is about *intraday index* gamma, not *overnight ETF-call carry*. Different horizon, different instrument, much more cost-sensitive.
2. **Kill OI delta** as flow proxy — identification failure (same +OI can be bullish or bearish; no clever decomposition recovers aggressor direction from daily OI).
3. **Next priority is not feature search** — it's timestamp realism, execution realism, and cleaner validation. Biggest risk: manufacturing alpha via researcher overfit, not missing alpha.

## Variant Ranking

`D > C > A >> B`

Where **D** (recommended, not in my original A/B/C):
```python
rr25 = iv_25dp_today - iv_25dc_today   # 25Δ risk reversal / skew
rr25_z = zscore(rr25, 60)
trade = v5_signal AND rr25_z <= 0      # steepening skew = no-trade filter
```
Reference: Atilgan, Bali et al. 2019 MS — IV spread predicts short-horizon index returns.

## Critical Blind Spots

### 1. My "0DTE" is really "1DTE overnight swing"
Academic 0DTE literature = intraday gamma. My trade = EOD → next-EOD long call. Fundamentally different microstructure regime.

### 2. Y2023 is no longer true OOS
I've killed 8-10 variants using it as scoreboard. It's trained me informally. Only true untouched test remaining = live paper trade (need CSCV/PBO per Bailey et al. 2014).

### 3. Possibly an instrument problem, not signal problem
Must test sequentially:
- Does v5/v11 signal predict SPY close-to-close return?
- Does signal + 0.70Δ call make money?
- Does signal + call spread make money?
If spot has edge but call loses → theta/IV/spread drag → **change the instrument, not the signal**.

### 4. Timestamp leakage risk
Theta EOD Greeks = closing quote + underlying at close. If I use same-day EOD Greeks to decide at close with same-close fills → information leakage or overstated tradability.

### 5. Fill model is a haircut, not a fill model
`mid + 35% spread` = paying 70% of quoted spread in effective-spread terms. No order-type modeling, no fill probability, no close-auction dynamics.

### 6. SPY ≠ SPX
SPY: American, physically settled, dividends.
SPX: European, cash settled.
BSM-style vanna/charm most wrong near expiry + ex-div — exactly where I trade.

### 7. Bootstrap likely iid, understates uncertainty
Need day-level block bootstrap (stationary bootstrap). Current CIs probably too tight.

### 8. 0.70Δ call is not stable across regimes
Gamma dollars, theta bleed, vega sensitivity differ. Comparing trades across regimes without delta/moneyness alignment = apples-to-oranges.

### 9. Regime-selection bias (the real sample bias, not survivorship)
824 days ≈ handful of macro states. Option predictability often clusters around macro events — must stratify CPI/FOMC/NFP/OPEX/ex-div.

### 10. False discovery
Already tried enough branches that "one more feature" is more likely to produce a story than an edge. the reference operator's 70% WR is a source of hypotheses, not evidence.

## Prescribed 7-Day Plan

| Day | Task |
|-----|------|
| 1 | Freeze research tree. Declare budget of 1 new feature family. Retire Y2023 as scoreboard. |
| 2 | Timestamp audit: verify no signal uses same-close EOD Greeks / same-day OI for same-close fills. Add ex-div + macro-event flags. |
| 3 | Validation upgrade: outer expanding walk-forward, inner purged/CPCV, block bootstrap by day. |
| 4 | **Instrument sanity check**: v5/v11 signal on (a) SPY close-to-close returns, (b) 0.70Δ call, (c) call spread. Kill project if spot has no edge. |
| 5 | Test Variant D (25Δ put-call IV skew level) as no-trade filter. Pre-declare sign and one threshold. Do NOT test B. Do NOT revive OI delta. |
| 6 | Execution stress: re-run with mid+20% / mid+35% / ask-entry+bid-exit. Believe worst case. |
| 7 | Paper trade frozen v11 — stop at 30-50 signals, not 3-6 months by calendar. |

## Methodology Prescription

- **Outer**: expanding-window walk-forward (not 60/20 — min 1 year train)
- **Inner**: purged/embargoed CV or CPCV (Lopez de Prado 2016)
- **Bootstrap**: day-level block (Politis-Romano stationary)
- **Final test**: forward live paper trade (Y2023 is burned)
- **PF ≥ 1.2 on all 4 buckets**: kill switch OK, optimization target BAD

## Feature Engineering Boundary

- Hard NO on boosted trees — "that's how you turn 824 days into fan fiction"
- LR only with Firth penalization + banned auto-selection
- Prediction literature: ~10 events per variable floor, often 20+
- Recommended: v5 base trigger + "skew not steepening" + maybe "IV shock not extreme"
- **At most ONE continuous filter OR a 2-feature linear score with predeclared signs**

## What to Abort

- OI delta feature (kill, identification failure)
- Variant A as written (|iv_shock| > 2% absolute, no normalization, bad threshold)
- Variant B (turnover skew — weakest, volume unsigned, ATM band drifts with spot)
- Pivot to Vilkov put-ratio-spread (resets research tree, SR 1.87 not independently verified)
- Grid search on feature weights
- Any ML beyond penalized LR

## What to Ship

- Variant D (25Δ IV skew filter as no-trade gate)
- Paper trade v11 → 30-50 live signals
- Timestamp + execution realism audit
- Instrument sanity check (signal on spot, on call, on spread)

## Data Upgrade Note

- the reference operator says massive ~$200/mo for realtime flow
- Theta Options tiers: ~$80 Value, ~$160 Standard+ (GPT Pro correction)
- **Cboe DataShop Open-Close** = real ground truth for signed buy/sell/open/close classification
- Only upgrade **after** paper trade shows baseline edge is live-reproducible

## the reference operator's MM-Pinning Thesis — Regime-Dependent Verdict

- the reference operator's thesis ("跟着 market maker 走,预判 MM 会推动股价到最赚钱点位") = classic SpotGamma / Barbon-Buraschi "Gamma Fragility" narrative
- **Adams 2024 SSRN 4881008**: MMs MATCH 0DTE flow, net gamma carry ≈ 0 — thesis mostly false post-2023
- Consequence: v5's Y2023 failure (PF 0.75-0.91) may be exactly the "MMs match flow" regime where pinning breaks
- Partial validity possible in specific regimes (choppy 2024-25), not universal
- the reference operator's 70% WR self-report cannot resolve this — not statistical evidence
