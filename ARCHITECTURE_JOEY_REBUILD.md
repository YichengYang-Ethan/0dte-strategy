# R0 — Architecture: Joey-Inspired 0DTE Reconstruction

**Status:** pre-registration. Frozen 2026-04-20. Any change during R1-R5
must be logged with date + reason in `CHANGELOG.md`.

This document resolves every ambiguity that GPT Pro flagged before
implementation starts. Implementation (R1-R5) must code against these
specs unchanged until the pipeline is feature-complete.

---

## 0. Mission statement

Reconstruct a Joey-inspired 0DTE trading system from WeChat transcript
extracts + public literature + own inference. **Not** a replication —
transcript does not give code-level spec, and Joey will not be asked
clarifying questions. The honest claim is **Joey-inspired
reconstruction**, not replication.

**Product shape:** rule-based, event-triggered, long-gamma system on
SPX / SPXW 0DTE, targeting ~1-hour holding periods, with instrument
selection (call, put, or butterfly) conditional on target geometry.

**Stop criteria are defined per-stage (R3, R4, R5).** System is killed
if any stage's gate fails. No rationalization of failed gates.

---

## 1. Target engine (the heart of the system)

### 1.1 What the target engine outputs

For each minute-bar t, produce:
- `T_t` — point estimate of where SPX is being "pinned" or "pushed"
  by dealer positioning
- `L_t, U_t` — lower / upper band around `T_t` (1 stddev under the
  combined state uncertainty)
- `confidence_t ∈ [0, 1]` — function of wall thickness, wall
  persistence, expiry-sliced vanna concentration, and flow
  corroboration

### 1.2 Target formula family (3 candidates, one chosen by R3 gate)

All three are pure geometric/structural combinations — **no OLS, no
learned coefficients**. Only integer weights with pre-declared signs.

**T1 — Dominant-wall target:**
```
T_t = spot-closer of {call_wall, put_wall}
      where "wall" = argmax_strike (|GEX_side(strike)|)
```

**T2 — Weighted-wall target (primary candidate):**
```
T_t = (w_c * CW + w_p * PW) / (w_c + w_p)
where
  w_c = GEX(call_wall) * thickness_c * persistence_c
  w_p = GEX(put_wall)  * thickness_p * persistence_p
  thickness_side = peak_GEX_side / total_GEX_side
  persistence_side = # minutes in last 30 where argmax stayed at that strike / 30
```

**T3 — Flow-adjusted weighted target:**
```
T_t = T2 + α * sign(net_flow_10m) * |net_flow_z|_clipped
where α is an integer in {1, 2, 3} (grid search), |.|_clipped to 3σ
```

All three produce a point estimate in SPX points. Band [L_t, U_t] is
defined uniformly as ±0.5 × ATM_straddle_price from the target.

### 1.3 Selection between T1/T2/T3

R3 kill gate (see §6.1) runs all three on untouched last-year data. One
target formula is chosen if and only if it clears the kill gate. If
more than one clears, pick the lowest-MAE one and report the others in
the final writeup.

---

## 2. Feature primitives (frozen)

All features are computed **at minute resolution** from 09:30 to 15:55
ET, leak-safe (never reads data from timestamp > t).

### 2.1 Wall definition

**Primary:** per-side argmax over strikes of |GEX|.
- `call_wall_t = argmax_strike (GEX_call(strike, t))`
- `put_wall_t = argmax_strike (GEX_put(strike, t))`

**Secondary fields:**
- `call_wall_gex_t`, `put_wall_gex_t` — GEX value at the wall
- `call_thickness_t = call_wall_gex_t / sum(|GEX_call|)`
- `put_thickness_t` — analogous
- `call_persistence_t` — fraction of last 30 minutes the argmax stayed
  at current strike
- `put_persistence_t` — analogous
- `call_wall_distance_t = (call_wall_t - spot_t) / spot_t * 100` (%)
- `put_wall_distance_t` — analogous

**Not used as primary:** top-3 sum, kernel-smoothed mode. (May be
added as robustness checks in R5 if primary fails.)

### 2.2 Vanna aggregation

**Primary formula (dealer-signed OI-weighted sum, expiry-bucketed):**
```
vanna_bucket_b_t = Σ_{strike, right} sign_mm(right, position) × OI × vanna(strike, right, t)
```

where `sign_mm(right, position)`: assume MMs are **short calls** and
**short puts** for customer-driven books (standard assumption; will be
flagged for violation in R5 robustness). Then:
- Long-vanna from MM side = -customer_vanna
- For 0DTE specifically, assume customer net-long gamma call/put flow
  → MM short gamma; sign absolute value positive = "MM exposed to up
  vol → spot move amplification"

**Expiry buckets:**
- `bucket_0` — same-day (0DTE)
- `bucket_1_7` — 1-7 days to expiry
- `bucket_8_30` — 8-30 days
- `bucket_31plus` — 31+ days

**Totals:** `vanna_total_t = Σ_buckets vanna_bucket_b_t`

**Why bucketed:** 2025 paper (SSRN 5641974) argues much of the 0DTE
hedging shift comes from longer-dated positions becoming 0DTE. Total
alone loses that distinction.

### 2.3 IV spike detection

Two separate features, both leak-safe:

**IV state filter (slow):**
```
iv_state_z_t = (ATM_IV_t - mean(ATM_IV_{t-30d..t-1d})) / std(ATM_IV_{t-30d..t-1d})
```
Daily resolution, rolling shift-1. `|iv_state_z_t| > 2` = elevated state.

**IV spike trigger (fast):**
```
iv_spike_z_t = (ΔIV_5m(t) - mean(ΔIV_5m_{trailing_100bars})) / std(ΔIV_5m_{trailing_100bars})
```
Intraday resolution, where `ΔIV_5m(t) = ATM_IV_t - ATM_IV_{t-5min}`.
`iv_spike_z_t > 2` = spike trigger fires.

### 2.4 Abnormal flow

Per-minute signed flow (call flow - put flow, delta-weighted), cutoff
at 15:55:
```
abn_flow_z_t = (flow_10m_t - mean(flow_10m_{trailing_100bars})) / std(...)
```
`abn_flow_z_t > 2` = abnormal bullish,  `< -2` = abnormal bearish.

### 2.5 ES futures proxy (hedge venue)

**Why:** SPX is cash-settled / European. Public pinning literature
points to futures as the real hedge vehicle. Without an ES-side
signal, the system can only see the option leg, not the hedge leg.

**Data question (needs R1 verification):** does the existing Theta
Data subscription include ES futures? If not, either:
- Use SPX spot as the tradeable proxy (standard assumption) with
  explicit flag that hedge venue is unobserved, OR
- Abort ES integration and rely purely on SPX option structure + spot.

**R0 decision:** start without ES proxy. Revisit only if R3 kill gate
passes and R4 is on track. This is an explicit known-unknown, not an
assumption.

---

## 3. Entry trigger framework (confluence required)

### 3.1 Trigger primitives (5 indicators, each ±1/0)

Each produces a ternary signal at time t:
- `trigger_wall_cross_t` — spot just crossed call/put wall boundary
  (from outside → inside gives +/-1 depending on direction; else 0)
- `trigger_iv_spike_t` — `|iv_spike_z_t| > 2`, sign matches IV
  direction
- `trigger_vanna_flip_t` — `vanna_total_t` crossed zero (flipped sign)
  in last 10 minutes
- `trigger_flow_confirm_t` — `|abn_flow_z_t| > 2`, sign matches target
  direction
- `trigger_wall_distance_t` — `|spot_t - T_t| / ATM_straddle > 0.5`
  (displacement view possible)

### 3.2 Confluence score

```
confluence_score_t = Σ_i w_i * trigger_i_t
```
where `w_i ∈ {1, 2, 3}` (integer grid search) and signs pre-declared:
- wall_cross: + in cross direction
- iv_spike: + if matches target direction
- vanna_flip: + in direction of flip
- flow_confirm: + in flow direction
- wall_distance: + if target is farther than 0.5 straddle from spot

**Entry rule:** `|confluence_score_t| ≥ threshold` (grid search
threshold in {3, 4, 5}) **AND** `confidence_t > 0.5`.

No single-trigger entries. Minimum 2 non-zero triggers.

---

## 4. Instrument chooser

Decision at entry time t, based on `d_t = (T_t - spot_t) / ATM_straddle_price_t`:

| Condition | Instrument | Rationale |
|-----------|------------|-----------|
| `|d_t| < 0.3` | **Centered butterfly** at `T_t` | pin view; cheap exposure to point location |
| `0.3 ≤ d_t ≤ 1.5` | **ATM call** (if `d_t > 0`) or **ATM put** (if `d_t < 0`) | travel view |
| `|d_t| > 1.5` | **Skip trade** | too far, low probability within 1 hour |

Butterfly spec: body strike = `T_t`, wings = body ± 25 SPX points.

---

## 5. Exit logic (dynamic)

Evaluated each minute after entry. First condition to fire wins:

1. **Target hit:** spot reaches `T_t` (or crosses it by 2+ points) →
   exit at current mid.
2. **Structure fail:** `confluence_score_t` sign flipped OR wall_t
   moved by ≥ 0.25 × initial wall distance → exit.
3. **Vanna/flow reversal:** both `trigger_vanna_flip` and
   `trigger_flow_confirm` now against position → exit.
4. **Profit target:** premium ≥ 2.0 × entry_premium → exit.
5. **Stop-loss:** premium ≤ 0.4 × entry_premium → exit.
6. **Time stop:** 120 minutes after entry OR 15:45 ET (whichever
   sooner) → exit.

---

## 6. Evaluation gates

### 6.1 R3 kill gate — dumb target engine

Before any options P&L, the target engine must beat three dumb
baselines on untouched last-year data:
- **Baseline A (spot-as-close):** `T_t = spot_t` (i.e., "no move")
- **Baseline B (nearest wall):** `T_t = argmin({|call_wall - spot|, |put_wall - spot|})`
- **Baseline C (wall midpoint):** `T_t = (call_wall + put_wall) / 2`

**Evaluation target:** SPX close price (spot at 15:55 ET).

**Pass criteria (both required):**
1. Target engine MAE to close ≤ 0.90 × best-baseline MAE (i.e., at least
   10% lower error)
2. Sign accuracy of `sign(T_t - spot_t)` vs `sign(close - spot_t)` at
   t=14:30 is >53%

**Fail:** STOP rebuild. Revert to archived short-vol branch or kill
project entirely.

### 6.2 R4 kill gate — conservative-fill PnL

Using **ask-in, bid-out** fills (no mid fantasy) and the exit rules in
§5, the baseline trade family must show positive expectancy on
untouched last-year data.

**Pass criteria (all required):**
1. Expectancy > 0 after fills
2. Winners are at least **1.5×** average losers (payoff asymmetry
   intact)
3. Drawdown on tail day < -3 × average loss

**Fail:** STOP.

### 6.3 R5 kill gate — grid search stability

Nested walk-forward: 4 outer folds × 3 inner folds over the 4-year
sample. Inner folds select weights / thresholds. Outer folds evaluate.

**Pass criteria (all required):**
1. Best rule does not sit at grid edges on any parameter
2. Best rule keeps same sign structure across all 4 outer folds
3. Best rule Sharpe > 1.0 on aggregated outer-fold PnL
4. Deflated Sharpe ratio > 0 (accounts for search multiplicity)

**Fail:** STOP.

### 6.4 Stop-don't-rationalize rule

If any gate fails, **do not**:
- Change the gate threshold to "just barely pass"
- Change the baseline set to make target engine look better
- Add post-hoc features to rescue a failed target

Stop means stop. Write post-mortem. Pick B (archive short-vol) or C
(kill project).

---

## 7. Pre-registration ledger

| Parameter | Fixed value | When grid-searched | Notes |
|-----------|-------------|---------------------|-------|
| Decision resolution | 1-minute bars | — | leak-safe |
| Cutoff | 15:55 ET | — | per leak-safe module |
| ATM range | ±1% of spot | — | consistent with prior |
| Wall definition | argmax single strike | — | §2.1 primary |
| Vanna aggregation | OI × dealer-sign | — | §2.2 primary |
| Expiry buckets | {0, 1-7, 8-30, 31+} | — | §2.2 |
| IV spike window | 5 min change, 100-bar rolling | — | §2.3 |
| Flow window | 10 min, 100-bar rolling | — | §2.4 |
| Target formula | T1, T2, or T3 (R3 selects one) | R3 | §1.2 |
| Confluence weights | w_i ∈ {1, 2, 3} each | R5 inner fold | §3.2 |
| Confluence threshold | {3, 4, 5} | R5 inner fold | §3.2 |
| Flow adjustment α | {1, 2, 3} (if T3) | R5 inner fold | §1.2 |
| Instrument boundaries | 0.3, 1.5 straddle | — | §4 |
| Butterfly wings | ±25 SPX points | — | §4 |
| Exit: profit target | 2.0 × entry premium | — | §5 |
| Exit: stop-loss | 0.4 × entry premium | — | §5 |
| Exit: time stop | 120 min or 15:45 | — | §5 |

Grid-searched parameters have a bounded, small search space (5 weights
× 3 values × 3 thresholds × 3 α values = 405 combinations max). Grid
results all reported, not just winner.

---

## 8. Deliverable schedule

| Stage | Deliverable | Duration |
|-------|-------------|----------|
| R1 | `vanna_bucketed.parquet` (minute-level, expiry-bucketed) | 1 day |
| R2 | `structural_features.parquet` (walls, IV spike, flow) | 2 days |
| R3 | Target engine + kill gate; STOP or GO | 2 days |
| R4 | Conservative-fill PnL simulation; STOP or GO | 2 days |
| R5 | Nested walk-forward grid search; STOP or GO | 3 days |
| Total | | ~10 days |

Each R has a written post-report. Each kill gate has an auditable pass
or fail verdict — not a narrative.

---

## 9. Explicit known-unknowns

Listed here so they are not forgotten or rationalized later:

- **Hedge venue (ES futures)** — unobserved. System sees option leg,
  not futures leg. May systematically miss edge.
- **Pinning asymmetry** — Golez & Jackwerth found stronger effects
  pushing from below toward ATM. Not modeled in T1/T2/T3.
- **Dealer position sign** — assumed MMs are short from customer
  books. If wrong, vanna sign is inverted.
- **Massive.com L2** — Joey uses streaming L2; this rebuild uses
  Theta Data historical parquet. Fundamental structural difference;
  tick sequencing may differ.
- **Price-target specification** — Joey in transcript gives exact
  integer targets (7175, 7126). This rebuild produces continuous
  T_t. Unknown whether exact-integer pin logic is more predictive.
- **Search multiplicity** — nominally 405 combinations, but R3 also
  picks among 3 target formulas. True search space is larger than it
  appears; Deflated Sharpe accounts for this.
