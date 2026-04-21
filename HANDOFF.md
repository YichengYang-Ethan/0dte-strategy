# Handoff — Current State and Next Actions

**Last updated:** 2026-04-21 08:30 CT — **PROJECT ARCHIVED**

## ⚠️ ARCHIVE NOTICE (2026-04-21)

The R0 thesis was empirically falsified on 952 days of SPXW 0DTE
data. A2 pilot rescue attempt also failed. Per pre-registered GPT Pro
Round 7 commitment, the project is archived. **No further R1–R5
development. No A2 expansion. No A1 rebuild.**

**Start here:** `docs/R0_RIP_2026_04_21.md` — terminal research artifact.
Then `docs/validation_summary_2026_04_21.md` — full empirical trail.

The sections below reflect the research state as of 2026-04-20 before
the archive decision. Preserved for historical context.

---

This document is the **single source of truth** for anyone picking up
this project. Read this first. Then read `README.md` for the full
timeline.

---

## Where we are right now

The project has cycled through 4 rounds of external review with GPT Pro
and 1 successful Ultra Review. All findings pointed to the same
direction:

1. **Daily/overnight branch** — falsified (M1-M4, Baseline 1 v1-v3).
2. **Intraday direction branch** — falsified (Day 3 baselines, max
   concordance 52.39%, Bonferroni p = 1.0).
3. **Intraday volatility branch** — archived as exploratory finding.
   V1 atm_gex_skew → realized_var, ΔR² = +0.008 over persistence,
   Bonferroni p = 0.0009. Real but too small to clear short-straddle
   friction.
4. **practitioner-inspired reconstruction** — R0 architecture pre-registered
   in `ARCHITECTURE_R0_REBUILD.md`. Not yet executed.

Ultra Review (completed technically, but the ultraplan command had
container issues on 2026-04-20) returned the following verdict:

### Ultra Review — Three-Layer Verdict (clean technical version)

- **Layer 1 (R0 architecture)**: Methodologically disciplined
  scaffolding, but the T1/T2/T3 target formula produces continuous
  barycenters while the reference operator's transcript cites integer pin levels
  (7175, 7126) — and three load-bearing mechanism questions (ES hedge
  venue, pinning asymmetry, MM dealer-sign) are parked in §9 as
  known-unknowns rather than promoted to primary features.

- **Layer 2 (methodology across 1 month)**: Strongest part of the
  repo — leak_safe.py passes genuine future-poison tests, the
  median-spot leak was caught and Sharpe correctly collapsed from
  3.45 to 0.05, M1-M4 and Day-3 direction branches were killed
  without rationalization, and the Day-2.5 "direction confirmatory /
  volatility exploratory" split was honestly disclosed as
  data-contingent and Bonferroni-12 corrected.

- **Layer 3 (practitioner reconstruction viability)**: Transcript +
  Theta-REST parquet cannot reconstruct the reference operator's claimed Sharpe 3 —
  the L2-WS to 1-min-REST gap is qualitative, not quantitative, for
  an event-triggered "unusual flow before headlines" bot. Honest
  upper bound is Sharpe 0.5-1.0 on whatever residual dealer-pinning
  edge survives minute-bucketed aggregation; that is a different
  product from what the reference operator runs.

---

## Ultra Review — Ranked R0 Changes (5 total)

Before executing any R1-R5 code, `ARCHITECTURE_R0_REBUILD.md` must
be amended:

1. **Make the target discrete, not continuous.** Replace T2
   weighted-wall barycenter with `T_disc = argmax` over candidate
   strikes `{call_wall, put_wall, midwall, most-persistent-wall-30min}`
   weighted by GEX × persistence. the reference operator's transcript says "pinned to
   7175", not "pinned to 7163.4."

2. **Promote §9 known-unknowns to §2 primary features.** MM
   dealer-sign, pinning asymmetry (Golez-Jackwerth upward bias), and
   ES-basis each flip features or targets by sign. They cannot be
   deferred. Build a 1-day sign-validator script before R1:
   aggregate customer 0DTE flow and test whether "MM short calls AND
   short puts" holds or is regime-varying.

3. **Insert a 3-day viability pre-check before R1.** Three scripts
   must all pass before any R1-R5 code runs:
   - `scripts/r0_check1_trigger_density.py` — per-trigger firing
     rate + confluence score distribution. Kill if median day has 0
     entries or every day has >5 entries.
   - `scripts/r0_check2_dumb_mae.py` — T_disc / T2 / spot-as-target
     MAE vs 15:55 close on untouched last-year data. Kill if no
     variant beats spot-at-14:30 by >=10% MAE reduction.
   - `scripts/r0_check3_dealer_sign.py` — MM dealer-sign stability
     across VIX regimes. Kill if regime-varying with no stable sign.

4. **Calibrate kill gates against actual baselines, not round
   numbers.** R5 "Sharpe > 1.0" is meaningless because unconditional
   long SPX clears 0.93 on this window. Restate as "Sharpe > 1.0 net
   of unconditional long SPX" or "Deflated Sharpe Ratio > 0 after
   subtracting long-beta." Same for R3.

5. **Collapse the "fixed vs grid-searched" ledger.** 8 knobs
   currently declared fixed are actually tunable:
   `iv_spike_z=2, persistence_window=30min, flow_window=10min,
   trailing_bars=100, α∈{1,2,3}, wall=argmax-single-strike, ATM±1%,
   butterfly_wings=±25pts, exits at 2.0× / 0.4× / 120min`. Every
   magic number must be either grid-searched-and-DSR'd or
   pre-justified from literature citation. Current state launders
   ~8 free parameters into "fixed," which the DSR in R5 will not
   account for.

---

## Ultra Review — Kill-or-Continue Verdict

**Neither "kill the project" nor "execute R0 unchanged" is correct.**

- Running R0 as-is burns 10 days on an architecture whose target
  formula does not encode the stated mechanism.
- Killing the project discards leak-safe plumbing and a clean
  falsification trail that genuinely narrowed the search space.
- Short-vol branch is not a revival candidate. Below economic bar.

**Correct path**: 3-day pre-check, then decide. Run viability checks
from change #3 above. If all three pass, amend R0 per #1, #2, #4, #5,
then run R1-R5. If any check fails, kill the practitioner reconstruction
entirely. Do not pivot to a "lighter the reference operator" or revive short-vol.

---

## This Week — Numbered Actions

0. **DONE 2026-04-20 evening**: Reverse-engineered the reference operator's live 0DTE bot
   from field research (18 parameter observations). Outputs:
   - `docs/peer_bot_extracted_specs.md` — source of truth for the reference operator's
     system parameters (sizing, fill, stops, costs, frequency,
     regime behavior, architectural gaps).
   - `docs/peer_payoff_model.py` — executable baseline. Run directly
     to print break-even WR by regime. **Weak-trend BE WR = 58.3%.**
   - `docs/strategy_delta_vs_peer.md` — five concrete optimization
     points with file paths, pseudocode, and intel-number rationale.

   **Benchmarking rule going forward:** R1–R5 validation must report
   performance by regime bucket, and the bar for success on weak-trend
   days is "better than no-trade," not "better than the reference operator's PnL" —
   because the reference operator likely loses money on weak-trend days himself. Systematic
   weak-trend no-trade gate is the single largest free engineering win
   this intel exposed. See `strategy_delta_vs_peer.md` §5.

1. **Today**: Rewrite `ARCHITECTURE_R0_REBUILD.md` §1.2 to add
   T_disc as the fourth target candidate, demoting T2 barycenter to
   robustness. Single commit before any code.

**Ordering reorganized 2026-04-21 per GPT Pro Q3 verdict**: check0
(payoff geometry) inserted before existing checks; remaining checks
reordered to check3→check2→check1 because dealer sign is load-bearing
mechanism, trigger density is tuning. Original Action numbers preserved
below for traceability.

2. **Day 2 (was Day 2)**: `scripts/r0_check0_payoff_geometry.py` —
   **NEW, GPT Pro 2026-04-21 recommendation**. Pure pathwise feasibility
   check. On 952 days of existing 0DTE data, measure whether the reference operator's
   claimed payoff (+300% gross before −40% stop within 10-60 min hold)
   is mechanically reachable at all. Written and running. Kill if target
   hit rate <3% of days, or >80% concentrated in top-3-months. V2
   already partly addressed this with +378% median win on full-day hold;
   check0 tests the shorter 10-60 min window specifically.

3. **Day 3 (reordered — was Action 4)**: `scripts/r0_check3_dealer_sign.py`.
   Using `compute_day_flow_leak_safe` across all ~950 days, test whether
   customer net call-side and put-side are systematically long or short,
   broken out by VIX regime. Per HANDOFF §9: dealer sign flips features
   and targets, cannot be deferred.

4. **Day 4 (reordered — was Action 3)**: `scripts/r0_check2_dumb_mae.py`.
   At t=14:30 on last-year data (untouched), compute T_disc, T2, and
   spot-as-target. Report MAE vs actual 15:55 close.

5. **Day 5 (reordered — was Action 2)**: `scripts/r0_check1_trigger_density.py`.
   Per-trigger firing rate, confluence-score distribution, number of
   days producing ≥1 entry candidate with confluence ≥3. Per GPT Pro
   Q2.4: the reference operator's 3-5/day is a sanity bound, NOT a tuning target.
   Validation requires future-only utility (check2 MAE or post-entry
   expectancy) to improve monotonically as threshold moves; if only
   trade count changes, cargo cult.

6. **Day 6 — Decision point**: If checks 0/1/2/3 all pass, amend R0
   §1, §2, §6, §7, §9 in a single commit with a `CHANGELOG.md`
   entry dated before R1 starts. If any fail, write a post-mortem
   and stop. Do not revive the short-vol branch. Do not pivot to a
   lighter the reference operator.

7. **Do NOT touch R1-R5 code** until checks 0/1/2/3 all pass.

---

## Critical files to read (in order)

1. `README.md` — full project timeline, falsification history
2. `docs/peer_bot_extracted_specs.md` — the reference operator's system reverse-engineered (Action 0 output)
3. `docs/strategy_delta_vs_peer.md` — five optimization points, prioritized
4. `docs/peer_payoff_model.py` — runnable reference baseline
5. `ARCHITECTURE_R0_REBUILD.md` — R0 pre-registration (NEEDS AMENDMENTS per #1-#5 above)
6. `ARCHIVE_SHORT_VOL_BRANCH.md` — why short-vol is archived
7. `GPT_PRO_REALIGN_PATH.md` — most recent external review brief
8. `logs/intraday_day3_report.md` — direction falsification numbers
9. `logs/day2_5_diagnostics.md` — where volatility signal surfaced
10. `src/pipeline/leak_safe.py` — leak-safe primitives (reusable)

---

## What NOT to do

- **Do not execute R1-R5 as currently written in `ARCHITECTURE_R0_REBUILD.md`.**
  The target formula is wrong; the known-unknowns are deferred instead of measured.
- **Do not revive the short-vol branch.** Bonferroni-surviving rounding error.
  Below economic bar after short-straddle friction.
- **Do not pivot to a "lighter the reference operator."** Ultra Review explicitly rejects
  sunk-cost softening.
- **Do not skip the 3-day pre-check.** It exists specifically to answer
  whether R1-R5 can possibly pass before burning 10 days.

---

## Known technical state

### Data

- **Theta Data Pro ($40/mo)**: 952 days SPXW 0DTE, ATM±3% strike range,
  ~16 GB of parquet files at `data/historical_0dte/` (gitignored).
- **IB Gateway paper** (port 4002, DUH719324): not yet connected.

### Code

- `src/pipeline/leak_safe.py` — leak-safe primitives:
  - `close_spot_leak_safe`, `compute_day_flow_leak_safe`
  - `rolling_zscore_shifted`, `intraday_spot_series_leak_safe`
  - `realized_variance_leak_safe`, `intraday_labels_leak_safe`
  - `future_poison_test` — core verification harness
- `src/pipeline/intraday_features.py` — feature extraction
  (short-vol-specific; archive candidate for rewrite per R0 changes)

### Parquets (not in git)

- `data/intraday_labels.parquet` (1904 rows) — reusable for R0
- `data/intraday_features.parquet` (1904 × 30) — short-vol artifact, superseded
- `data/pre_signal_realized_var.parquet` — reusable for R0 Check 2

### Git state

- Branch: `feature/0dte-intraday` (active work) + `main` (synced)
- Archive: tag `v2-short-vol-exploratory-archive`, branch `archive/short-vol-exploratory`
- Prior archive: tag `v1-1dte-archive`

---

## Ultra Review artifacts in this repo

- `ULTRA_REVIEW_PROMPT.md` — the prompt used for Ultra Review
- Ultra Review verdict text was pasted into chat; its ranked changes
  are summarized above in this document (authoritative).

---

## Session handoff protocol

For the next Claude session (new account or otherwise):

1. Open this repo: https://github.com/YichengYang-Ethan/0dte-strategy
2. Read `HANDOFF.md` (this file) first.
3. Read the "Critical files to read" list above, in order.
4. Do NOT execute any R1-R5 code.
5. Current task = Action 1 in "This Week — Numbered Actions":
   amend `ARCHITECTURE_R0_REBUILD.md` per Ultra Review's 5 ranked
   changes, starting with §1.2 T_disc addition.

If anything in this document contradicts `ARCHITECTURE_R0_REBUILD.md`,
**this document wins** — the architecture doc has not yet been updated
with Ultra Review's 5 changes. That update is Action 1 of this week.
