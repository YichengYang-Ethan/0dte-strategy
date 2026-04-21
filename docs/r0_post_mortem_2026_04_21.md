# R0 Post-Mortem — CONFIRMED KILL (2026-04-21 01:30 CT)

**Triggered by:** `scripts/r0_check2_dumb_mae.py` + confirmed by
`scripts/r0_check2b_grid_sensitivity.py` (24-cell grid scan).

**UPDATE 2026-04-21 01:30 CT — measurement rescue FALSIFIED:** Grid
scan across 6 entry times × 4 windows produced **zero** cells where
any wall-based target beats spot-as-target. Not even a marginal pass.
The "measurement problem" hypothesis is dead; this is a mechanism
failure.

The decision space has collapsed from A/B/C to A only: **kill R0 and
pivot.**

---

## The failure numbers

```
                      ORIG_IS   ORIG_OOS   EXT_OOS    ALL (952d)
T_spot   MAE          (baseline across all buckets)
                        15.02     9.83      10.96      11.14
T1       (dominant wall)
         MAE           15.57     13.01      15.46      15.17
         vs T_spot       +3.7%     +32.4%     +41.1%     +36.2% WORSE
T2       (barycenter)
         MAE           15.29     11.04      12.76      12.86
         vs T_spot       +1.8%     +12.3%     +16.5%     +15.4% WORSE
T_disc   (argmax over walls + midwall)
         MAE           17.32     13.97      16.23      16.08
         vs T_spot      +15.3%    +42.2%     +48.1%     +44.3% WORSE
```

Every target, every bucket, worse than naive "spot will stay where
it is." No variant clears the 10% improvement bar. Several are
substantively worse (T_disc, T1 on EXT_OOS).

## What this tells us

On 952 days of SPXW 0DTE data, walls computed at 14:30 ET **do not
predict 15:55 ET spot** better than assuming spot stays flat. The
"pin" mechanism of GEX theory (SpotGamma, Barbon-Buraschi) is not
observable in this window on this data.

## But — is this a mechanism problem or a measurement problem?

### Case for mechanism problem (R0 truly dead)

1. The failure is **consistent across all three OOS buckets**. Not
   a period-specific artifact.
2. The effect direction is wrong in a way that matters: walls are
   systematically further from 15:55 close than 14:30 spot. That means
   the market is LESS pinned to walls than to its own inertia.
3. Barbon-Buraschi gamma-fragility is about intraday momentum in
   NEG_GAMMA states; it's not "walls always pin."
4. Adams 2024 Fed paper already warned dealer gamma carry is ~0
   (though our check3 partially counter-evidenced that).
5. the reference operator's +300% winners on 3.3% of days (check0) are not a "wall
   pin" story — they're a "spot moves a lot" story. Hitting a call
   OTM +300% requires spot to go UP, not stay pinned.

### Case for measurement problem (R0 rescuable)

1. **14:30 is the wrong entry time.** 0DTE gamma ramps exponentially
   in the last hour. Pin hypothesis is probably strongest 10:00-14:00
   when gamma is still building. By 14:30, call-wall / put-wall
   resistance may already be broken.
2. **95-minute window is too long for walls to matter.** Spot RV
   over 95 min ≈ 0.15% × spot ≈ 9 SPX points (matches T_spot MAE
   11.14). Walls are typically 20-50 SPX points from spot. For walls
   to improve on spot, pin must overcome RV — unlikely over an hour
   when the strike is OTM.
3. **T_disc implementation is simplified.** Per `ARCHITECTURE_R0_REBUILD.md`
   §1.2, T_disc should be weighted by `GEX × persistence`. Check2
   uses |GEX| only, no persistence window. Persistence is the whole
   reason walls "stick."
4. **the reference operator's holding window is 10-60 min, not 85 min.** check0 showed
   +300% target reachable within 60 min on 3.3% of days. Walls
   may predict 60-min spot better than 85-min spot.
5. **No `midwall` feasibility check.** The midwall candidate in T_disc
   is the strike nearest to `(call_wall + put_wall) / 2`, but there's
   no check whether that strike has meaningful GEX. If it's a low-GEX
   strike, it shouldn't be in the candidate set.

### Evidence tilt (ORIGINAL ANALYSIS — SUPERSEDED 01:30 CT)

The measurement-problem hypothesis WAS thought stronger, but was
empirically falsified by check2b grid scan.

### check2b findings (decisive, 01:30 CT)

Grid: 6 entry times × 4 windows × 3 targets = 72 improvement cells.

```
Best cell:    14:30/120min T2 (-15.38% — still worse than spot by 15%)
Worst cell:   11:00/30min  T_disc (-178.4%)
T_disc:       worst of all three variants in EVERY cell
T2:           least-bad of all three but never positive
T1:           uniformly terrible
```

**Count of cells where any target beats spot-as-target by ≥10%: 0
Count of cells where any target beats spot-as-target by any amount: 0**

**Interpretation:** there is no (entry_time, window) combination in our
data where GEX-wall-based targets predict future spot better than
assuming spot stays flat. The pin mechanism is not recoverable by
parameter choice.

### Reconciled story — check3 + check2 + check2b

Dealers are systematically net short gamma (check3 PASS). Their
hedging pressure must exist. But on 952 days × 24 parameter combos,
that pressure does NOT manifest as spot gravitating toward GEX walls.

Three possible reconciliations:
1. **Dealers hedge in ES futures, not cash SPX.** Pin happens in ES;
   cash SPX shows no pin because it's not the hedge instrument.
2. **Dealers are short gamma but also hedge continuously enough that
   residual pressure is washed out by RV.** Over any window ≥30min,
   realized vol > pin effect.
3. **NEG-gamma dealers produce momentum, not pin** — the classic
   Barbon-Buraschi result. Our R0 was built on the reverse assumption
   (walls as attractors). This would flip the entire formulation.

Reconciliation (3) is the most parsimonious and aligns with
Barbon-Buraschi 2021 + Adams 2024. It also explains why the reference operator's
winners cluster on high-movement days (check0 3.3% hit rate): in
NEG_GAMMA, dealers accelerate moves away from spot; the reference operator's
0.70Δ-call-in-NEG_GAMMA rule (v5) was accidentally capturing the
momentum, not the pin.

## Decision space (COLLAPSED after check2b)

Options B (rescue) and C (GPT Pro adjudication of mechanism-vs-measurement)
are no longer on the table. check2b empirically falsified the
measurement hypothesis. Only Option A survives, now with three pivot
branches:

### Option A1 — Momentum-not-pin restatement (most promising)

- Keep check3's dealer-short-gamma finding as load-bearing.
- REVERSE the R0 formulation: walls act as **momentum barriers**, not
  attractors. When spot approaches a wall in NEG_GAMMA, dealer
  hedging accelerates the move through/past the wall, not back to it.
- This aligns with Barbon-Buraschi 2021 gamma-fragility and with
  the reference operator's v5 rule surviving on NEG_GAMMA+pos<0.15 (spot near put wall →
  bounce AWAY, which is what a long-call captures).
- Next step: new test, "do wall-proximity events in NEG_GAMMA predict
  directional spot moves AWAY from the wall?"
- Risk: this is a new research spike, not a finished R0 rescue. But
  it's intellectually coherent.

### Option A2 — Signal engineering on raw features, no target formula

- Drop the target-prediction framing entirely.
- Build an entry rule on raw features (GEX state, pos_in_range, flow
  sign, ATM IV, overnight gap, VIX) without trying to predict a
  specific target level.
- This is essentially the reference operator's approach: confluence of features triggers
  entry into 0.20Δ OTM calls/puts; exit at −40% stop or EOD.
- Closer to what actually makes money (based on check0's 3.3% hit
  rate + V2's +378% median winner).
- Risk: more empirical curve-fitting exposure; need very strict OOS
  discipline (exactly what HANDOFF Ultra Review warned about).

### Option A3 — Abandon 0DTE research, redirect effort

- Redirect effort elsewhere.
- Archive the repo as "reverse-engineering case study + infrastructure
  library"; the leak_safe pipeline + 952-day data + 4-tier OOS
  framework are portable.
- Write up the project as a research artifact for resume / interview.
- Most honest option if R0 kill + R0 direction exhausted.

**Recommendation (PRE-check2c):** A1 first, then A2, then A3.

---

## UPDATE 2026-04-21 01:50 CT — check2c results collapse A1

check2c empirically tested momentum-vs-pin on NEG_GAMMA + extreme
wall-proximity days, 14:30→15:55 window:
- pin hit rate:      49.0%  (n=147 near put_wall)
- momentum hit rate: 49.7%
- mean return:       +0.018%  (random walk)

Neither pin nor momentum dominates intraday. v5's PF 1.23-1.77 (which
uses the same NEG_GAMMA + pos<0.15 rule) works at overnight 24h
horizon, not the intraday 85-min window. Its edge must be
Baltussen/Da/Soebhag 2024 retail-attention MR, NOT dealer-gamma
intraday.

**Revised pivot ranking (post-check2c):**

1. **A2 (practitioner-style feature engineering, strict OOS)** — most defensible.
2. **A3 (archive + writeup)** — most honest if we think A2 is dressed-up
   overfitting.
3. **A1 (momentum-not-pin rebuild)** — demoted. No empirical support
   at intraday horizon. Rebuilding it at 1DTE horizon is literally
   v5 under a new name.

**Core revision:** "rebuild R0 with a new thesis" is no longer a
useful option. Either we pivot to signal engineering (A2) or we
archive (A3). GPT Pro Round 7 brief should focus on A2 vs A3
adjudication.

## What we keep regardless

- V2 empirical finding (the reference operator +378% real, −40% stop correct)
- V3 (open-filter no microstructure support)
- V4 (§5 weak-trend free alpha falsified)
- check0 (payoff geometry feasible at 3.3% 60min / 9.7% full-day)
- check3 (dealer-sign stable across VIX, PASS)
- `docs/peer_bot_extracted_specs.md` (intel)
- `docs/peer_payoff_model.py` (V2-calibrated)
- `docs/strategy_delta_vs_peer.md` (§1/§3/§4 softened, §5 falsified)

All of the above remain valid whether we kill R0 or rescue it. No
rollback needed on this front.

## What we revert if R0 dies

- `ARCHITECTURE_R0_REBUILD.md` (entire file) — archive
- HANDOFF.md Actions 2-7 — superseded by pivot plan
- `src/pipeline/intraday_features.py` — already short-vol artifact,
  either archive or repurpose depending on pivot

## Timeline for decision (SIMPLIFIED)

- User reads this at 08:00 CT.
- GPT Pro Round 7 brief (UPDATED for post-kill pivot guidance) ready
  at `docs/gpt_pro_brief_2026_04_21_round7.md`.
- Paste brief + 3 attached files to GPT Pro, get pivot guidance.
- Decision on A1 / A2 / A3 by 10:00 CT.
- Then: either implement new research plan (A1), or write practitioner-style
  signal engineering plan (A2), or write project wrap-up (A3).

## One-paragraph summary for GPT Pro (UPDATED)

> 952 days of SPXW 0DTE data. check3 PASS: dealers systematically net
> short calls AND puts across all 3 VIX regimes, mag ratios 1.34x and
> 1.49x (stable short-gamma position). check2 KILL + check2b grid
> scan (24 entry×window combinations) empirically rules out measurement
> artifact: NO parameter choice allows wall-based targets (T1/T2/T_disc)
> to beat spot-as-target. Mechanism failure, not measurement. Dealer
> short-gamma exists; pin does not. R0 target-prediction thesis is
> dead. Options: (A1) revise to momentum-not-pin (Barbon-Buraschi
> gamma fragility); (A2) abandon target formula, do practitioner-style feature
> engineering; (A3) archive project. Which pivot is most defensible
> given the reconciled evidence?
