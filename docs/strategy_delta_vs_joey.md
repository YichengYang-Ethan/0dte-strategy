# Strategy Delta — Where We Can Beat Joey

**Companion to:** `docs/joey_bot_extracted_specs.md` and `docs/joey_payoff_model.py`.
**Purpose:** concrete, file-scoped engineering changes that match Joey where he's right and exceed him where he's weak, without needing his $200/mo data source.

**Constraint:** HANDOFF.md gates R1-R5 code behind the 3-day pre-check (r0_check1/2/3). Items below marked `[POST-CHECK]` must not be coded until the pre-check passes. Items marked `[NOW]` are safe to start immediately.

---

## Five Optimization Points

### 1. Sizing: match Joey, add adaptive downgrade `[POST-CHECK]` **⚠️ DOWNGRADED 2026-04-21 — incremental plumbing, not free alpha (GPT Pro Q2.1)**

> **Update 2026-04-21:** GPT Pro correctly flagged this as hidden-dependency,
> not free alpha. It can only reduce exposure after recent trades
> deteriorate — it cannot create expectancy. Also: our code review confirmed
> `src/risk/manager.py` already has `max_daily_loss=$500`, `max_trades_per_day=5`,
> `no_trade_before="09:45"`. We're not missing a risk layer vs Joey; we're
> adding a second-order refinement. Keep as "nice to have" rather than
> "load-bearing." Identification test before adopting: same fixed entries
> on untouched data, compare current manager vs current + adaptive Kelly.
> Count only if downside metrics improve OOS without future leakage.

**File:** `src/risk/manager.py`
**Joey intel:** #2 (1/4 Kelly × equity fraction), #9 (no kill switch).

Our current manager already has VIX scaling + direction correlation penalty — richer than Joey. Add one more layer:

```python
def adaptive_kelly(base_fraction: float,
                   recent_wr: float,
                   baseline_wr: float,
                   lookback_trades: int = 20) -> float:
    """Downgrade Kelly when recent WR drifts below baseline.

    Joey has no kill switch. We do, but not a hard daily-loss stop —
    instead, a continuous Kelly downgrade so the system self-throttles
    during weak regimes without yanking the plug.
    """
    if recent_wr < baseline_wr * 0.70:
        return base_fraction * 0.50
    if recent_wr < baseline_wr * 0.85:
        return base_fraction * 0.75
    return base_fraction
```

**Why this beats Joey:** OTM convexity + Kelly gives you mathematical self-capping on average, but a pathological streak (bot bug, broker glitch, regime shift) can still bleed. Adaptive downgrade reacts continuously without a binary cutoff that loses information.

---

### 2. Fill policy: match Joey's live logic, add resilient exit state machine `[POST-CHECK]`
**File:** `src/execution/fill_policy.py` (new) + `src/backtest/fill_simulator.py`
**Joey intel:** #3 (limit @ ask/bid), #4 (no-fill undefined), #11 ($3 round-trip cost).

```python
class JoeyFillPolicy:
    """Matches Joey's live behavior exactly, for realistic backtest."""
    def entry_price(self, quote) -> float:
        return quote.ask          # pay full spread to guarantee fill

    def exit_price(self, quote) -> float:
        return quote.bid          # accept full spread to exit

    round_trip_cost_usd: float = 3.00   # $1 slippage + $1 + $1 commission


class ResilientFillPolicy(JoeyFillPolicy):
    """Our extension — handles the no-fill case Joey left undefined."""
    def exit_sequence(self, t0, quote, position):
        return [
            (  0, "limit", quote.bid            ),  # attempt 1
            ( 60, "limit", quote.bid - 0.01     ),  # t+60s: cross by 1 tick
            (120, "limit", quote.bid - 0.02     ),  # t+120s: cross by 2 ticks
            (180, "market", None                 ),  # fallback
        ]
```

**Also update** `src/backtest/fill_simulator.py`: the existing `mid + 35% spread` is *more optimistic* than Joey's live fill (which is `mid + 50%` effectively). Add `aggressive_fill` mode using `ask` for entries and `bid` for exits so backtest assumptions match what Joey actually runs — and therefore what we will run in paper trade.

**Why this beats Joey:** he admitted he trusts liquidity and doesn't handle no-fill. On OPEX days / macro events / late-day illiquidity, limit-at-bid can simply not fill. Without a state machine he's either stuck in the position or manually intervening. We auto-escalate.

---

### 3. Stop-loss: validate against Joey's −40% before defaulting `[POST-CHECK]` **⚠️ DOWNGRADED 2026-04-21 — parameter search, not free alpha (GPT Pro Q2.3)**

> **Update 2026-04-21:** GPT Pro correctly flagged this as parameter search,
> not orthogonal improvement. HANDOFF.md Ultra-Review #5 already warned
> against "laundering free parameters as fixed." Validating a stop grid
> is legitimate but must require **ranking stability across adjacent
> years/regimes** before adopting a non-default. If the optimal stop
> flips between buckets, there's no signal — just tuning noise.
>
> V7 empirical result (2026-04-21): sl_pct ∈ {−0.40, −0.50, −0.60}
> produce **identical PF** in swing_1dte mode, because the stop path is
> inert for overnight-hold trades. Real sensitivity test must wait for
> intraday 0DTE engine. V2 (unconditional 0.20Δ intraday path) did show
> −40% > −60% > no-stop for PF, but that's conditional-on-no-signal;
> v5 signal may have different stop sensitivity.

**File:** `src/backtest/engine.py` + `scripts/validate_stop_loss.py` (new)
**Joey intel:** #7 (−40% hard stop).

Current v5 engine uses `stop_loss = -1.00` (stop at 100% loss of premium — i.e. exit only at expiry if worthless).
Joey uses `-0.40`. That's much tighter. Do NOT blindly adopt.

```python
# scripts/validate_stop_loss.py
for stop_pct in (-1.00, -0.70, -0.60, -0.50, -0.40):
    result = run_backtest(stop_loss_pct=stop_pct,
                          data=load_952_day_spxw_0dte())
    print(f"stop={stop_pct:5.2f}  "
          f"WR={result.win_rate:5.1%}  "
          f"PF={result.profit_factor:5.2f}  "
          f"avg_win={result.avg_win:+5.1%}  "
          f"avg_loss={result.avg_loss:+5.1%}")
```

**Expected finding:** tighter stops (Joey's −40%) should increase PF in chop regimes (cut dead trades faster) but decrease PF in trending regimes (stop out of would-be winners). The right answer is likely regime-dependent.

**Why this matters:** if our backtest shows −0.40 universally dominates, adopt it. If it's regime-split, we get another alpha lever (tight stop in chop, loose stop in trend) that Joey — operating with a fixed −40% — does not.

---

### 4. Trigger density: use Joey's 3–5/day as sanity bound only `[NOW]` **⚠️ DOWNGRADED 2026-04-21 — sanity bound not tuning target (GPT Pro Q2.4)**

> **Update 2026-04-21:** GPT Pro correctly flagged "match Joey's
> frequency" as cargo cult. Joey's 3-5/day is a behavioral observation
> about his signal, not evidence that our mechanism should fire at the
> same rate. Legitimate use: as an upper bound for sanity (if our
> signal fires 20+ times/day, it's too loose regardless of what Joey
> does). Non-legitimate use: tuning confluence threshold to hit 3-5/day
> as a target.
>
> Identification test (per GPT Pro): as confluence threshold moves,
> **future-only utility** must improve monotonically on untouched data
> (r0_check2 MAE or post-entry expectancy). If only trade count changes,
> the rule is cargo cult.

**File:** `scripts/r0_check1_trigger_density.py` (HANDOFF Action 2)
**Joey intel:** #13 (3–5 trades/day).

HANDOFF.md Action 2 says "kill if median day has 0 entries or every day has >5 entries" — the `>5` upper bound is fuzzy. Joey just gave us a concrete anchor:

```python
# scripts/r0_check1_trigger_density.py
ACCEPTABLE_MEDIAN_ENTRIES = (1, 5)    # Joey runs 3-5; we accept 1-5 median
ACCEPTABLE_P95_ENTRIES    = 10        # allow fat right tail for squeeze days

result = check_trigger_density(
    data=load_952_day_spxw_0dte(),
    confluence_threshold=3,
    session_filters=["no_open_15min"],   # per Joey intel #17
)

if result.median_entries_per_day < ACCEPTABLE_MEDIAN_ENTRIES[0]:
    raise CheckFailed("too strict — would produce no trades on median day")
if result.median_entries_per_day > ACCEPTABLE_MEDIAN_ENTRIES[1]:
    raise CheckFailed("too loose — would trade more than Joey's live freq")
if result.p95_entries_per_day > ACCEPTABLE_P95_ENTRIES:
    raise CheckFailed("fat tail — squeeze-day stacking would blow risk budget")
```

**Why:** before Joey's intel, we had no principled target for trigger firing rate. Now we do. If our confluence ≥ 3 rule produces 20 entries/day median, we know the threshold is too loose — raise it. If it produces 0.5, too strict — lower it.

---

### 5. Regime filter: weak-trend no-trade + squeeze scaling `[POST-CHECK]` **⚠️ PARTIALLY FALSIFIED 2026-04-21 — see docs/validation_summary_2026_04_21.md**

> **Update 2026-04-21:** V4 empirically tested whether a 30-min open-range
> z-score can prospectively identify weak-trend days at 10:00 ET. Result
> on 947 days: precision 0.34, recall 0.38 — both below kill threshold
> (0.55 / 0.40). **The "free alpha" framing is dead in this form.** The
> mechanism (Joey loses money on weak-trend) remains plausible, but the
> specific claim "we can filter weak-trend days prospectively" requires
> a classifier we do not yet have. Do NOT implement the pseudocode below
> as-is — it would gate away true positive trading days at a 66% false
> positive rate.
>
> Squeeze-regime scaling (second half of this section) is not affected by
> V4 and remains a live candidate.


**File:** `src/signal/regime.py` (new) + `src/signal/generator.py`
**Joey intel:** #18 (squeeze stacking), and his admitted weak-trend vulnerability.

Weak-trend is Joey's largest free alpha to hand us. From `joey_payoff_model.py`:

```
Regime           Net win %  Net loss %   BE WR
strong_trend        370.0%      -70.0%   15.9%
squeeze             270.0%      -70.0%   20.6%
weak_trend           50.0%      -70.0%   58.3%    ← requires 58% WR
```

Joey's own reported WR is ~70% overall — comfortably above 58%. But that's an average across regimes. Weak-trend days, winners collapse and the 70% WR probably drops to ~40–50% because of `theta`. **Result: Joey likely loses money on most weak-trend days but recovers on squeeze days.**

We can do better by not trading weak-trend days at all:

```python
# src/signal/regime.py
def trend_strength(features_30min) -> Literal["strong_trend", "chop", "weak_trend"]:
    """Measured at 10:00 ET on the first 30 minutes of trading.

    - realized_range_pct = (high_30m - low_30m) / vwap_30m
    - atr_ratio = realized_range_pct / rolling_atr_30m(20d)

    Joey intel #17 says no signals fire in first 15 min; we compute regime
    on the 09:30-10:00 window and gate entries starting 10:00.
    """
    atr_ratio = realized_range_pct / rolling_atr_30m_20d
    if atr_ratio > 1.20:
        return "strong_trend"
    if atr_ratio < 0.60:
        return "weak_trend"
    return "chop"


def squeeze_detector(flow, gex) -> bool:
    """Systematize Joey's manual 'squeeze 日咔咔好几单' rule."""
    return (abs(flow.net_delta_flow) > flow.rolling_95th
            and gex.dealer_gamma < gex.p10_30d)


# src/signal/generator.py
if regime == "weak_trend":
    return None                         # NO TRADE — Joey's biggest leak
if squeeze:
    plan.kelly_multiplier = 1.25        # within quarter-Kelly budget
    plan.time_stop_minutes = 60         # extend from default 30
else:
    plan.kelly_multiplier = 1.00
    plan.time_stop_minutes = 30
```

**Why this beats Joey:** he does both weak-trend handling and squeeze stacking **manually, inconsistently**. Systematizing removes human-in-the-loop error. He admitted (WeChat screenshot 1) that he changed his rule to "吃弱趋势" over the weekend and was punished on Monday — that's the exact brittleness we avoid.

---

## Prioritization (ROI × effort)

| # | Optimization | Impact | Effort | Gated by |
|---|--------------|--------|--------|----------|
| 4 | Trigger density calibration | High | S | [NOW] |
| 5 | Weak-trend no-trade + squeeze scaling | **Very high** | M | r0_check2 pass |
| 2 | ResilientFillPolicy exit state machine | High | M | r0_check3 pass |
| 1 | Adaptive Kelly downgrade | Medium | S | r0_check3 pass |
| 3 | Stop-loss regime validation | Medium | S | r0_check2 pass |

---

## Explicit anti-goals (do NOT do these based on Joey intel)

- **Do not** copy Joey's `-40% stop` blindly without regime-conditional validation.
- **Do not** remove our 4-tier OOS + bootstrap CI infrastructure to "go faster like Joey." Joey's speed comes from skipping validation — it's a liability, not an advantage.
- **Do not** try to replicate his `massive.com` data by scraping / proxying. Our Theta Pro + Lee-Ready signer is adequate for pre-check validation. Data upgrade is gated behind paper-trade-proven baseline edge.
- **Do not** try to per-symbol-specialize to NVDA/TSLA/MRVL yet. Joey's edge there comes from months of iteration we haven't done. SPX/SPY first, OOS must clear, only then expand.
- **Do not** compile signal directly to 4-tuple order (Joey's architecture). Keep our trade_plan abstraction — it's a structural advantage precisely because it's not what he has.

---

## Reference

- `docs/joey_bot_extracted_specs.md` — source data points
- `docs/joey_payoff_model.py` — executable baseline
- `HANDOFF.md` — Action 0–6, gates Phase 3–6 work
- `ARCHITECTURE_JOEY_REBUILD.md` — R0 pre-registration (pending Ultra Review amendments)
