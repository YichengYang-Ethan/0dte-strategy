# Morning Summary — Overnight Iteration 2026-04-18

## TL;DR

**Strategy v5 fails when tested on 2023 data (4th-tier OOS).** 5+ hours of
iteration, 824 days of data, multiple signal variants, all structural
inversions — nothing passes all 4 OOS buckets. Do not deploy real capital.

## What I accomplished

1. ✅ Upgraded Theta Data to Standard; rewrote enrichment to use official
   Greeks instead of BSM-inverted IV. Modest metric improvement on the
   existing 574 days. **v5 committed on `feature/v5-real-greeks` branch.**
2. ✅ Downloaded + v2-enriched 250 days of 2023 SPY OI (all the way from
   2023-01-03). This is a true 4th-tier OOS that was never seen during design.
3. ✅ Added signal-mode multiplexer (gex / mr / gex_or_mr / gex_and_mr) to
   the backtest engine. Useful future infrastructure.
4. ✅ Ran 2 external research agents (Baltussen 2024, Vilkov 2023 papers).
   Literature concurs with my diagnostic findings.
5. ✅ Bootstrap CIs + Y2023 4-tier OOS proved every signal variant is
   regime-dependent. **No universal edge.**

## Key numerical findings

```
                      Y2023   EXT_OOS  ORIG_OOS  ORIG_IS  ALL (824d)
gex (v5 production)   0.78    1.29     1.84      1.67     1.25
mr                    0.91    1.70     4.66      1.12     1.46
gex_or_mr             0.91    1.34     2.56      1.48     1.32
gex_and_mr            0.75    1.77     3.61      1.30     1.39
short_call            1.11    0.72     0.45      0.52     0.72
```

**Every mode loses money or barely breaks even in Y2023.**
**Bootstrap 95% CI for every mode × every bucket includes PF < 1.**

## What the literature said (2023-2026)

- Adams/Fontaine/Ornthanalai SSRN 4881008 (2024): MMs match 0DTE flow; net
  dealer gamma carry ~0. "Dealers short gamma" assumption is empirically
  false most days. (contradicts my v4 narrative)
- Baltussen/Da/Soebhag SSRN 5039009 (2024): same authors who wrote the 2021
  JFE paper I built on now document end-of-day REVERSAL, not momentum.
- Vilkov SSRN 4641356 (2023, updated 2026): best 0DTE rule is **put ratio
  spread** (not long calls), SR 1.87 OOS, but requires ML classifier on IV
  skew/slope/RV features at 10:00 ET entry. SPX not SPY.

## Decision for user

Three options in order of increasing risk-acceptance:

**Option A — Abandon**: Don't trade this. Close the project. Preserved
infrastructure can seed a future strategy.

**Option B — Paper trade anyway, small**: Run the paper_trade.py daily log
for 6+ months. Learn when the regime is favorable. Position size = 1 contract
maximum until you've seen a real fat-tail event LIVE.

**Option C — Pivot to structurally different strategy**: Implement a short-
vol variant (Vilkov put ratio spread, iron condor, or delta-neutral IV
scalping). Requires Theta Standard (already have), SPX options data, and
possibly ML classifier. Est. 1-2 weeks of rewrite.

**My recommendation**: Option A for real capital. Option B with paper trade
for educational value. Do NOT deploy real capital on v5.

## Git state

```
Main branch (untouched):
  f46d228  Paper-trade signal logger + cron setup

Feature branch (feature/v5-real-greeks, 4 commits ahead):
  5753ee3  Structural inversions fail too (latest)
  3dfaf11  Y2023 4-tier OOS: strategy FAILS
  a2c8142  Engine signal_mode multiplexer
  69d5c35  v5: Theta Standard Greeks + mechanism honesty

Files to review:
  DAILY_LOG.md        — full overnight narrative
  MORNING_SUMMARY.md  — this file
  scripts/validate_4tier.py  — rerun the 4-tier test
  scripts/bootstrap_pf.py    — rerun bootstrap CIs
```

## If you want to proceed with paper trade anyway

```bash
cd ~/0dte-strategy
git checkout feature/v5-real-greeks  # use the real-Greeks pipeline
# Daily at ~8:30 AM ET:
python3 scripts/paper_trade.py --mode daily
```

Running this daily will accumulate live OOS observations. Expectations:
- ~1-2 trades per week
- Modal month may be flat or small loss
- Occasional fat-tail winning month
- **Do NOT scale up based on 1-3 months of data** — fat tails require longer
  observation

## If you want to pivot to Vilkov's approach

See `DAILY_LOG.md` "Vilkov 0DTE Trading Rules" section for the specific
implementable rules. You'd need:
1. SPX 0DTE options data (confirm Theta has SPXW)
2. Rewrite engine for 10:00 ET intraday entries
3. Implement L2-logistic regression classifier
4. 252-day expanding-window training
5. OOS from 2019 onwards

Budget: 1-2 weeks of focused work. SR 1.87 target is notable but
publication-bias haircut applies.

## Data inventory

```
data/historical/spy/    824 parquets (2023-01-03 → 2026-04-16)
                        All v2-enriched with Theta Standard Greeks
                        Size: ~1 GB
```
