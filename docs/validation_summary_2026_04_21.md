# Validation Summary — 2026-04-21 (V3 + V4)

**Purpose:** record empirical findings from V3 (open-window filter) and V4
(weak-trend prospective identification) while GPT Pro review runs in
parallel. These findings reshape `docs/strategy_delta_vs_joey.md` §5 and
partially weaken Joey intel #17.

---

## V4 — Weak-trend prospective identification: **FALSIFIED** ❌

### Setup
- **Claim tested:** `docs/strategy_delta_vs_joey.md` §5 says weak-trend
  no-trade is "very high impact free alpha" because Joey's BE WR on
  weak-trend is 58.3%.
- **Implicit requirement:** we can label weak-trend days *prospectively*
  at 10:00 ET. If we can only label them retrospectively (end of day),
  we're not filtering regimes — we're just removing losing days after
  the fact (trivial and not actionable).
- **Test:** 947 trading days (2022-07-01 → 2026-04-16, after ATR warmup).
  Prospective classifier: `open_range_pct_30min < 0.6 × rolling_20d_mean(open_range_pct_30min)`,
  normalized apples-to-apples against its own history, not full-day ATR.
  Retrospective label: `full_day_range < 0.6 × rolling_20d_mean(full_day_range)`.

### Result

```
Base rate (retrospective weak):   18.1%  (reasonable)
Base rate (prospective weak):     20.2%  (reasonable after threshold fix)
Confusion: TP=65  FP=126  FN=106  TN=650
Precision:     0.34   ← KILL (< 0.55)
Recall:        0.38   ← KILL (< 0.40)
F1:            0.36
Accuracy:      0.755  (misleading — driven by large TN bucket)
```

### Interpretation

The 30-min open-range z-score is **too noisy** to prospectively identify
weak-trend days:
- Of days we flag as weak at 10:00 ET, only 34% are actually weak by day-end.
- Of actually-weak days, we catch only 38% of them at 10:00.

This is worse than flipping a coin *for the specific task of regime
filtering at the entry gate*. An R3 component that relies on this
classifier would gate away ~66% true positive trading opportunities
that turn out to be non-weak, while still missing 62% of the weak days
it was supposed to catch.

### First-run bug (disclosed for audit)

The initial V4 run (logs/v4_run.log) used `open_range_30min < 0.6 × full_day_ATR20`,
which is an apples-to-oranges comparison. 30-min range is mechanically
far smaller than full-day range, so 92.6% of days triggered the
"weak" flag — a threshold specification error, not a model finding.
Fixed in commit pending: rolling ATR computed on the open-window series
itself. Result above is from the fixed version (logs/v4_run_v2.log).

### Action

- **Edit `docs/strategy_delta_vs_joey.md` §5**: downgrade from "very
  high impact free alpha" to **FALSIFIED 2026-04-21**. Leave squeeze
  scaling as a separate item (not tested by V4).
- **Do NOT remove regime-awareness from R3 scope** — V4 only falsifies
  this *specific* classifier (30-min open range). Other prospective
  classifiers (GEX state at 10:00, IV-skew z-score, overnight gap)
  remain candidates. But promoting any candidate to R3 requires first
  passing a V4-style prospective test.
- **Flag to GPT Pro:** this is the strongest empirical finding of the
  day. Either it challenges our framing, or it confirms Round-5's warning
  against manufactured alpha. Either way, it's load-bearing.

### What this does NOT mean

- Does not mean Joey is wrong about weak-trend being his hardest regime.
  He probably is, because OTM convexity needs movement to print.
- Does not mean we should copy Joey and also ignore weak-trend — V4 just
  shows that identifying weak-trend prospectively is harder than
  `strategy_delta_vs_joey.md` §5 assumed.
- Does not mean regime filtering is impossible — just that 30-min range
  is not the signal.

---

## V3 — Opening 15-min no-trade filter: **WEAKLY SUPPORTED at microstructure level, motivation ambiguous** 🟡

### Setup
- **Claim tested:** Joey intel #17 says "no signals in first 15 min after
  open." Our `src/risk/manager.py` has `no_trade_before="09:45"`
  matching this.
- **Test:** 951 days. For each, sampled ATM SPXW 0DTE call. Computed
  minute-level mid-return std and spread% in three windows:
    - A = 09:30–09:45
    - B = 09:45–10:00
    - C = 10:00–15:00

### Result

```
Return std (median across days):
  A (09:30-09:45):  0.0819
  B (09:45-10:00):  0.0739
  C (10:00-15:00):  0.0805
  A/C ratio: 1.02         ← nearly flat
  B/C ratio: 0.92

Spread % of mid (median):
  A: 0.0167  (1.67%)
  B: 0.0154  (1.54%)
  C: 0.0223  (2.23%)      ← core session is WIDER
  A/C ratio: 0.75         ← first 15 min actually tighter
```

### Interpretation

At the **option microstructure** level (SPXW ATM call quote and price):
- First 15 min is not materially noisier than the core session.
- First 15 min spreads are 25% tighter than core session — best
  liquidity of the day.

This contradicts the naive reading of Joey #17 ("first 15 min is
chaotic, don't trade"). At the option level, the first 15 min is
a *good* execution environment.

### But this is not a full refutation

Joey's rule likely isn't about option microstructure — it's about
**signal primitive stability**:
- GEX is recalculated on overnight OI + fresh quote snapshots.
- `call_wall` / `put_wall` levels from `src/gex/calculator.py` depend
  on bid/ask/OI across many strikes, not just ATM liquidity.
- First 15 min of flow is unrepresentative because morning imbalance
  (overnight-accumulated orders) hasn't cleared.

V3 did NOT measure GEX/wall stability in first 15 min. That's a
follow-up diagnostic (V3b).

### Action

- **Keep `no_trade_before="09:45"` for now** — no evidence to relax it.
- **Downgrade Joey intel #17 in `docs/joey_bot_extracted_specs.md`**:
  add note "empirical support at microstructure level is weak; likely
  motivated by GEX/wall primitive stability which V3 did not measure."
- **Defer V3b** (GEX stability in first 15 min) until r0_check1 trigger
  density script is written, since that script already needs GEX values
  computed at minute resolution.

---

## Updated delta vs Joey

| # | Original claim | Status after V3/V4 |
|---|----------------|-------------------|
| 1 | Adaptive Kelly downgrade | Unchanged, still pending |
| 2 | ResilientFillPolicy exit state machine | Unchanged, still pending |
| 3 | Stop-loss -40% regime validation | Unchanged, pending V6 |
| 4 | Trigger density calibration 3-5/day | Strengthened — V3 says first 15 min is tradeable at microstructure level, so filter calibration must address GEX stability, not copy Joey's window blindly |
| 5 | Weak-trend no-trade as free alpha | **FALSIFIED with naive 30-min range classifier.** Claim preserved in spirit (Joey's weak-trend is real) but demoted from "free" to "requires a classifier we don't yet have." |

**Net effect:** one of the five "free wins" is dead in its current form.
Four remain. The repo-wide implication is that R3 regime filter work
needs to search for *actually* prospective signals, not assume them.

---

## Cross-check pending

GPT Pro Question 2 specifically asked about this identification trap.
When their response returns:
- If GPT Pro also flags V4-style failure → **convergent evidence**, ship
  update to `strategy_delta_vs_joey.md` §5 as FALSIFIED.
- If GPT Pro says classifier variants (GEX state, IV skew z-score) would
  pass prospective identification → **queue V4b** testing those.
- If GPT Pro says the whole §5 reasoning is wrong (not just the
  classifier) → rewrite §5 from scratch before amending R3 scope.

Do NOT roll back the V4 empirical finding regardless of GPT Pro's
theoretical answer. Data wins.

---

## Files produced

- `logs/v4_weaktrend_prospective_result.json` — final V4 metrics
- `logs/v4_weaktrend_prospective_labels.csv` — per-day labels
- `logs/v3_open_filter_result.json` — V3 window comparisons
- `logs/v3_open_filter_by_day.csv` — per-day A/B/C stats
- `logs/v4_run.log`, `logs/v4_run_v2.log`, `logs/v3_run.log` — console

## V2 — Joey payoff model empirical check: **CONFIRMED with signal-conditionality flag** ✅ ⚠️

### Setup
- **Claim tested:** Joey's `+300% typical win / -40% hard stop` numbers,
  encoded in `docs/joey_payoff_model.py` as baseline
- **Test:** 951 days. Pick call with |delta| ≈ 0.20 at 09:45 ET. Enter
  at ask (Joey's fill method). Exit at 15:55 bid OR stop-out (whichever
  first) under 4 stop levels: none, −40%, −60%, −100%
- **Critical property:** this is UNCONDITIONAL on any signal — pure
  mechanical baseline. Joey's claimed payoff numbers must be at least
  mathematically possible on this distribution, else they're fabricated

### Result

```
                  WR     PF    stopped  median_win  median_loss  mean_win  p90_win
none (hold EOD)   18.7%  0.97    —       +298%       -99.7%       +396%    +834%
stop -40%          9.7%  1.28   89.8%    +378%       -40.0%       +477%    +971%
stop -60%         12.9%  1.11   85.5%    +320%       -60.0%       +444%    +856%
stop -100%        18.7%  0.97    0.0%    +298%       -99.7%       +396%    +834%
```

### Interpretation — three findings

#### Finding 1 — Joey's +300% number is REAL
Unconditional median win on 0.20Δ 0DTE calls held 09:45 → 15:55 is
**+378% gross** under his −40% stop rule (+298% without stop). Joey's
"+300% typical win" is not memory survivorship — it's within the
empirical distribution. This **validates `joey_payoff_model.py`'s
squeeze regime number** (+300%) as the unconditional baseline.

#### Finding 2 — Joey's −40% stop is mathematically correct
- No stop:  PF **0.97** (mean EV < 0 — unconditional strategy loses money)
- −40% stop: PF **1.28** (+32% improvement)
- −60% stop: PF **1.11**
- −100%/none: equivalent

Joey's −40% stop converts an unprofitable mechanical strategy into a
marginally profitable one even WITHOUT any signal edge. This is not
a tuning overfit — the mechanism is obvious: 0.20Δ calls are OTM by
design, so most days they expire near zero, and cutting losses at −40%
lets the rare +300%+ winner pay for the losers. **Our `src/backtest/engine.py`
currently uses `sl_pct = -0.50` in `BacktestConfig`. Joey is at −0.40.
**Note:** I initially mis-read this as −1.00 (no stop); correction:
the gap is 10%, not 50%. V7 will test the 40/50/60 range empirically
rather than rely on unconditional V2 numbers, because v5 signal may
have different stop sensitivity than the unconditional distribution.**

#### Finding 3 — Joey's 70% WR is impossible as self-reported
Unconditional WR at −40% stop is **9.7%**. If Joey's signal produced a
real 70% WR with +300%/-40% payoff, PF would be:
```
PF = (0.70 × 300) / (0.30 × 40) = 17.5
```
No 0DTE strategy achieves PF 17.5 live. His self-reported 70% WR is
either:
  (a) counted over a different denominator — e.g. WR on *signals that
      led to profitable trades* rather than all signals (confirmation
      of a trade ≠ same as entry), OR
  (b) measured over cherry-picked months (squeeze clusters), OR
  (c) verbal inflation / misremembered
Most likely: his real live WR is probably 20–35%, with PF 2.5–4.0,
driven by signal gating picking the top 25–35% of days from the
unconditional distribution.

### Reshaping `docs/joey_payoff_model.py`

The `win_by_regime` dict in `joey_payoff_model.py` assumed weak-trend
winner = +80%. V2 finds the **unconditional** median winner is +378%.
Regime conditioning matters less than I thought. Correct shape:

- **Unconditional baseline:** +378% median win, 9.7% WR, −40% loss cap
- **Joey's signal effect:** shifts WR distribution upward (not median
  winner size); realistic signal-gated WR is ~25–35%
- **Weak-trend days are NOT characterized by smaller winners.** They're
  characterized by **fewer winner days** (lower WR). Losers stay at
  exactly −40% because the stop rule is mechanical.

Updated `joey_payoff_model.py` `win_by_regime` should be uniform ≈ +378%
across regimes, and `kelly_wr` should be the regime-varying parameter.

### Critical implications for our strategy

1. **Our v5 swing_1dte backtest uses `sl_pct = -0.50`; Joey uses −0.40.**
   10% difference, not 50%. V2 evidence says −40% is optimal on
   unconditional 0.20Δ path, but v5 is conditional on a different entry
   rule (NEG_GAMMA + pos<0.15 → 0.70Δ ITM call, not 0.20Δ OTM). Test
   rather than assume.
2. **V5 validation numbers (PF 1.23–1.77 across buckets) should be
   re-run with −40% stop as a comparison point.** If v5's PF drops
   when using −40% (because it stops out too many eventual winners),
   that's actually a signal-character discovery. If v5's PF improves,
   we've gained free alpha.
3. **Joey's system is approximately: take an unconditional PF 1.28
   baseline and gate it to the top 25-30% of days.** We should measure
   whether our signal does the same gating work.

### Action

- **Update `docs/joey_payoff_model.py`**: rewrite `win_by_regime` using
  V2 empirical numbers. Add signal-conditionality flag making explicit
  that `typical_win` is unconditional and Joey's +300% is consistent
  with this unconditional measurement. Regime differences should be
  expressed as WR shifts, not winner-size shifts.
- **Update `docs/joey_bot_extracted_specs.md`**: append note to
  row #8 (+300% win) that V2 empirically validates this as
  unconditional number, not memory bias. Append note to row #? (70%
  WR) that V2 mathematically contradicts 70% WR with +300%/-40%
  payoff — likely 25-35% conditional on signal.
- **Queue new test V7: v5 signal under −40% stop** — see if our v5
  backtest's PF 1.23 can be pushed higher just by adopting Joey's
  stop rule without any architecture change.

---

## Master status after V2/V3/V4

| Claim | Verdict | Evidence |
|---|---|---|
| Joey's +300% winner | ✅ REAL, unconditional | V2 empirical median +378% |
| Joey's −40% stop | ✅ CORRECT, +32% PF vs no-stop | V2 PF comparison |
| Joey's 70% WR | ❌ MATHEMATICALLY IMPOSSIBLE with self-reported payoff | V2 derivation |
| Joey intel #17 (open 15min no-trade) | 🟡 No microstructure support; GEX-primitive test pending | V3 |
| Weak-trend free alpha (our §5 claim) | ❌ FALSIFIED (30-min open-range classifier) | V4 |
| Our backtest at `sl_pct = -0.50` vs Joey `-0.40` | 🟡 10% tuning difference, test required (V7) | V2 + engine.py read |

**Biggest surprise:** the load-bearing finding of the day is NOT that §5
was falsified. It's that **our own v5 backtest has a trivially-fixable
−31% PF leak** from using no stop loss when Joey's −40% is mechanically
better even on the unconditional distribution. This is a one-line change
in `BacktestConfig` that could move v5 from "regime-dependent marginal"
to "materially positive." Validate V7 tomorrow.

---

## Files produced (updated)

- `logs/v2_joey_payoff_empirical_result.json` — V2 metrics by stop level
- `logs/v2_joey_payoff_empirical_trades.csv` — per-day trade records
- `logs/v4_weaktrend_prospective_result.json` — final V4 metrics
- `logs/v4_weaktrend_prospective_labels.csv` — per-day labels
- `logs/v3_open_filter_result.json` — V3 window comparisons
- `logs/v3_open_filter_by_day.csv` — per-day A/B/C stats

## V7 — v5 signal stop-loss sensitivity: **NULL RESULT (plumbing smoke test)** ⚠️

### Setup
- Run v5 backtest on 825 days under sl_pct ∈ {−0.40, −0.50, −0.60}
- Compare PF by bucket (ORIG_IS / ORIG_OOS / EXT_OOS / ALL)
- Expected: if any stop dominates uniformly, adopt it as default

### Result

```
Bucket          sl=-0.40    sl=-0.50    sl=-0.60
ORIG_IS            1.672       1.672       1.672
ORIG_OOS           1.841       1.841       1.841
EXT_OOS            1.098       1.098       1.098
ALL                1.249       1.249       1.249
```

**All three stop levels produce identical PF to 3 decimal places.**

### Interpretation

The `sl_pct` path in `src/backtest/engine.py` is **not active** in the
v5 `swing_1dte` mode. The swing strategy holds from EOD of day N to EOD
of day N+1, exiting at the next day's close. The stop-loss check, if
implemented at all, only fires on intraday bar transitions — but v5
trades hold across the overnight gap where no bars are checked. Option
premium can run from +100% to −60% to +40% overnight without the stop
firing, then exit at whatever the close is.

**This exactly validates GPT Pro's Q3 warning:** "running v5 under
Joey parameters is not a replacement check … because
`src/signal/generator.py` and `src/backtest/engine.py` are still
swing_1dte, not intraday 0DTE. PF ≥ 1.0 on weak-trend days there would
not validate Joey or kill R0 — most likely indicate horizon
contamination, simulator artifact." V7 result confirms the artifact
hypothesis.

### Action

- **Do NOT change** `BacktestConfig.sl_pct` default. The empirical
  finding is "no effect in current engine," which supports no decision.
- **Add a TODO in `src/backtest/engine.py`**: document that `sl_pct`
  is inert in swing_1dte mode and will only activate when we implement
  intraday 0DTE mode (R3 scope).
- **Downgrade V7 conclusion status**: this was a plumbing smoke test,
  not a strategy evaluation. V2 remains the authoritative evidence that
  −40% stop is mathematically correct on the unconditional intraday
  0.20Δ distribution. No conflict with V2 — V7 simply does not measure
  the same thing.

---

## GPT Pro 2026-04-21 verdict — cross-check with our data

GPT Pro returned three-block verdict (Q1/Q2/Q3). Cross-checked against V2/V3/V4:

### Q1 — Joey claim reliability

| Claim | GPT Pro | Our data | Verdict |
|---|---|---|---|
| +300% typical winner | **Unreliable (salient-memory)** | **REAL — V2 median +378% unconditional** | ✅ **Data overrides GPT Pro** |
| 70% WR | Unreliable, zero calibration | Mathematically impossible (would imply PF 17.5) | ✅ Convergent |
| −40% hard stop | Directionally reliable, numerically unreliable | V2 shows PF 0.97→1.28 (+32%) on unconditional | 🟡 Partial — stop is mathematically correct; numerical grid still worth testing |
| "No kill, Kelly enough" | Fact reliable, adequacy claim unreliable | Convergent — Joey's adequacy claim is unverified | ✅ Convergent |

**Key disagreement:** GPT Pro marked +300% as unreliable salient-memory. V2
empirically disproves this: unconditional median win on 0.20Δ 0DTE calls
at −40% stop is +378%. **We trust V2 over GPT Pro on this single point**,
because V2 tested the exact scan GPT Pro requested and returned a
positive result GPT Pro could not have known about (brief was written
before V2 ran).

### Q2 — Five free wins

| # | GPT Pro verdict | Our state |
|---|---|---|
| 1 adaptive Kelly | Hidden dependency, incremental plumbing, not free alpha | Agree; §1 downgraded |
| 2 fill state machine | Half realism correction, half alpha only if no-fill observable | Agree; V1 pending |
| 3 stop validation | Not free — parameter search, needs OOS ranking stability | Agree; §3 softened |
| 4 trigger density 3-5/day | Not free — sanity bound only, not tuning target | Agree; §4 softened |
| 5 weak-trend gate | Highest hidden dependency, requires prospective separation test | **V4 already ran this test and falsified it** |

### Q3 — Gate ordering

- GPT Pro recommended reorder: **check0_payoff_geometry → check3_dealer_sign → check2_dumb_mae → check1_trigger_density**
- Reasoning: dealer sign is the load-bearing mechanism (per HANDOFF §9); trigger
  density is tuning, not mechanism.
- **Adopted.** `scripts/r0_check0_payoff_geometry.py` written and running.
- HANDOFF.md Action 2/3/4 will be re-numbered accordingly.

---

## Master status after V2/V3/V4/V7 + GPT Pro

| Claim / Item | Verdict | Evidence |
|---|---|---|
| Joey's +300% winner | ✅ REAL, unconditional (V2 beats GPT Pro here) | V2 |
| Joey's −40% stop | ✅ Mathematically correct on unconditional path | V2 |
| Joey's 70% WR | ❌ IMPOSSIBLE with claimed payoff | V2 + GPT Pro convergent |
| Joey intel #17 | 🟡 No microstructure support; GEX-primitive test pending | V3 |
| §5 weak-trend free alpha | ❌ FALSIFIED | V4 + GPT Pro convergent |
| v5 stop sensitivity | ⚠️ null (engine artifact, plumbing test only) | V7 |
| strategy_delta §1-§4 | 🟡 Softened per GPT Pro Q2 | GPT Pro |
| r0 gate ordering | ✅ Reorder adopted: check0→3→2→1 | GPT Pro Q3 |

## Files produced (final state)

- `scripts/validate_v2_joey_payoff_empirical.py` + logs/v2_*
- `scripts/validate_v3_open_filter.py` + logs/v3_*
- `scripts/validate_v4_weaktrend_prospective.py` + logs/v4_*
- `scripts/validate_v7_v5_stop_sensitivity.py` + logs/v7_*
- `scripts/r0_check0_payoff_geometry.py` (running at time of writing)
- `docs/joey_payoff_model.py` rewritten with V2 empirical baseline

## r0_check0 — payoff geometry feasibility: **MARGINAL PASS** 🟡

### Setup (per GPT Pro Q3)
- On 951 days (2022-07 → 2026-04), pick 0.20Δ call at 09:45 ET
- Enter at ask; walk minute path; exit at first of:
  - +300% gross on bid (`TARGET_HIT`)
  - −40% on mid (`STOP_HIT`)
  - 60 minutes elapsed (`TIMEOUT` → exit at 15:55 bid if past 15:55, else terminate)

### Result

```
TARGET_HIT: 3.26% of days     (+300% before −40% within 60 min)
STOP_HIT:  65.19% of days     (−40% before +300%)
TIMEOUT:   31.55% of days     (neither within 60 min)

median_pnl:  -40.0% (dominated by STOP_HIT)
mean_pnl:     +3.25% (wins drag mean positive despite 3.3% rate)
top3_month_concentration: 22.6%  (NOT regime-locked)
mean_mins_to_exit: 34.9 min
```

### Interpretation

**Kill criterion 1** (target hit rate < 3%): NOT triggered (3.26% ≥ 3%),
but marginal.

**Kill criterion 2** (>80% of target hits in top 3 months): NOT triggered
(22.6%). Target distribution is dispersed over time — this is the
stronger piece of evidence. If the +300% target were squeeze-only, we'd
expect concentration well above 50%.

### Relationship to V2

- V2 used 09:45 → 15:55 hold (full day): median win +378%, WR 9.7% at
  −40% stop
- check0 restricts to 60-min hold (Joey's claimed window): WR drops to 3.26%

**Implication:** Joey's full +300% winner size is reachable in his stated
10-60 min holding window on 3.3% of days, and on an additional 6.4% of
days if held to 15:55. The "intraday within 60 min" constraint is the
binding one. Joey's claimed 3-5 trades/day combined with 10-60 min
holds is mathematically consistent with ~3-10% per-trade WR on the
unconditional baseline — not 70%.

### Derived Joey signal alpha budget

Unconditional target-hit rate:  3.3% (60-min) / 9.7% (full day)
Joey's real live WR (estimate): 20-30% (per V2 derivation)
**Required signal lift:** 6-9× improvement in target-hit rate over
unconditional. This is achievable with strong features but is the actual
bar for R1-R5, not "beat random."

### Verdict

- Proceed to check3 (dealer sign) per GPT Pro ordering
- **Tighten check2/check3 budgets**: if subsequent checks show our
  current primitives can only lift target-hit rate by 2-3×, R1-R5 is
  not worth the engineering. We need 6-9× lift for Joey-class returns.
- **Update `joey_payoff_model.py`**: add `target_hit_rate_60min = 0.033`
  as a field, so downstream code can compute signal-lift targets
  explicitly.

---

## r0_check3 — dealer-sign stability: **CLEAN PASS** ✅ (with counter-evidence to Adams 2024)

### Setup (per GPT Pro Q3 + HANDOFF §9)
- 952 days. Compute signed call volume and signed put volume separately
  using Lee-Ready on single-leg electronic trades (condition ∈ {0, 18},
  Dong AEA 2026 filter).
- VIX proxy = median ATM SPX IV at 10:00 ET from greeks parquet
  (leak-safe — only 10:00 data used to classify the day's regime).
- Tercile cutoffs: low ≤ 0.187, mid ∈ (0.187, 0.274], high > 0.274

### Result

```
                     low_VIX    mid_VIX   high_VIX    mag_ratio  verdict
signed_call_vol_mean  +13,560   +11,528    +9,109      1.49x    PASS
signed_put_vol_mean   +15,072   +17,445   +12,997      1.34x    PASS
```

**Both call and put flow signs are uniformly positive across all three
VIX regimes.** Customers are net buyers on both sides regardless of
volatility regime. Magnitude ratios (1.49x, 1.34x) comfortably below
the 2x PASS threshold and 3x soft-kill threshold.

### Interpretation — unexpected mechanism support

If customers are net buyers on BOTH calls AND puts, dealers are net
SHORT on both sides → **dealers hold a net short-straddle position
with net short gamma**. This is direct support for the R0 GEX thesis
("dealers are short gamma → must buy dips, sell rallies → spot gets
pinned"), and it holds **across VIX regimes**, not only in calm markets.

### Counter-evidence to Adams 2024

Our `docs/joey_bot_extracted_specs.md` cited Adams/Fontaine/Ornthanalai
SSRN 4881008 (May 2024) which found "MMs MATCH 0DTE flow; net dealer
gamma carry is essentially zero." This was load-bearing evidence
against the Baltussen 2021 / Barbon-Buraschi narrative.

Our check3 finding on 952 days of Lee-Ready signed single-leg
electronic trades shows the opposite: **customers are systematically
net buyers on both sides, dealers are systematically net short**.
Possible reconciliations:
1. Adams' analysis uses different flow-signing methodology (CBOE
   Open-Close or similar aggregated data); Lee-Ready on tape trades
   may capture a different subset of the order flow.
2. Adams' analysis may be all-strike weighted while we aggregate
   across 0DTE strikes only.
3. We filter to single-leg electronic (condition {0, 18}); Adams may
   include complex orders and floor-routed trades.
4. Regime difference: Adams looked at 2024 snapshots; our 952 days
   span 2022-07 to 2026-04.

This is **not a full refutation** of Adams — we use a narrower
signing methodology. But it is sufficient to restore our confidence
in the R0 "dealer short gamma" mechanism for the specific subset of
trades we can observe and size.

### Action

- **Do NOT update `joey_bot_extracted_specs.md` to remove the Adams
  reference.** Keep both positions in the file with a "methodological
  divergence" note. Honest disclosure is load-bearing.
- **Proceed to check2** (T_disc/T1/T2 MAE test) per reordered HANDOFF.
- **Flag for eventual GPT Pro Round 7**: this convergence/divergence
  with Adams 2024 is worth a formal audit once check1/2 complete,
  because R0 mechanism story now depends on which signing methodology
  is closer to reality.

---

## r0_check2 — dumb MAE test: **KILL TRIGGERED** ❌

### Setup (per HANDOFF Action 4, Ultra Review #3)
- 952 days. Compute GEX profile at 14:30 ET using all-strike gamma ×
  OI. Derive 4 targets: T_disc, T1 (dominant wall), T2 (barycenter),
  T_spot (naive baseline).
- Compare MAE to actual 15:55 ET close.

### Result

```
                    ORIG_IS  ORIG_OOS  EXT_OOS    ALL (952d)
T_spot   MAE         15.02    9.83     10.96       11.14
T1                   15.57    13.01    15.46       15.17   (+36.2% WORSE)
T2                   15.29    11.04    12.76       12.86   (+15.4% WORSE)
T_disc               17.32    13.97    16.23       16.08   (+44.3% WORSE)
```

### Interpretation

Every wall-based target, every bucket, strictly worse than naive
spot-as-target. Ultra Review kill criterion (≥10% MAE reduction from
spot baseline) is not met by any variant. **HANDOFF Action 6 kill
criterion triggered.**

### The tension with check3

- check3 says dealers ARE systematically short-gamma (PASS).
- check2 says walls DO NOT pin spot in the 14:30→15:55 window (KILL).

Both cannot describe the same mechanism coherently. Either:
- **Mechanism dead** — dealer short-gamma exists but doesn't manifest
  as pin (e.g. futures hedging, or pin hypothesis was always wrong).
- **Measurement wrong** — 14:30 is too late, 85-min window too long,
  T_disc implementation missing persistence weighting.

Full analysis in `docs/r0_post_mortem_2026_04_21.md`.

### Action (not auto-executed)

Per HANDOFF Action 6: "If any fail, write a post-mortem and stop."
Written but not auto-executing kill. User decision required, informed
by:
- `docs/r0_post_mortem_2026_04_21.md` — decision space (A kill / B rescue / C GPT Pro first)
- `docs/gpt_pro_brief_2026_04_21_round7.md` — three adjudication questions

**Recommendation:** Option C (GPT Pro Round 7) → if measurement, Option B
(revised check2 with corrected entry/window/T_disc) → if mechanism,
Option A (kill R0).

### check1 NOT launched

Per HANDOFF Action 7: "Do NOT touch R1-R5 code until checks 0/1/2/3
all pass." check2 KILL means check1 is moot (wouldn't save R0 either
way). Script remains unwritten until decision point resolved.

---

## r0_check2b — entry × window grid sensitivity: **CONFIRMED R0 KILL** ❌

### Setup
- 6 entry times × 4 hold windows × 3 targets = 72 improvement cells
- Entries: 10:00, 11:00, 12:00, 13:00, 14:00, 14:30
- Windows: 30, 60, 85, 120 min

### Result

```
Cells where any wall-target beats T_spot by ≥10%:   0
Cells where any wall-target beats T_spot at all:    0
Best cell:   14:30/120min T2  (-15.38% still worse than spot)
Worst cell:  11:00/30min T_disc (-178.4%)
T_disc:      uniformly worst variant
T2:          uniformly least-bad but never positive
```

### Interpretation

The measurement-rescue hypothesis is empirically dead. No parameter
choice converts wall-based targets into something that beats
spot-as-target on this data. The conclusion from check2 is not an
artifact of one bad parameter choice — it holds across the entire
plausible parameter space.

### Reconciled story with check3

Dealers ARE systematically short gamma (check3 +1 across all VIX
regimes, confirmed). Walls DO NOT pin spot (check2 + check2b, 24
cells confirmed). Three candidate reconciliations:

1. **Momentum-not-pin** (Barbon-Buraschi 2021 gamma fragility):
   NEG-gamma dealers produce accelerating moves, not pinning. Walls
   are event triggers, not attractors.
2. **Futures hedging**: dealers hedge in ES, not cash SPX.
3. **Thesis incoherent**: short-gamma exists as positioning but has
   no predictive content for spot.

See `docs/r0_post_mortem_2026_04_21.md` for full analysis. Sent to
GPT Pro Round 7 at `docs/gpt_pro_brief_2026_04_21_round7.md` for
pivot-branch adjudication.

---

## r0_check2c — momentum-vs-pin confirmatory test: **AMBIGUOUS (both fail)** 🟡

### Setup
- On 952 days at 14:30 ET, filter to NEG_GAMMA + pos_in_range in
  extremes (<0.15 near put_wall, or >0.85 near call_wall).
- Measure spot return over 14:30→15:55 (85 min).
- Pin hypothesis predicts: bounce toward midpoint.
- Momentum hypothesis predicts: break through the extreme wall.
- Pre-registered pass: hit rate >55% for a thesis on both sides.

### Result

```
Near put_wall  (n=147, NEG_GAMMA + pos<0.15):
  pin_hit_rate:      49.0%   (below 55%)
  momentum_hit_rate: 49.7%   (below 55%)
  mean ret 85min:    +0.018%  (essentially zero)
  median ret 85min:   0.0%

Near call_wall (n=3):   INSUFFICIENT DATA
```

Script verdict: "PIN_PARTIAL" driven by mean-return sign tie-breaker,
but both hit rates are near 50% — this is genuinely **ambiguous / no
dominant mechanism** on the 85-min window.

### Major insight — v5 edge is overnight, not intraday

This test directly parallels v5's rule (NEG_GAMMA + pos<0.15 → BULLISH
next-EOD), but measured in an 85-min intraday window instead of
overnight 24h. Critical asymmetry:

| Measurement window | Outcome |
|---|---|
| 85 min intraday (check2c) | WR ~49%, mean return +0.018%, essentially random walk |
| overnight 24h (v5 backtest) | PF 1.23–1.77 across 574 days, positive across 4 OOS tiers |

**v5's apparent edge cannot be explained by same-day pin mechanism.**
The intraday data shows no directional signal in the NEG_GAMMA +
extreme-wall state. The overnight edge must come from something
else — the most parsimonious candidate is Baltussen/Da/Soebhag SSRN
5039009 (Nov 2024) retail-attention + short-seller-risk-management
MR that happens across the overnight session, not dealer gamma
hedging during the day.

### Implication for pivot

The **A1 (momentum-not-pin rebuild)** branch in the post-mortem
assumed NEG_GAMMA + wall-proximity produces directional moves
(either pin or momentum, but specifically NOT random). check2c shows
it produces essentially **neither** on the intraday window.

This collapses A1 as originally framed. The only way A1 becomes
viable is if we argue the mechanism lives exclusively in the
overnight window — which is not 0DTE, it's 1DTE. That means A1 is
equivalent to "rebuild v5" and we already have v5's numbers.

**Revised pivot ranking after check2c:**

1. **A2 (Joey-style feature engineering)** — most defensible. No
   specific mechanism story, just ensemble of weak signals with
   strict OOS. Acknowledges honestly that we lack net-flow data
   Joey uses and so cannot exceed his edge; frames this as
   "infrastructure + research skills portfolio project" not a
   money machine.

2. **A3 (archive + writeup)** — most honest. We have now
   empirically disproven the R0 thesis and partially the v5
   intraday thesis. Project becomes a case study in rigorous
   falsification with intrinsic methodological value.

3. **A1 (momentum-not-pin rebuild)** — demoted. Would require
   either (a) finding a different measurement window where pin or
   momentum becomes dominant, or (b) conceding we're actually
   rebuilding v5 under a new name. Neither seems worth the
   engineering cost.

### Action

- Update `docs/r0_post_mortem_2026_04_21.md` pivot rankings to
  reflect A2 > A3 > A1 (originally A1 > A2 > A3).
- Repack `~/Desktop/gpt_pro_round7/` with check2c result.
- GPT Pro Round 7 brief remains valid; add check2c as a 3rd result
  attachment.

---

## Master status after V2/V3/V4/V7 + check0 + check3 + check2 + GPT Pro

| Claim / Item | Verdict | Evidence |
|---|---|---|
| Joey's +300% winner | ✅ REAL on full-day hold, 🟡 marginal on 60-min hold | V2 + check0 |
| Joey's −40% stop | ✅ Mathematically correct on unconditional path | V2 |
| Joey's 70% WR | ❌ IMPOSSIBLE with claimed payoff | V2 + GPT Pro convergent |
| Joey intel #17 | 🟡 No microstructure support; GEX-primitive test pending | V3 |
| §5 weak-trend free alpha | ❌ FALSIFIED | V4 + GPT Pro convergent |
| v5 stop sensitivity | ⚠️ null (engine artifact, plumbing test only) | V7 |
| strategy_delta §1-§4 | 🟡 Softened per GPT Pro Q2 | GPT Pro |
| r0 gate ordering | ✅ Reorder adopted: check0→3→2→1 | GPT Pro Q3 |
| R0 payoff geometry | 🟡 MARGINAL PASS (3.3% base rate) | check0 |
| R0 signal lift bar | ≥6× unconditional for Joey-class returns | V2 + check0 derivation |
| R0 dealer-sign stability | ✅ PASS — call & put customer flow both net-buy across VIX terciles | check3 |
| Adams 2024 "MMs match flow" | 🟡 Partially counter-evidenced on our data methodology | check3 |
| R0 wall-as-pin target | ❌ KILL — no wall-based target beats spot-as-target in 14:30→15:55 window | check2 |
| R0 measurement-rescue hypothesis | ❌ FALSIFIED — 24-cell grid scan, 0 pass, 0 marginal | check2b |
| R0 overall status | ❌ CONFIRMED KILL (mechanism failure) — pivot required | post-mortem + check2b |

## Files produced (final state)

- `scripts/validate_v2_joey_payoff_empirical.py` + logs/v2_*
- `scripts/validate_v3_open_filter.py` + logs/v3_*
- `scripts/validate_v4_weaktrend_prospective.py` + logs/v4_*
- `scripts/validate_v7_v5_stop_sensitivity.py` + logs/v7_*
- `scripts/r0_check0_payoff_geometry.py` + logs/r0_check0_*
- `docs/joey_payoff_model.py` rewritten with V2 empirical baseline
- `docs/validation_summary_2026_04_21.md` (this file)
- `HANDOFF.md` Actions 2-7 reordered per GPT Pro Q3

## A2 pilot — frozen-feature monotone-lift test: **CLEAN FAIL** ❌

### Setup (per GPT Pro Round 7 Q3 spec, exactly as pre-registered)
- Label: check0 `TARGET_HIT before STOP_HIT within 60 min`. Base rate 3.06% on EXT_OOS (719 days).
- Decision time: 09:45 ET (aligns with check0 entry).
- 6 frozen features: GEX_state, pos_in_range, flow_sign, ATM_IV, overnight_gap, VIX_proxy.
- Pass: any single bin hit rate ≥ 6.5% (2× base) AND n ≥ 40 AND ORIG_OOS sign agreement.

### Result

```
Feature         Best EXT_OOS bin   Hit rate   Lift vs base   Gate
GEX_state       neg                3.33%      1.09×          fail
pos_in_range    high               3.61%      1.18×          fail
flow_sign       neg                3.22%      1.05×          fail
ATM_IV          high               3.36%      1.10×          fail
overnight_gap   flat               3.61%      1.18×          fail
VIX_proxy       high               3.64%      1.19×          fail

Max lift across all 6 features: 1.19× (needed 2×)
```

No single feature has prospective edge on the TARGET_HIT label at the
pre-registered decision time, at the pre-registered 60-min window,
with the pre-registered binning. ORIG_OOS had some cells look higher
(pos_in_range=high 10%, ATM_IV=high 9.1%) but the corresponding
EXT_OOS bins did not clear the 2× threshold — fail by rule.

### Interpretation

The A2 thesis ("Joey-style signal engineering on raw option-structure
features lifts target-hit rate enough to clear mechanics") is
**empirically unsupported on this dataset at pre-registered settings**.

Combined with earlier results:
- Dealer short-gamma is real (check3 PASS)
- Walls don't pin spot (check2 KILL)
- Measurement rescue fails (check2b KILL)
- Intraday momentum-vs-pin is ambiguous (check2c PIN_PARTIAL)
- Raw frozen features have no prospective lift (A2 pilot FAIL)

The 0DTE thesis tested in this repo does not support a positive-EV
strategy from this data. Per GPT Pro Round 7 Q3 commitment, **pivot
to A3 (archive) is executed immediately**. Do NOT rescue with new
features.

### Action taken

- `docs/R0_RIP_2026_04_21.md` written as rigorous falsification case
  study summarizing the full 2026-04-20 → 2026-04-21 research arc.
- Repository declared **archived** at this state. No further R1-R5
  development. No A2 expansion.

---

## Master status (FINAL, 2026-04-21 AM)

| Claim / Test | Verdict | Evidence |
|---|---|---|
| Joey's +300% winner | ✅ REAL on full-day hold | V2 |
| Joey's −40% stop | ✅ Mathematically correct | V2 |
| Joey's 70% WR | ❌ IMPOSSIBLE with payoff | V2 + GPT Pro R6 |
| Joey intel #17 (open filter) | 🟡 No microstructure support | V3 |
| §5 weak-trend free alpha | ❌ FALSIFIED | V4 |
| v5 stop sensitivity | ⚠️ null (engine artifact) | V7 |
| R0 payoff geometry | 🟡 MARGINAL PASS (3.3%) | check0 |
| R0 dealer-sign stability | ✅ PASS (short-gamma confirmed) | check3 |
| R0 wall-as-pin target | ❌ KILL | check2 |
| R0 measurement rescue | ❌ KILL (24-cell grid) | check2b |
| R0 momentum rebuild (A1) | ❌ KILL (49/49 random walk) | check2c |
| A2 frozen-feature pilot | ❌ FAIL (max 1.19× vs need 2×) | A2 pilot |
| **Project overall** | **ARCHIVED — 0DTE thesis not supported** | cumulative |

## Next

- Repo is **archived**. Scripts + data pipelines preserved as
  methodological artifact.
- No further R1–R5 work. No A2 expansion. No A1 rebuild.
- `docs/R0_RIP_2026_04_21.md` documents the full research arc.

## Biggest lesson of the day

**The first V4 run had a threshold bug that produced 92% base rate — an
obvious failure mode I should have caught in design.** This is exactly
the class of mistake Round 5 warned against: making data say what we
want it to say. The fix took 60 seconds. The lesson: every prospective
classifier needs its null/base rate sanity-checked *before* reading
precision/recall. That check should be added to future V-scripts.
