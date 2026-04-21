# Reference 0DTE Bot — Specification Notes

**Source:** field research observation of a live 0DTE bot reference system
(2026-04-20). 18 parameter observations extracted to serve as a reference
baseline for our R0 architecture: where to match, where to diverge, where
to exceed.

**Status:** each row below is a direct observation. "Inference" rows are
our extrapolation and labeled as such.

---

## 18 Observations

| # | Observation | Type |
|---|-------------|------|
| 1 | Bot output schema = `(ticker, contract, size, fill_order)` 4-tuple, sent directly to broker execution link | Direct |
| 2 | `size` = `equity_fraction × 0.25 × Kelly_fraction` (quarter-Kelly × position percentage) | Direct |
| 3 | `fill_order` = limit order, price fixed at counter-side (buy at ask, sell at bid) to guarantee fill | Direct |
| 4 | Exit = limit at bid, assumes fill is guaranteed because ticker liquidity is high enough; **no-fill behavior undefined** | Direct + critical gap |
| 5 | Claim: spread cost does not materially affect this strategy (edge large enough) | Direct (belief, not independently verified) |
| 6 | Caveat added when pressed: for high-freq/thin-edge strategies the spread cost DOES matter | Direct |
| 7 | **Hard stop loss = −40% of premium** | Direct |
| 8 | Typical winner = +300% of premium (gross) | Direct |
| 9 | **No daily loss cap. No kill switch.** | Direct (critical) |
| 10 | Justification for #9: OTM convexity + Kelly sizing provides mathematical self-capping | Direct |
| 11 | Transaction cost: slippage $1 + commission $1 open + $1 close = **$3 per contract round-trip** | Direct |
| 12 | +300% number is **gross**, not net — operator never normalized for slippage/commission | Direct |
| 13 | Frequency: 3–5 entries/day | Direct |
| 14 | Holding time: **10–60 min intraday swing** | Direct |
| 15 | Self-identifies as "low-frequency" strategy; high-freq spread capture is infeasible without institutional fee structure | Direct (strategic) |
| 16 | Portfolio-level concurrency: holds multiple tickers simultaneously | Direct |
| 17 | Hard session filter: **no signals fired in first 15 min of regular session** | Direct |
| 18 | Regime-aware scaling: on squeeze days the bot stacks multiple back-to-back entries and extends holding to the 45–60 min upper bound | Direct (behavioral) |

---

## Payoff Math (reference operator's self-reported numbers)

### Gross (as quoted)
```
Typical loss:     -40%  of premium   (hard stop)
Typical win:      +300% of premium   (no stated cap)
Break-even WR:    40 / (40 + 300)   =  11.76%
```

### Net (after $3 round-trip cost, assuming $10 typical premium/contract)
```
Typical loss net:  -40% × $10 - $3  =  -$7.00  =  -70%
Typical win net:   +300% × $10 - $3 =  +$27.00 = +270%
Break-even WR:     70 / (70 + 270)  =  20.6%
```

### Regime-conditional (inference)
| Regime | Net win | Net loss | Break-even WR |
|--------|---------|----------|---------------|
| Squeeze / strong trend | +370% | −70% | 15.9% |
| Chop | +170% | −70% | 29.2% |
| **Weak trend** ⚠️ | **+50%** | **−70%** | **58.3%** |
| Event day | +170% | −70% | 29.2% |

**The reference operator's single largest hidden vulnerability = weak trend.**
Winners collapse (because 0DTE OTM needs meaningful movement to print);
losses remain fixed at −40%. Break-even WR jumps from ~12% to ~58%.
Operator acknowledges weak trend is the hardest regime but has not
implemented a weak-trend no-trade gate.

---

## Architecture Gaps (explicitly lacking in the reference system)

1. **No trade_plan layer** — signal compiles straight to the 4-tuple. No invalidation, no time stop, no exit policy, no confidence score carried through.
2. **No-fill handling undefined** — if limit @ bid doesn't fill, behavior is not specified; default is "trust liquidity."
3. **No daily loss cap / no kill switch** — relies entirely on Kelly sizing + OTM payoff asymmetry for risk control.
4. **No systematic regime filter for weak trend** — relies on manual judgement; reports being caught out when rule was changed to attempt weak-trend trading.
5. **No net-PnL accounting** — operator never did the math. The +300% figure is gross.
6. **No formal OOS validation** — subjective overfit detection only.
7. **Liquidity gate is implicit** — ticker universe is hand-picked (SPX, SPY, QQQ, and select Mega7), not runtime quote-driven.

---

## Architecture Strengths (to preserve or copy)

1. **Low-frequency, high-confidence entry** — 3–5/day means confluence is tight. Matches payoff asymmetry.
2. **Quarter-Kelly sizing on equity fraction** — industry-standard bankruptcy-aware sizing.
3. **Aggressive limit @ counter-side** for fill certainty — the right tradeoff for intraday 0DTE: paying spread < missing fills.
4. **Opening 15-min no-trade** — cleaner GEX + flow snapshots after settle.
5. **Regime-aware manual scaling** — squeeze days = more entries, longer holds. (Behavior we should systematize.)
6. **Rule-based, not ML** — operator attempted ML and abandoned it. Consistent with Ultra Review's "don't re-introduce boosted trees" verdict.

---

## Our Competitive Map (after this intel)

| Dimension | Reference | Us (current / R0 target) | Delta |
|-----------|-----------|--------------------------|-------|
| Raw option-structure features | ✅ | ✅ | 0 |
| Signed net-flow data source | ✅ (L2 WS ~$200/mo) | ❌ (Theta Pro $40) | **Reference ahead by data access** |
| Aggregation / cross-feature grid search | ✅ (few hundred tried) | ❌ | **Reference ahead by trial-and-error hours** |
| Per-symbol feature specialization | ✅ | ❌ (SPX/SPY only) | **Reference ahead** |
| Rule-based signal (no ML) | ✅ | ✅ | 0 |
| Quarter-Kelly sizing | ✅ fixed | ✅ base + VIX scaling + direction correlation penalty | We ahead (richer) |
| Aggressive limit fill | ✅ | 🆗 (backtest uses mid+35%; should match live @ ask/bid) | Needs alignment |
| Opening 15-min no-trade | ✅ | ✅ (our OPENING session is 30 min — stricter) | We ahead |
| Concurrent multi-ticker | ✅ | ✅ (already built into risk manager) | 0 |
| Exit no-fill state machine | ❌ undefined | ❌ not yet implemented — **free alpha** | Neither has it; first to ship wins |
| Daily loss cap / kill switch | ❌ | ❌ but we plan adaptive Kelly downgrade | We can ship ahead |
| Weak-trend regime filter | ❌ (manual, inconsistent) | ❌ but we plan systematic gate — **free alpha** | We can ship ahead |
| Squeeze-regime scaling | ✅ (manual) | ❌ systematic version TBD | Convert manual rule to code |
| 4-tier OOS + bootstrap CI validation | ❌ subjective | ✅ | We ahead (substantially) |
| Academic literature grounding | ❌ | ✅ (Baltussen, Adams, Vilkov, Barbon-Buraschi) | We ahead |
| Net-PnL accounting (fills + costs) | ❌ | ✅ in progress | We ahead |

**Summary:** we trail the reference on exactly one dimension — raw
signed-flow data. Reference trails us on six dimensions. Four of our
advantages (no-fill state machine, adaptive kill switch, weak-trend
filter, systematic squeeze scaling) are **free engineering wins that
don't require new data**.

---

## Key strategic implication

Reference's edge is in **signal + execution speed of iteration** (months
of hundreds of feature combinations).
Our edge is in **validation rigor + engineering discipline** (leak_safe
pipeline, OOS tiers, adaptive risk controls).

The two are complementary. If R0 Check 1–3 pass, our target is NOT
"replicate." Our target is **"reference signal quality (approximately)
with our engineering quality."** The delta we can charge is on the four
free wins listed above.
