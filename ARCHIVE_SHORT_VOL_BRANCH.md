# Archive: Short-Volatility Exploratory Branch

**Status:** archived 2026-04-20. Not the active research path. Preserved for reference only.

## What this archive is

An exploratory research branch that surfaced during the intraday MVP work
and produced a statistically significant finding on **intraday realized
variance compression conditional on dealer-state proxy**
(`atm_gex_skew`). This is a real, leak-safe finding — but it is
**structurally unrelated** to the the reference operator 0DTE bot reconstruction that
drives the main branch.

## Git references

- **Tag:** `v2-short-vol-exploratory-archive` (at commit `05141d4`)
- **Branch:** `archive/short-vol-exploratory`
- **Main-branch files that are archive-related (kept in place, not deleted):**
  - `GPT_PRO_DAY2_5_UNEXPECTED.md` — brief that pivoted to volatility
  - `scripts/intraday_day2_5_diagnostics.py`
  - `scripts/intraday_day3_baselines.py`
  - `logs/day2_5_diagnostics.md`
  - `logs/intraday_day3_report.md`
  - `data/intraday_labels.parquet` (reusable)
  - `data/intraday_features.parquet` (short-vol-specific; superseded)
  - `data/pre_signal_realized_var.parquet`

## Findings summary

**Direction branch — confirmatory falsification:**
- 4 pre-registered baselines (flow-only, state-only, interaction,
  inverse-interaction) against `signed_ret_pct` at t=15:00 → 15:55 ET.
- Max sign concordance 52.39%, all Bonferroni p = 1.0 (N=12).
- Directional 0DTE thesis **dead** at this feature set and decision
  horizon.

**Volatility branch — exploratory (flagged per GPT Pro Day 2.5 verdict):**
- Persistence baseline (pre-15:00 realized variance) is dominant
  predictor of post-15:00 realized variance: Pearson r = 0.706,
  Spearman 0.805, R² ≈ 0.50.
- `atm_gex_skew` (dealer-state proxy) adds incremental R² over
  persistence:
  - vs `realized_var`: ΔR² = +0.0078, Pearson r = -0.132, Bonf p =
    0.0009
  - vs `abs_ret_pct`: ΔR² = +0.0136, Pearson r = -0.127, Bonf p =
    0.0019
- Sign matches Dim-Eraker-Vilkov 2024 prediction (MM gamma → lower
  intraday volatility).
- Quintile relationship is **not** monotonic — top-bucket compression,
  not clean gradient.

## Why this is archived rather than deleted

Per GPT Pro realignment verdict (2026-04-20):
> "Archive it as a legitimate separate branch. Do not delete it. Do not
> use it as evidence that the practitioner rebuild is working. Do not mix its
> thresholds/features into the the reference operator branch."

The finding is real. It is just not what the main research thread is
trying to build. Keeping it archived avoids:
1. Losing a genuine result.
2. Contaminating the practitioner reconstruction branch with short-vol
   artifacts.
3. Self-deception of treating this as evidence for the active thesis.

## Why the short-vol finding is not the main path

the reference operator's real bot (reconstructed from the field research transcript) is
structurally different:
- **Long gamma** (buy options), not short vol.
- **Event/structure-triggered** entry, not fixed 15:00 decision.
- Target = **predicted SPX closing point** (e.g. "7175", "7126"), not
  regression R².
- Instrument mix includes **butterflies**, not just ATM call/put.
- **Rule-based + grid search** on weighted features, not OLS.
- Feature set explicitly includes **Vanna total**, **call-wall /
  put-wall**, **ATM IV spike**, **net flow**, **bid/ask** — several of
  which were never built here.

See `ARCHITECTURE_R0_REBUILD.md` at repo root for the active path.

## If you ever want to revive this branch

```bash
git checkout archive/short-vol-exploratory
# or
git checkout v2-short-vol-exploratory-archive
```

Possible future directions from here (explicitly not pursued now):
- Short-straddle wrapper on V1 signal with conservative 5% round-trip
  friction. GPT Pro estimate: probably Sharpe 0.3-0.8 after costs,
  below the 1.0 economic bar.
- Residualize targets on pre-signal realized variance and retest V1
  contribution (Day 4 original plumbing check, not executed).
- Regime conditioning (VIX terciles, IV rank) to see if V1 edge
  concentrates in specific states.
