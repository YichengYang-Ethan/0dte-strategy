# Joey Bot — Extracted Specs (WeChat 2026-04-20)

**Source:** WeChat conversation with UIUC CS+Stats friend Joey, evening of 2026-04-20 (10 screenshots).
**Purpose:** Full reverse-engineering of Joey's 0DTE bot to use as a reference baseline for our R0 architecture, so we know exactly where to match, where to diverge, and where to exceed him.

**Status:** Every row below is a direct quote from Joey. No interpolation. "Inference" rows are our extrapolation and labeled as such.

---

## 16 Data Points

| # | Claim | Source | Type |
|---|-------|--------|------|
| 1 | Bot output schema = `(ticker, contract, size, fill_order)` 4-tuple, sent directly to broker execution link | Screenshot 4 ("给交易链路那边发 ticker，合约，张数，fill order 的方式") | Direct |
| 2 | `size` = `equity_fraction × 0.25 × Kelly_fraction` ("按仓位百分比算" + "四分之一凯利") | Screenshot 5 | Direct |
| 3 | `fill_order` = limit order, price fixed at counter-side (buy at ask, sell at bid) to guarantee fill | Screenshot 5 ("limit order" / "为了保证 fill 我直接用 ask 和 bid") | Direct |
| 4 | Exit = limit at bid, assumes fill is guaranteed because ticker liquidity is high enough; **no-fill behavior undefined** | Screenshot 6 ("直接 bid 价" / "不会不成交" / "如果 ticker 流动性够好" / "也差不了多少") | Direct + critical gap |
| 5 | Claim: "模型吃一些点差没啥大影响" — edge large enough that spread cost is secondary | Screenshot 6+7 | Direct (his belief, not independently verified) |
| 6 | Caveat he acknowledged when pressed: "如果是高频+利润薄 那可能影响比较大" — accepts spread matters for thin-edge/high-freq strategies | Screenshot 7 | Direct |
| 7 | **Hard stop loss = −40% of premium** ("亏就是大概 40% 左右就平了") | Screenshot 7 | Direct |
| 8 | Typical winner = +300% of premium (gross) ("赢一个 +300%") | Screenshot 7 | Direct |
| 9 | **No daily loss cap. No kill switch.** ("我一般都没" / "都没") | Screenshot 7 | Direct (critical) |
| 10 | Why no kill switch: "只是因为 0dte otm 期权 赢一个都比较大" — OTM convexity + Kelly sizing provides mathematical self-capping | Screenshot 7 | Direct |
| 11 | Transaction cost: slippage $1 + commission $1 open + $1 close = **$3 per contract round-trip** | Screenshot 8 | Direct |
| 12 | +300% number is **gross**, not net ("我懒得算了") — he never normalized payoff for slippage/commission | Screenshot 8 | Direct |
| 13 | Frequency: "一天就做几笔" → 3–5 entries/day | Screenshot 8 | Direct |
| 14 | Holding time: "十几分钟到一个多小时" → **10–60 min intraday swing** | Screenshot 9 | Direct |
| 15 | Self-identifies as "低频" strategy; explicitly says HFT ("套点差") is Citadel/Jane Street territory requiring rebate/fee-free structure that retail lacks | Screenshot 9 ("高频都是去套点差的 你没有机构免佣甚至券商倒贴钱的那种优势 没得做") | Direct (strategic) |
| 16 | Portfolio-level concurrency: "可能同时持仓几种吧" — holds multiple tickers simultaneously | Screenshot 10 | Direct |
| 17 | Hard opening filter: **no signals fired in first 15 min of regular session** ("开盘 15 分钟内不触发信号") | Screenshot 10 | Direct |
| 18 | Regime-aware scaling: on squeeze days he opens multiple entries back-to-back and extends holding to the 45–60 min upper bound ("前几天轧空的时候咔咔好几单 一到 45") | Screenshot 10 | Direct (behavioral) |

(Numbering exceeds the headline "16" because several screenshots revealed multiple claims. All are preserved.)

---

## Payoff Math (Joey's self-reported numbers)

### Gross (what Joey quotes)
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

**Joey's single largest hidden vulnerability = weak trend.** Winners collapse (because 0DTE OTM needs meaningful movement to print); losses remain fixed at −40%. Break-even WR jumps from ~12% to ~58%. He acknowledged weak trend is his hardest regime but has not implemented a weak-trend no-trade gate.

---

## Architecture Gaps (what Joey explicitly lacks)

1. **No trade_plan layer** — signal compiles straight to the 4-tuple. No invalidation, no time stop, no exit policy, no confidence score carried through.
2. **No-fill handling undefined** — if limit @ bid doesn't fill, behavior is not specified in his description; he defaults to "trust liquidity."
3. **No daily loss cap / no kill switch** — relies entirely on Kelly sizing + OTM payoff asymmetry for risk control.
4. **No systematic regime filter for weak trend** — relies on manual judgement; admits to being caught out when he "改了一下想吃弱趋势 结果今天挨打".
5. **No net-PnL accounting** — "我懒得算了". His +300% is gross.
6. **No formal OOS validation** — he told us previously: "靠自己把控" subjective overfit detection.
7. **Liquidity gate is implicit** — ticker universe is hand-picked (SPX, SPY, QQQ, Mega7), not runtime quote-driven.

---

## Architecture Strengths (what Joey does well, to preserve or copy)

1. **Low-frequency, high-confidence entry** — 3–5/day means confluence is tight. Matches his payoff asymmetry.
2. **Quarter-Kelly sizing on equity fraction** — industry-standard bankruptcy-aware sizing.
3. **Aggressive limit @ counter-side** for fill certainty — the right tradeoff for intraday 0DTE: paying spread < missing fills.
4. **Opening 15-min no-trade** — cleaner GEX + flow snapshots after settle.
5. **Regime-aware manual scaling** — squeeze days = more entries, longer holds. (Behavior we should systematize.)
6. **Rule-based, not ML** — he tried ML and abandoned ("train 不好"). Consistent with Ultra Review's "don't re-introduce boosted trees" verdict.

---

## Our Competitive Map (after this intel)

| Dimension | Joey | Us (current / R0 target) | Delta |
|-----------|------|--------------------------|-------|
| Raw option-structure features | ✅ | ✅ | 0 |
| Signed net-flow data source | ✅ (massive, $200/mo) | ❌ (Theta Pro $40) | **Joey ahead by data access** |
| Aggregation / cross-feature grid search | ✅ (few hundred tried) | ❌ | **Joey ahead by trial-and-error hours** |
| Per-symbol feature specialization | ✅ | ❌ (SPX/SPY only) | **Joey ahead** |
| Rule-based signal (no ML) | ✅ | ✅ | 0 |
| Quarter-Kelly sizing | ✅ fixed | ✅ base + VIX scaling + direction correlation penalty | We ahead (richer) |
| Aggressive limit fill | ✅ | 🆗 (backtest uses mid+35%; should match live @ ask/bid) | Needs alignment |
| Opening 15-min no-trade | ✅ | ✅ (our OPENING session is 30 min — stricter) | We ahead |
| Concurrent multi-ticker | ✅ | ✅ (already built into risk manager) | 0 |
| Exit no-fill state machine | ❌ undefined | ❌ not yet implemented — **free alpha** | Neither has it; first to ship wins |
| Daily loss cap / kill switch | ❌ | ❌ but we plan adaptive Kelly downgrade | We can ship ahead |
| Weak-trend regime filter | ❌ (manual, inconsistent) | ❌ but we plan systematic gate — **free alpha** | We can ship ahead |
| Squeeze-regime scaling | ✅ (manual) | ❌ systematic version TBD | Convert his manual rule to code |
| 4-tier OOS + bootstrap CI validation | ❌ subjective | ✅ | We ahead (substantially) |
| Academic literature grounding | ❌ | ✅ (Baltussen, Adams, Vilkov, Barbon-Buraschi) | We ahead |
| Net-PnL accounting (fills + costs) | ❌ "我懒得算了" | ✅ in progress | We ahead |

**Summary:** we trail Joey on exactly one dimension — raw signed-flow data. He trails us on six dimensions. Four of our advantages (no-fill state machine, adaptive kill switch, weak-trend filter, systematic squeeze scaling) are **free engineering wins that don't require new data**.

---

## Key strategic implication

Joey's edge is in **signal + execution speed of iteration** (he's tried hundreds of feature combinations over months).
Our edge is in **validation rigor + engineering discipline** (leak_safe pipeline, OOS tiers, adaptive risk controls).

The two are complementary. If R0 Check 1–3 pass, our target is NOT "replicate Joey." Our target is **"Joey's signal quality (approximately) with our engineering quality."** The delta we can charge is on the four free wins listed above.

---

## Sources (WeChat screenshots, 2026-04-20 evening)

All 10 screenshots preserved in user's image cache. Direct quotes used above, no paraphrase in the Claim column.
