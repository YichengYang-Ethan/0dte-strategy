# GPT Pro Handoff Brief — 2026-04-20 (Post-the reference operator-Intel)

**Paste this entire file into a fresh GPT Pro session. It is self-contained.**

---

## Who I am

Undergraduate researcher, building a 0DTE SPX/SPY options
strategy. I am the sole operator. I do not have institutional resources,
no rebate / fee-free trading, no L2 WebSocket data. I pay for Theta Data
Pro ($40/mo) and have 952 trading days of SPXW 0DTE parquet files
(2022-07-01 to 2026-04-16, ~16 GB on disk, minute-resolution quote + trade).

This project is not a toy. I have ~2,556 LOC across `src/` and ~40 scripts.
It has already survived 4 rounds of your own prior review + 1 Ultra Review.

## What you have done for me before (truncated)

- **Round 1–2**: killed OI-delta as flow proxy (identification failure).
- **Round 3**: three paths (A/B/D) for realignment; I chose D (practitioner rebuild).
- **Round 4 (Realign)**: warned me I am using EOD data to chase an intraday
  mechanism — instrument/horizon mismatch.
- **Round 5 (Theta)**: warned me against feature search as manufactured alpha.
- **Ultra Review**: 5 ranked amendments to R0 (T_disc discrete target, promote
  §9 known-unknowns, 3-day pre-check before R1, calibrate kill gates against
  unconditional long SPX, collapse fixed-vs-grid ledger).

All prior verdicts stand. Do not retract them. Do not re-litigate unless
new evidence contradicts them.

## What happened 2026-04-20 (new evidence)

I reverse-engineered the reference operator's live 0DTE bot through a field research
conversation (an observation session, 18 direct data points). the reference operator has been running
the reference bot for ~2 months, claims 70% WR, holds 10–60 min per trade, 3–5 trades
per day, pays for massive.com L2 WS ($200/mo) for aggressor-tagged flow.

Extracted specs (verbatim where possible), stored in
`docs/peer_bot_extracted_specs.md`:

1. Output schema = `(ticker, contract, size, fill_order)` 4-tuple, no trade_plan abstraction
2. Sizing = 1/4 Kelly × equity fraction
3. Entry fill = limit at ask (pays full spread for certainty)
4. Exit fill = limit at bid, assumes liquidity is always sufficient — **no-fill behavior is undefined**
5. Claim reports "spread cost doesn't matter for my strategy"
6. Caveat he accepted: "for high-freq / thin-edge strategies it does matter"
7. Hard stop loss = **−40% of premium**
8. Typical winner = **+300% of premium (gross)**
9. **No daily loss cap. No kill switch.**
10. Justification for #9: OTM convexity + Kelly self-caps mathematically
11. Transaction cost: $1 slippage + $1 open + $1 close = $3 per contract RT
12. +300% is **gross**, not net — (reports: never normalized) (he never normalized)
13. Frequency: 3–5 entries/day
14. Holding: 10–60 min
15. Universe: SPX, SPY, QQQ, NVDA, TSLA, MRVL
16. Concurrent multi-ticker positions allowed
17. Hard session filter: no signals in first 15 min after open
18. Squeeze days: stacks multiple back-to-back entries and extends holding to upper bound

I then encoded this as `docs/peer_payoff_model.py` (runnable; prints
break-even WR by regime). Key output:

```
Regime           Net win %  Net loss %   BE WR
strong_trend        370.0%      -70.0%   15.9%
squeeze             270.0%      -70.0%   20.6%
chop                170.0%      -70.0%   29.2%
weak_trend           50.0%      -70.0%   58.3%   ← the reference operator's weakness
event_day           170.0%      -70.0%   29.2%
```

And a 5-point optimization map in `docs/strategy_delta_vs_peer.md`.

## What my codebase actually looks like (not what HANDOFF claims)

I just did a deep code review. There is drift between the docs and the code:

- **`src/signal/generator.py`** is v5 **swing_1dte** rules (NEG_GAMMA +
  `position_in_range < 0.15` → BULLISH 0.70Δ 1DTE call). This is the
  1DTE archived strategy, not an intraday 0DTE signal generator.
- **`src/pipeline/leak_safe.py`** (439 LOC) provides intraday primitives
  (`close_spot_leak_safe`, `compute_day_flow_leak_safe`, `realized_variance`,
  labels, future-poison test). These are NOT plumbed into generator.py.
- **`src/risk/manager.py`** already has: quarter-Kelly, VIX inverse scaling,
  direction correlation penalty, **`max_daily_loss = $500`**,
  **`max_trades_per_day = 5`**, `no_trade_before = "09:45"` (matches the reference operator's
  15-min open filter). In other words, we already exceed the reference operator on risk
  plumbing — I had mis-described this in `strategy_delta_vs_peer.md` §1.
- **`src/backtest/fill_simulator.py`**: entry = mid + 35% half-spread + 5bps,
  exit = bid + 10% spread. Round-trip spread cost ≈ 57% of full spread.
  **the reference operator live pays 100% of spread**. Our backtest is 43% more optimistic
  than his live execution.
- **`src/backtest/engine.py`**: 713 LOC, hard-coded for swing_1dte mode.
  Intraday backtest support is not built.
- Data: 468,887 parquet files spanning 2022-07-01 to 2026-04-16, with
  `quote/` directories at per-strike granularity. This is more data than
  I realized.

So the actual architectural gap is: **I have leak-safe intraday
primitives and 3.5 years of quote-level 0DTE data, but my signal generator
and backtest engine are still 1DTE swing.** The R0 practitioner rebuild is
conceptually pre-registered but not written.

## What I am NOT asking you

- "What's my next step" — HANDOFF.md has Actions 0–6.
- "Should I add feature X" — you already forbade this in Round 5.
- "Validate my plan" — I want the opposite: falsification.
- "Should I upgrade to massive.com" — gated behind paper-trade-proven edge.
- "Should I pivot" — no.

## What I AM asking (three questions, falsification only)

### Question 1 — Reliability of the reference-operator intel

18 parameter observations came from a casual field research session, not a research
interview. Friend is a competent CS undergrad, not an empiricist. No
data was shared beyond verbal claims.

Which specific claims in `peer_bot_extracted_specs.md` should I treat
as **unreliable** or prone to **narrative-overlay bias**, and why?
Specifically challenge:

- **+300% typical winner** — is this survivorship in his memory?
  He showed me one chart of a single great trade (+120% → lost).
  Memory of winners ≠ statistical winner distribution.
- **70% WR (self-reported)** — never validated by him, no blotter shown.
  Rule from your Round 5: self-reported Sharpe / WR from a non-rigorous
  researcher should be discounted by how much?
- **−40% hard stop** — is this an implemented rule, or post-hoc
  rationalization of exits that actually happen at −30% to −60%?
  Humans compress distributions to round numbers.
- **"no kill switch, Kelly is enough"** — mathematically the OTM
  payoff is bounded below (−premium) so Kelly-size × premium caps
  single-trade loss. But the reference operator admitted "没设" (doesn't have one).
  What's the empirical risk of absent kill switches when your own
  Round 5 attribution showed v5 / v7 had regime-dependent collapse?

For each claim you flag: name it, state what downstream conclusion it
invalidates in `strategy_delta_vs_peer.md`, and propose a specific test
I can run on my 952-day data to independently verify or falsify.

### Question 2 — Are the "five free wins" actually free?

`strategy_delta_vs_peer.md` claims five optimization points where I can
match or beat the reference operator without upgrading my data source:

1. Sizing — adaptive Kelly downgrade
2. Fill — ResilientFillPolicy with exit timeout state machine
3. Stop loss — regime-validate against −40% rather than copy
4. Trigger density — calibrate to 3–5/day baseline
5. Regime filter — weak-trend no-trade + squeeze scaling

For each: is this a genuinely orthogonal improvement, or am I confusing
**regime misclassification with regime filtering**?

Specifically #5: I claim weak-trend no-trade is "free alpha" because
the reference operator's net-PnL BE WR on weak-trend is 58.3% (from `peer_payoff_model.py`).
But this requires that my regime classifier correctly labels weak-trend
days **in advance** (at 10:00 ET). If my classifier is retrospective
and I'm filtering days that were already weak-trend in 30-min realized
range, I haven't discovered regime gating — I've discovered that removing
losing days improves PnL (trivially true).

Propose the specific identification test: what minimum condition must
`trend_strength(features_30min)` satisfy at 10:00 to prove the signal
is prospective and not retrospective? If this test fails, the "free
alpha" disappears.

### Question 3 — Gate ordering and possible replacement

HANDOFF.md pre-check order is:
- `r0_check1_trigger_density.py`
- `r0_check2_dumb_mae.py`
- `r0_check3_dealer_sign.py`

With the reference-operator intel in hand, evaluate:

(a) Is the ordering still correct? E.g. should `dealer_sign` move to
    first because the reference operator's whole premise (and ours) is dealer positioning,
    and if customer flow sign is regime-unstable everything downstream
    is garbage?

(b) Is any check now **partially redundant** with a simpler benchmark?
    Specifically: if I run our current v5 primitives on last-year 0DTE
    data under the reference operator's parameters (1/4 Kelly, −40% stop, limit @ bid/ask,
    3–5 entries/day cap, no-trade first 15 min), and the result is
    PF ≥ 1.0 on weak-trend days **without** any of the R0 architecture
    changes, what does that mean? Does it kill R0, validate the reference operator, or
    reveal that my current generator.py is already closer to the reference operator than
    I think?

(c) Is there a simpler check I'm missing that would cost 1 day and could
    kill the whole R0 direction if it fails? E.g. "compute realized
    hourly volatility on 2023 data, segregate by regime, does the reference operator's
    payoff geometry mathematically work at all given historical move
    distributions?" — a first-principles feasibility check before any
    feature work.

## Hard constraints on your answer

1. **No new features**, no new data sources, no new academic references.
2. **Do not propose a pivot.** I pivoted once (1DTE → 0DTE) and it cost
   a week. The bar for another pivot is: identified mechanism failure
   in empirical data I already have, not sophistication concerns.
3. **Do not soften the verdict.** If you flag a the reference operator claim as unreliable,
   name what invalidates, not how to salvage.
4. **Point to specific lines or sections** of the files cited above.
   Generic advice ("use better validation") is not useful.
5. **Length cap: 1500 words.** If you can't say it in 1500 words,
   I can't execute it this week.
6. **Do not propose massive.com / Theta Pro upgrade.** Irrelevant to the
   three questions.
7. **Do not re-validate Ultra Review's 5 amendments.** Those are accepted.

## Files you should treat as authoritative (read cold, don't guess)

When I give you this brief, assume you have read:

- `docs/peer_bot_extracted_specs.md` — 18 parameter observations + payoff math + architecture gaps
- `docs/peer_payoff_model.py` — runnable reference baseline
- `docs/strategy_delta_vs_peer.md` — 5 optimization points (**contains the
  `max_daily_loss` mis-description I already noted above — account for
  this when auditing**)
- `HANDOFF.md` — Ultra Review verdict + Actions 0–6
- `ARCHITECTURE_R0_REBUILD.md` — R0 pre-registration (pending Ultra
  Review amendments)

If any of those files contradict this brief, flag the contradiction
rather than resolving silently.

## What a useful answer looks like

```
Q1 Verdict:
- Claim X [unreliable / likely biased / reliable]
- Reason: [specific]
- Test I can run on my 952-day data: [specific]
- Downstream invalidation in strategy_delta_vs_peer.md §Y: [specific]
...

Q2 Verdict:
- Free win #1: [actually free / hidden dependency]
- Identification test required before claiming: [specific]
...

Q3 Verdict:
- Ordering: [keep / reorder and why]
- Redundancy: [yes / no]
- Missing simpler check: [yes + proposal / no]
```

No fluff. No restatement. No executive summary. Just these three
answer blocks.

---

**End of brief. Respond with three answer blocks only.**
