# Realignment Check: Am I Back on Joey's Path, or Still Drifting?

**Question: after 1 month of work, I just realized I've been researching a project that is structurally different from my friend Joey's real 0DTE bot. I want a sanity check before I restart. Specifically: is the rebuild plan below actually Joey's path, or am I again going to end up somewhere else that happens to use the same data?**

## Context on how I got here

Original intent: replicate my friend Joey's SPX 0DTE bot. He claims 70% win rate, asymmetric payoff (wins double, losses ~40%), ~1 hour holding time, rule-based (not ML), $200/mo massive.com data, moomoo API execution.

What I actually built over the past month under your guidance:

1. **M1-M4 daily/overnight branch**: dead after leak-safe rebuild (Sharpe collapsed from 3.45 → 0.05-0.41 when median-spot leakage was fixed).
2. **Intraday 5-day MVP plan** (your prescription): Day 1 labels at fixed decision times 15:00 / 14:30 → 15:55. Day 2 features: flow/concentration/slow-state/interaction. Day 2.5 diagnostic found direction dead (max |r|=0.028), volatility signal visible (atm_gex_skew Q1 abs_ret 0.232% → Q5 0.111%). Day 3 confirmatory falsification on direction (all four baselines 48-52% concordance, Bonferroni p=1.0) + exploratory volatility branch (V1 state-only beats persistence by ΔR²=0.008, Bonferroni-significant).

Then I re-read a long WeChat transcript with Joey and realized how different his bot is from anything I've built.

## What Joey actually does (from transcript, verbatim extracts)

- **Instrument**: SPX 0DTE calls / puts / butterflies (ATM-ish). **Long gamma**, not short. "0dte 凸性收益,输 40% 赢翻倍."
- **Holding**: "持仓就几个小时吧" / "一个小时左右吧." Dynamic, not fixed-time exit.
- **Entry**: event / structure triggered, not fixed clock time. Examples he gave:
  - IV spikes creating MM gamma exposure (MM forced to move the underlying).
  - Price punching through or rejecting off call-wall / put-wall.
  - Vanna imbalance flips.
  - News being *used by MMs* as a tool; signal is the *unusual option flow before the headline*, not the headline itself.
- **Features (explicit list from his text)**:
  - GEX total
  - GEX skew
  - Call wall, Put wall
  - ATM IV
  - Vanna total
  - Net flow
  - Volume, bid/ask
- **Method**: rule-based. Grid search on weights across these features. "网格搜索权重" + 自己的 "融合特征".
- **Target**: he predicts a *closing point* for SPX, e.g. "目标去 7175", "最后收 7126", then uses the target as entry direction.
- **Data**: massive.com realtime websocket L2 ($200/mo). GEX/flow aggregated *from raw data himself*, not via gexbot-like API.
- **Execution**: moomoo API. Limit bid-ask, not market, not mid. Got bait-ordered on market orders.
- **Self-assessed capacity**: ~1M before it gets noticed.
- **Framing**: "美股市场其实是期权市场,股价是被期权劫持的" — predict what MMs are forced to do by their gamma book, not predict statistical regularities.

## What I built that's misaligned with Joey

| axis | Joey | Me (current) | aligned? |
|------|------|--------------|----------|
| instrument | SPX 0DTE long ATM call/put/butterfly | SPXW 0DTE | ✅ same product |
| direction | **long gamma** | drifted toward short vol after Day 2.5 | ❌ opposite |
| timing | event / structure trigger | fixed 15:00 decision | ❌ different |
| holding | dynamic ~1hr | fixed 15:00→15:55 = 55min | ❌ different philosophy |
| features | GEX skew + walls + ATM IV + **Vanna** + net flow + vol + bid/ask | delta/gamma-weighted flow + HHI + atm±1% GEX + interaction | ❌ missing Vanna, wrong wall definition |
| method | rule-based + grid search on feature weights | Pearson/Spearman + OLS + Bonferroni | ❌ different paradigm |
| target | predict price level MM is pinned to | regress signed_ret_pct / realized_var | ❌ different problem |
| data | massive.com L2 WS | Theta Data REST parquet | ✅ close enough |
| execution | moomoo limit | not implemented | — |

The Day 3 result I got last night — "V1 atm_gex_skew adds ΔR²=0.008 over persistence for realized_var, Bonferroni-significant, exploratory flag" — is a perfectly valid statistical result that has **nothing to do with Joey's bot**. Joey isn't running OLS; Joey is buying ATM calls when spot is about to get pinned to 7175 because the MM book forces it there.

## My proposed rebuild plan (Option 1 restart)

Throw away the feature parquet + fixed-time framework. Keep the historical data, leak-safe primitives, and labels (as reference). Rebuild over 5 days:

**R1**: Vanna aggregation. Check if Theta Data v3 greeks endpoint returns vanna; if not, compute vanna = ∂Delta/∂σ via BSM from existing IV/delta/spot/strike. Produce minute-level `vanna_total`, `vanna_call`, `vanna_put` series.

**R2**: Call Wall / Put Wall detection at minute resolution. Wall = argmax(GEX) per side, with "thickness" = peak GEX / total GEX. ATM IV rolling z-score (30d shift-1) for IV-spike detection. Net flow and imbalance features.

**R3**: Event trigger framework, minute-by-minute (not fixed 15:00). Triggers:
 - spot crosses call/put wall (from outside → inside, or inside → outside)
 - ATM IV spikes (z > 2)
 - Vanna total flips sign
Target: in next 60 minutes, does spot touch call wall, put wall, or neither? (Three-class label, not regression.)

**R4**: Long-gamma PnL simulation. For each trigger, buy ATM call or put depending on trigger direction, hold 60min or exit on +100% / -40% stop-move. Use quote bid-ask mid + 2% round-trip slippage. Aggregate trades → win rate, avg win, avg loss, Sharpe.

**R5**: Grid search + walk-forward. Search over trigger thresholds (IV z, Vanna z, wall-distance) on first 3 years, test on last year OOS. Stop/go criteria: OOS Sharpe ≥ 1.0, win rate ≥ 55%, PnL ratio ≥ 1.5.

## My questions for you

**Question 1**: is this rebuild plan actually Joey's path, or am I going to end up somewhere third again because I'm re-constructing Joey's bot by inference, not by his spec? Concretely, are the R1-R5 features/triggers/targets the *right* family, or are there elements of his framing I'm still missing (e.g. dealer pinning mechanics, specific wall-breach vs wall-rejection asymmetry, Vanna term-structure across strikes not just total)?

**Question 2**: the "predict SPX closing point then trade toward it" framing is *forecasting a target price*, not predicting a regression R². I've been doing the latter. Is the rebuild target ("in next 60min, does spot touch call wall / put wall / neither") the right reformulation, or should it be closer to Joey's actual behavior — *produce a single point estimate for EOD close, and entry logic is "go long the side spot has to travel through to reach the estimate"*? If the latter, the target is EOD close price prediction and the model is a regression on point estimate; the entry is pure geometry.

**Question 3**: Joey explicitly said he uses **rule-based + grid search**, not ML. My intuition after a month of being corrected by you on pre-registration purity is to still use walk-forward, full-family Bonferroni, leak-safe primitives, etc. Is there a tension here, or does rule-based + grid search still require pre-registered trigger thresholds to avoid the same overfitting you already caught me doing? How should I design a grid search that isn't just a laundered version of "find the thresholds that worked in-sample"?

**Question 4**: the volatility result I just produced (V1 ΔR²=0.008 Bonferroni-sig, exploratory flag) — is it scientifically correct to **archive this as a legitimate finding on a separate branch** even though it's structurally unrelated to Joey's bot? It may be real, just not what I'm trying to build. Or do I kill it because continuing to work on a short-vol result while claiming to rebuild Joey's long-gamma bot is the same self-deception that got me here?

**Question 5**: I am **not going to ask Joey for more details**. I will rebuild entirely from the transcript extracts above + public literature + my own inference. Given I cannot ask him clarifying questions, what are the highest-leverage ambiguities in his spec that I have to *decide for myself* before R1? Specifically:
- Wall definition (single-strike argmax vs top-3 vs kernel-smoothed mode)
- Vanna aggregation (per-strike sum vs OI-weighted vs flow-weighted)
- "IV spike" operational definition (ATM IV absolute z, or IV change z, or vol-of-vol?)
- Event trigger confirmation logic (one trigger fires → enter, or two-of-three confluence?)
- Price-target prediction method (regression on structure features, or rule-based geometry: "spot → nearest wall")
For each, pick the version **most consistent with his transcript evidence** even if ambiguous, and justify.

**Question 6**: is there any scenario where the honest answer is "Joey's edge is probably partially overstated; rebuild to his spec and you'll get a Sharpe 0.5 bot not a Sharpe 3 bot"? If yes, what's the early detection signal (in R1-R4) that lets me kill this at cost before R5 grid search? Since I cannot validate against Joey himself, this early-kill criterion is critical — it's my only defense against 5 more days of work on a 0.3-Sharpe lookalike.

## What I want back

- Brutal verdict on whether R1-R5 is Joey's path or my third drift.
- Concrete correction on target formulation (Q2).
- Pre-registration design for rule-based + grid search (Q3).
- What to do with the live volatility finding (Q4).
- Resolution of 5 ambiguities in Joey's spec that I have to decide unilaterally (Q5).
- Early-kill criterion if Joey's edge is overstated (Q6).

I need the brutal version. **I am not asking Joey any more questions** — the rebuild must work from his transcript + public literature + my own inference, or not at all. If you think the right answer is "stop trying to clone Joey, build your own thing from the short-vol result," say so. If you think the right answer is "you can't do this without L2 realtime WS data; Theta Data parquet fundamentally can't reproduce Joey's bot," say that too. I will stop spending if that's the verdict.
