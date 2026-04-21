# Independent Validation Plan — Runs in Parallel with GPT Pro Review

**Purpose:** while GPT Pro is falsifying the reference-operator intel and the 5 free-win
claims, run a separate, code-first validation that tests the same claims
against the 952-day SPXW 0DTE dataset already on disk. This produces
empirical evidence — not opinion — against which GPT Pro's verdict can
be cross-checked.

**Principle:** GPT Pro's answer is theoretical. This plan is empirical.
If they disagree, we trust the data.

**Gate:** this plan does NOT violate HANDOFF.md's R1-R5 code freeze.
Every task below is diagnostic / benchmarking of existing primitives,
not new signal engineering. HANDOFF Action 2–4 (r0_check1/2/3) remain
the gate for R1-R5 code.

---

## Codebase reality (from deep review, 2026-04-20)

Before designing this plan I re-read the code:

- `src/pipeline/leak_safe.py` (439 LOC): intraday leak-safe primitives
  exist but are NOT plumbed into `src/signal/generator.py`.
- `src/signal/generator.py` (152 LOC): **still v5 swing_1dte rule**.
  Not an intraday 0DTE generator.
- `src/risk/manager.py` (152 LOC): already has quarter-Kelly, VIX scaling,
  direction penalty, **`max_daily_loss=$500`**, **`max_trades_per_day=5`**,
  `no_trade_before="09:45"`. My `strategy_delta_vs_peer.md` §1 incorrectly
  claimed we don't have a daily loss cap — we do.
- `src/backtest/fill_simulator.py` (192 LOC): round-trip spread cost ≈ 57%
  of full spread. the reference operator live pays 100%. Our backtest is 43% optimistic.
- `src/backtest/engine.py` (713 LOC): hard-coded swing_1dte, no intraday mode.
- Data: 468,887 parquets, 2022-07-01 to 2026-04-16, including per-strike
  `quote/` directories at minute resolution.

So my working assumption going into this plan:
**I have leak-safe intraday primitives + 3.5 years of minute-level quote
data on disk, but no intraday backtest engine. R0 conceptually pre-registered,
not implemented.**

---

## Validation tasks (ordered, numbered, with kill criteria)

### V1 — Fill simulator calibration against the reference operator live

**File:** `scripts/validate_v1_fill_calibration.py` (new)
**Effort:** 2 hours
**Data:** existing 952-day quote parquets

Add two modes to `FillSimulator`:
```
mode="current"      entry=mid+17.5%spread exit=mid-40%spread    # today's default
mode="joey_live"    entry=ask             exit=bid              # the reference operator's actual
mode="resilient"    the reference operatorFillPolicy.exit_sequence                # what I want to ship
```

Run v5 signal on last 118 days (ORIG_OOS) under all 3 modes. Report:
- PF under each mode
- PF delta `current` → `joey_live` (should be negative)
- PF delta `joey_live` → `resilient` (should be ≥ 0 — otherwise resilient doesn't help)

**Kill:** if `joey_live` PF < 0.9 × `current` PF, our backtest has been
systematically optimistic and all v5 numbers upstream need a footnote.

**Expected finding:** `joey_live` is 15–25% worse than `current` on PF. If
smaller, our backtest was actually closer to the reference operator than I thought. If larger,
v5's 4-tier validation was measuring a fill-advantage we don't have live.

---

### V2 — the reference operator payoff model sanity check on real data

**File:** `scripts/validate_v2_payoff_empirical.py` (new)
**Effort:** 3 hours
**Data:** 952-day quotes

`docs/peer_payoff_model.py` claims:
- loss = −40% of premium (hard stop)
- typical win = +300% gross
- break-even WR by regime in `summary_table()`

Build a **model-free trade simulator** that:
1. Picks a synthetic 0DTE call at 0.20Δ, entered at 09:45, exited at 15:55
2. For each of 952 days, records simulated loss % and win % at different
   stop levels: none, −40%, −60%, −100% (i.e. hold to expiry)
3. Fits empirical distribution `loss_pct | side=loss` and `win_pct | side=win`
4. Compares empirical to the reference operator's claim (−40% / +300%)

**Kill:** if empirical median win < +150% gross, the reference operator's +300% is either
(a) conditional on the reference signal (in which case it's not
our baseline), (b) survivorship memory, or (c) per-contract cherrypicking.
Either way the `peer_payoff_model.py` numbers need adjustment.

**Expected finding:** empirical median win is probably +80–150% on
**unconditional** 0.20Δ 0DTE call, with fat right tail extending to
+500%+. the reference operator's +300% is likely the conditional-on-his-signal number,
which is fine — but it means we can't use +300% as an unconditional
baseline.

---

### V3 — Opening 15-min no-trade empirical support

**File:** `scripts/validate_v3_open_filter.py` (new)
**Effort:** 1 hour
**Data:** 952-day quotes

reference-operator intel #17: "no signals in first 15 min".

Compute per-minute GEX + wall stability on first 30 minutes of each day.
Report:
- 09:30–09:45 wall-level change variance (should be high = unstable)
- 09:45–10:00 wall-level change variance (should be lower)
- 10:00+ variance

**Kill:** if 09:30–09:45 variance is NOT significantly higher than
10:00+, the reference operator's 15-min filter is cargo-culted and we should not copy.

**Expected finding:** 09:30 walls are noisy because spot + OI settle
slowly post-open. the reference operator's rule is probably empirically sound. This
validates copying it to our intraday generator.

---

### V4 — Weak-trend prospective identification test

**File:** `scripts/validate_v4_weaktrend_prospective.py` (new)
**Effort:** 4 hours
**Data:** 952-day quotes + daily OHLC

This directly tests the "free alpha" claim in `strategy_delta_vs_peer.md` §5.

Build two regime classifiers:
- **Retrospective:** label day as `weak_trend` if `(high_full_day − low_full_day) / vwap < 0.6 × ATR20`
- **Prospective (what we claim):** label day as `weak_trend` at 10:00 ET
  using only 09:30–10:00 data (first 30 min realized range + opening gap + overnight vol)

Compute agreement matrix. Report:
- Prospective accuracy: what % of retrospectively-weak days does
  prospective correctly pre-classify at 10:00?
- Prospective precision: when prospective says weak at 10:00, what % actually end weak?

**Kill:** if prospective precision < 55% or recall < 40%, the 10:00
classifier is ~noise and the "free alpha" disappears. We'd be better
off trading all regimes and relying on our risk layer.

**Expected finding:** prospective classifier is moderately good (60–70%
precision/recall). This lets us ship a weak-trend gate with controlled
false-negative rate.

**Critical:** this is the single most important validation task.
If V4 fails, `strategy_delta_vs_peer.md` §5 is deleted entirely.

---

### V5 — Trigger density dry-run with current primitives

**File:** `scripts/validate_v5_trigger_density.py` (new)
**Effort:** 2 hours
**Data:** 952-day quotes + `src/gex/calculator.py`

This is essentially HANDOFF Action 2 (`r0_check1_trigger_density.py`) but
slightly different in scope: **use the CURRENT generator's rule** (v5
NEG_GAMMA + pos<0.15 BULLISH) instead of R0's unwritten trigger primitives.
Goal: see how close v5 already is to the reference operator's 3–5/day baseline.

Compute per-day entry count. Report:
- Median entries/day
- p95 entries/day
- Days with 0 entries %
- Days with ≥1 entry %

**Kill:** if median entries/day < 0.2 (one entry per 5 days) under v5,
our signal is too strict for the 3–5/day benchmark and the architectural
gap is signal-side, not primitive-side.

**Expected finding:** v5 fires on maybe 15–25% of days (too rare). Means
when we ship R0 intraday, we need a genuinely different trigger stack,
not just v5 reimplemented at minute resolution.

---

### V6 — the reference operator's −40% stop empirical distribution

**File:** `scripts/validate_v6_stop_distribution.py` (new)
**Effort:** 2 hours
**Data:** 952-day quotes

For every v5 signal in the last 232 days (original IS+OOS), record
**minute-by-minute** option price path from entry to exit. Compute:
- % of trades that ever touched −40% (would have been stopped)
- Of those, % that would have recovered to profit if not stopped
- Of those, avg PF with −40% stop vs no stop

**Kill:** none — diagnostic only. But a strong finding ("−40% stops
out 35% of eventual winners") means the reference operator's stop rule is regime-specific,
probably overfit to 2025–2026, and we should NOT copy it uniformly.

---

## Total time budget

- V1: 2 hours
- V2: 3 hours
- V3: 1 hour
- V4: 4 hours ← critical, do first
- V5: 2 hours
- V6: 2 hours

**Total: 14 hours** — 2 focused days of work. Can be parallelized with
GPT Pro review which takes 1 day wall-clock.

## Execution order

1. **Day 1 morning**: paste `gpt_pro_brief_2026_04_20.md` into GPT Pro.
   While waiting: start V4 (weak-trend prospective). This is the load-bearing
   validation — if it fails, §5 of `strategy_delta_vs_peer.md` dies regardless
   of GPT Pro's answer.
2. **Day 1 afternoon**: V1 + V3 in parallel.
3. **Day 1 evening**: read GPT Pro response; cross-check against V1/V3/V4
   findings. Write brief reconciliation doc noting where data disagrees with
   theory.
4. **Day 2**: V2 + V5 + V6. Decide final shape of amendments to
   `strategy_delta_vs_peer.md` and `ARCHITECTURE_R0_REBUILD.md`.
5. **Day 3**: HANDOFF.md Action 1 (T_disc amendment) using all accumulated
   evidence — GPT Pro + V1-V6 combined.

## What this plan deliberately does not do

- Does not write any new signal rule
- Does not run any new backtest beyond parameter sweeps on existing v5
- Does not touch `src/signal/generator.py` or `src/backtest/engine.py`
- Does not download new data
- Does not upgrade data providers
- Does not rewrite `fill_simulator.py` (calibration only; the
  `the reference operatorFillPolicy` / `ResilientFillPolicy` classes live under `POST-CHECK` gate)

## Exit criteria for this plan

After V1–V6 + GPT Pro response, I should have a one-page
`docs/validation_summary_2026_04_21.md` with:
- the reference operator claims that survived empirical + theoretical review → baseline accepted
- the reference operator claims killed by data → removed from `peer_payoff_model.py`
- Strategy-delta items that survived → promoted to R3–R5 scope
- Strategy-delta items killed → deleted from `strategy_delta_vs_peer.md`

Only then do I touch HANDOFF Action 1 (T_disc amendment).

---

## Reference

- GPT Pro brief: `docs/gpt_pro_brief_2026_04_20.md`
- reference-operator intel source: `docs/peer_bot_extracted_specs.md`
- the reference operator payoff model: `docs/peer_payoff_model.py`
- Optimization map: `docs/strategy_delta_vs_peer.md`
- Session plan: `HANDOFF.md`
