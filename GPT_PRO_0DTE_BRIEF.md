# GPT Pro Research Brief — Intraday 0DTE Options Bot Design

## Context

New project. Building a fully automated intraday 0DTE options trading bot on SPX (cash-settled European options). A reference practitioner runs a production version of this strategy on moomoo, so I have (1) a concrete reference architecture to reason about, and (2) a candid record of how it works. This brief is a from-scratch design request — not a validation of existing work.

**Extended thinking + brutal honesty requested.** I want you to challenge the mechanism, the data pipeline, the execution design, and the expected economics.

## The strategy thesis (from the reference implementation)

Direct quotes from the reference practitioner:
- "I basically follow the market maker"
- "My job is to predict what the market maker will do"
- "Longs and shorts use options to hijack the MM → MM then pushes the price"
- "[MMs] will push price toward the strike where they make the most money, because they hold huge option positions themselves"

In academic language: MMs are **profit-maximizing agents holding significant option book**, not neutral hedgers. When customer flow concentrates at a strike K (via OI buildup + IV spike + aggressive buying), MM's delta hedging becomes constrained; combined with their own book, they have mechanical incentive to push spot toward the strike that minimizes their book loss. This is the **active MM repositioning thesis**, distinct from the traditional "passive dealer short-gamma pinning" narrative.

Relevant literature: Barbon & Buraschi "Gamma Fragility" (SSRN 3725454). Adams/Fontaine/Ornthanalai (SSRN 4881008, 2024 Fed paper) argues MMs match 0DTE flow — which complicates the traditional "dealer short gamma → mechanical hedging" story but does not rule out active profit-driven MM repositioning.

## Production reference — actual implementation

- **Platform**: local Python + moomoo API
- **Data**: uses L2 websocket provider (approx $200/mo tier)
- **Asset focus**: SPX index 0DTE primarily; also individual tickers (NVDA, MRVL, NFLX, CRDO, TSLA)
- **Holding time**:
  - Individual tickers: minutes to ~1 hour (fast moves)
  - SPX: 1–3 hours (slow grind)
- **Payoff profile** (self-reported, unverified):
  - Win rate: ~70%
  - Win size: +100% to +1500% of premium (convex lottery right tail)
  - Loss size: ~−40% (capped by exit, not let expire worthless)
- **Order type**: originally market orders → got "hunted by fake-depth", switched to **limit bid-ask** (not mid)
- **Execution bug**: bot occasionally lets +120% winners turn into losses due to exit logic error
- **Capacity**: self-estimated $1M hard cap before MM hunting
- **Validation discipline**: none formal — "grid search historical, subjective overfitting threshold, no walk-forward CV"
- **Features**: 11 raw (GEX total / GEX skew / call-wall / put-wall / ATM IV / Vanna total / bid-ask spread / DTE / volume / price range / L1-L2 order book / symbol blacklist) + "aggregated and combined features picked via trial-and-error" + per-symbol specialization

### Specific trade example (actual bot output as described)

For SPX at some recent date:
1. Detected strike 7175: put OI surged + ATM IV went 12 → 16 (extreme spike) + sustained aggressor-side buying
2. Inferred: large customer shorting gamma, MM book now concentrated around 7175
3. Predicted: MM will push spot toward 7125 (identified as "long cost line")
4. Trade: bought 7125-strike butterfly
5. Outcome: spot dragged from 7126 toward 7146 intraday; 7125 touched later in day
6. Bot exit: not described in detail

### Red flags on the self-report

- 70% WR is mental estimate, no broker blotter shown
- "8 consecutive days correct SPX close prediction" claim
- Bot has admitted exit bug that distorts realized vs intended P&L
- Rich post-hoc narrative ("MM took over", "longs defended their cost line") that a rule-based bot cannot directly output without a natural-language layer
- When asked whether narrative is bot output or interpretation, the answer was "bot output" — either there is an LLM layer, or this is retconning

## Available infrastructure

- IB paper account with options permissions (full Greeks + OPRA)
- moomoo OpenD (local) as backup broker
- Python 3.14 on macOS
- Existing research infrastructure from an archived 1DTE project:
  - GEX/Vanna calculation code (`src/gex/`)
  - BSM Greeks computation
  - Fill simulator (mid + 35% spread, time-of-day widening)
  - 825 days SPY EOD option chain parquets
- Data budget: up to $360/mo
- Engineering budget: 6–12 weeks

## Not available

- Tick-level 0DTE intraday history (only have EOD snapshots from Theta Standard)
- Aggressor-side signed volume (massive.com public docs show trades schema with price/size/exchange/conditions/timestamp/sequence but NO aggressor field — your prior round caught this)
- Cboe Open-Close participant/buy-sell/open-close classification
- L2 depth of book history
- Bloomberg terminal

## Questions for this round

### Q1. Is the "active MM repositioning" thesis mechanism valid?

Is the framing — MMs as profit-maximizing agents that actively push spot toward strikes minimizing their book loss — consistent with modern 0DTE microstructure research? Or is it retail folklore dressed up?

Specifically:
- Does Barbon & Buraschi "Gamma Fragility" support MM **active** pushing, or only passive delta hedging?
- How does Adams 2024's "MMs match flow" result interact with this?
- Is there peer-reviewed work on MM P&L optimization around 0DTE pin strikes?
- If the thesis is partially valid, which market regimes strengthen/weaken the effect (VIX level, trending vs choppy, specific macro events)?

### Q2. What is the correct feature set for an intraday 0DTE bot?

Reference uses 11 raw features + "aggregated and combined features picked empirically". Without paying for massive or Cboe Open-Close, what features are constructible from Theta Options Pro ($160/mo: every OPRA NBBO quote + every trade with size/exchange/conditions + 1-min Greeks + streaming OI updates)?

Specifically:
- Can tick-rule-based aggressor signing (Lee-Ready or quote-based) substitute for massive's claimed signed flow? If so, with what accuracy loss?
- What aggregation windows matter most for 0DTE pressure detection (5m / 15m / 30m)?
- Is running GEX/Vanna at 1-min intervals using intraday snapshot OI + 1-min Greeks reliable, given OI is a stock variable that updates daily not tick-by-tick?
- What is the minimum feature set to replicate reference-level performance (even with 50% haircut)? What features require premium data that cannot be substituted?

### Q3. Execution design for intraday 0DTE via IB API

Target broker: IB (not moomoo). Specifically for SPX 0DTE:
- Limit order at bid-ask (reference style) vs. mid vs. adaptive — what's the correct default for fast markets?
- How to handle partial fills on 1-hour intraday scalps — cancel the remainder at time-stop, or keep working?
- Should I use native OCO orders for stop-loss + profit-target, or manage exit in code?
- SPX options trade 8:30am-3:00pm CT — what is the optimal time-of-day for signal generation vs. execution (e.g. avoid first 30 min of session)?
- Complex-order tickets for butterflies / spreads vs. legging in — which is robust in live 0DTE?

### Q4. What is the realistic Sharpe after real-world frictions?

Assume:
- Win rate: 55% (haircut from reference's claimed 70%)
- Win size: +60%
- Loss size: −40%
- Execution slippage: 10% of premium per round-trip
- Trade frequency: 3-5 signals per day
- Position size: 1-5 contracts, scaling with account equity

What's the realistic Sharpe ratio, expected max drawdown, and required sample size before conclusions are statistically defensible?

### Q5. Validation methodology for 0DTE

What's the right validation approach for an intraday bot with 1-hour holds?

- Walk-forward window size (days vs weeks vs months)?
- Cross-validation — CPCV, purged K-fold, or something 0DTE-specific?
- How to handle regime dependence (low-VIX grind vs high-VIX panic vs macro-event days)?
- What's the minimum number of live paper-trade signals before I can reject H0 that the strategy is noise?
- Given the convex payoff distribution, what's the correct bootstrap method (iid block vs stationary bootstrap, block length)?

### Q6. Specific engineering roadmap — 6 to 12 weeks

What's the correct phase ordering?

Proposed phases:
1. **Week 1-2**: Intraday data recorder (Theta Options Pro streaming → local parquet, SPX only)
2. **Week 3-4**: Intraday engine rewrite (bar-level replay, 1-min bars, feature pipeline)
3. **Week 5-6**: Core signal rules (v1 — "MM pressure detected + target strike predicted" → limit order)
4. **Week 7-8**: Execution engine (IB limit bid-ask orders, TP/SL, time stop, partial fill handling)
5. **Week 9-10**: Paper trade validation (30-50 live signals)
6. **Week 11-12**: Validation + decision (live deploy vs iterate vs kill)

Should I reorder anything? Are any phases underestimated? Is 30-50 paper signals enough given the convex payoff distribution?

### Q7. Red flags I should test for in my own build

What specific things would indicate my 0DTE bot is (a) overfit to historical data, (b) leaking information in backtest, (c) inflating fills that won't happen live, (d) misidentifying MM pressure when it's actually just normal retail noise?

### Q8. When to abandon this project

What quantitative criteria would cause you to kill this project partway through and revert to a simpler strategy? Be specific: "if paper trade WR < X after N signals, stop" type thresholds.

## Format for your response

Section-by-section answers to Q1-Q8. Prioritize Q1 (mechanism validity), Q2 (feature set), and Q6 (roadmap). Extended thinking. Brutal honesty. If the answer is "this is a lottery disguised as a strategy and you should spend the 6-12 weeks on something else," say so explicitly.

Do not pull punches. A prior 1DTE project has been archived; this is a committed pivot. Stress-test the 0DTE design before engineering begins, not politely after.
