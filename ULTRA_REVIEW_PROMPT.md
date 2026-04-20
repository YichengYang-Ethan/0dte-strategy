# Ultra Review Request: Complete 0DTE Research Project Audit

## Context

I'm a UIUC CS+Stats+Econ student (4.0 GPA, F1 visa, job-hunting quant/SWE/DS
Summer 2026). I have spent roughly 1 month building an SPX 0DTE options
research pipeline, inspired by a friend's ("Joey") live bot. Along the way
I've paid for Theta Data ($40/mo), spent ~100+ hours, and gone through 4
rounds of external review with GPT Pro. Each round falsified a branch
and forced a pivot. I'm now at a pre-registration decision point for a
full-fledged 10-day rebuild.

**I have one Ultra Review left for the month.** I'm spending it on the
entire project, not on code-level nitpicks, because I need a brutal
outside view before committing another 10 days to rebuilding.

## Repository

**Public URL**: https://github.com/YichengYang-Ethan/0dte-strategy

Relevant artifacts (all on main):
- `README.md` — full project timeline
- `ARCHITECTURE_JOEY_REBUILD.md` — the R0 pre-registration for next 10 days
- `ARCHIVE_SHORT_VOL_BRANCH.md` — archival notice for discarded finding
- `GPT_PRO_REALIGN_JOEY_PATH.md` — most recent brief, with 6-question
  answer from GPT Pro pasted back
- `GPT_PRO_DAY2_5_UNEXPECTED.md` — target-snooping pivot question
- `GPT_PRO_M4_FALSIFICATION_COMPLETE.md` — daily-branch death
- `GPT_PRO_0DTE_BRIEF.md` — original project brief
- `src/pipeline/leak_safe.py` — leak-safe primitives (core reused code)
- `src/pipeline/intraday_features.py` — feature extraction (soon-archived)
- `logs/intraday_day3_report.md` — direction falsification + vol archive
- `logs/day2_5_diagnostics.md` — where the vol signal surfaced
- Other `GPT_PRO_*.md` files — full external review trail

Tags/branches:
- `main` — current state (post-realignment, R0 frozen)
- `v2-short-vol-exploratory-archive` — archived short-vol branch
- `archive/short-vol-exploratory` — ditto, accessible as branch
- `v1-1dte-archive` — prior 1DTE project, archived before 0DTE pivot

## What I actually did over 1 month (the trail)

1. **Phase A**: inherited 1DTE SPY swing research (signal PF 1.67,
   long-call wrapper ate 41% of edge). Archived in favor of intraday
   0DTE per GPT Pro Round 3.
2. **Subscribed Theta Data**, downloaded 952 days × ATM±3% SPXW 0DTE
   options (16 GB), 336M trade rows.
3. **Built Baseline 1** (signed flow → next-day return). Got Sharpe
   3.45. GPT Pro caught median-spot leakage; rebuilt leak-safe →
   Sharpe collapsed to 0.05-0.41. Daily/overnight branch **dead**.
4. **M4 baselines** (3 variants): all failed to beat unconditional
   long SPX. Branch fully falsified.
5. **GPT Pro Round 6 pivot**: daily/overnight dead, try **intraday**
   with a 5-day MVP plan (labels, features, diagnostic, baselines,
   plumbing, stop/go).
6. **Day 1-2**: built intraday labels (signed_ret_pct, abs_ret_pct,
   realized_var, t=15:00 → 15:55 ET) + features (F1 flow, F2
   concentration, F3 slow state, F4 interaction). All leak-safe, all
   future-poison verified.
7. **Day 2.5 diagnostic** (unplanned, honest): max |r| = 0.028, sign
   concordance 52%. Direction dead. **But** atm_gex_skew Q1-Q5
   quintile showed ~50% abs-return compression in Q5 — matches
   Dim-Eraker-Vilkov 2024 MM-gamma-vol result.
8. **Asked GPT Pro** whether extending Day 3 to volatility targets
   was target-snooping. Verdict: direction branch = confirmatory
   falsification; volatility branch = exploratory only, full-family
   Bonferroni (N=12), primary=realized_var, must beat persistence
   baseline.
9. **Day 3 ran both branches**. Direction: all 4 baselines 48-52%
   concordance, Bonf p=1.0. Volatility: V1 state-only beats
   persistence by ΔR²=+0.008 on primary (Bonf p=0.0009) and +0.014
   on robust (Bonf p=0.002). Real statistical finding.
10. **Re-read Joey's WeChat transcript** — realized my entire
    approach was structurally misaligned. Joey does **long gamma**,
    **event-triggered**, **price-target forecasting**, **rule-based
    grid search**, **Vanna + walls + butterflies**. I was doing the
    opposite on almost every axis.
11. **Asked GPT Pro** whether my rebuild plan (R1-R5) was Joey's path
    or a third drift. Verdict: closer, but still not Joey unless R3
    and R4 change formulation. Specific prescriptions:
    - Target engine (point estimate or band, not classifier)
    - Instrument chooser (butterfly/call/put by target geometry)
    - Dynamic exits
    - Conservative fills (ask-in / bid-out, not mid)
    - Nested walk-forward grid search
    - Three kill gates (R3/R4/R5), stop-don't-rationalize
12. **Pre-registered R0 architecture** in `ARCHITECTURE_JOEY_REBUILD.md`,
    frozen 2026-04-20. Archived short-vol branch. Updated repo.

## What I want from Ultra Review

**Read every MD file in the repo root, every log in `logs/`, and the
code in `src/pipeline/`. Then give me a brutal four-layer audit.**
Not a code review. A project-level audit.

### Layer 1: R0 architecture (the thing I'm about to execute)

Read `ARCHITECTURE_JOEY_REBUILD.md` in full. Evaluate:

1. **Does T1/T2/T3 target-engine family correctly encode Joey's
   transcript-stated mechanism?** Specifically: does "dealer-pinning
   toward argmax strike weighted by wall-thickness and persistence"
   map to his examples of SPX being "pulled to 7125" and "pinned at
   7175"? If not, what's the missing object — volatility-weighted
   barycenter? ES-basis-adjusted dealer hedge ratio? Something else?

2. **Is the 5-trigger confluence design under-specified?** Joey also
   references news as a MM tool and "abnormal option flow before
   headlines" — is that captured by `trigger_flow_confirm`, or is
   there a missing "news-leading-flow" trigger I'm ignoring?

3. **Are the three kill-gate thresholds right?**
   - R3: 10% MAE reduction over dumb baseline, 53% sign accuracy
   - R4: positive expectancy, 1.5× payoff ratio
   - R5: Sharpe > 1.0, Deflated Sharpe > 0, stable across 4 outer folds
   Are these too lenient, too strict, or miscalibrated against Joey's
   self-reported "70% WR / +100% wins / -40% losses"?

4. **Pre-registration ledger** — did I correctly split fixed vs
   grid-searched parameters, or did I launder a free parameter into
   "fixed" (e.g. IV spike z-threshold at 2 is arbitrary)?

5. **Explicit known-unknowns** (§9) — which of these will actually
   kill the project in practice vs which are acceptable to defer?

### Layer 2: Methodology across the 1-month trail

Read all `GPT_PRO_*.md` files plus `logs/`. Evaluate:

1. **Falsification discipline**: were M1-M4 and Day 3 direction
   branches killed cleanly, or did I rationalize through them?
2. **Pre-registration purity**: is the Day 3 "volatility was
   exploratory, direction was confirmatory" framing honest, or am I
   retroactively constructing the split?
3. **Leak-safety rigor**: Baseline 1 v1 (Sharpe 3.45 leaked) → v3
   (Sharpe 0.05, leak-safe). Are there other subtle leaks in
   `leak_safe.py` or `intraday_features.py` that future-poison tests
   miss? (Not every timing dependency is a timestamp dependency.)
4. **External review usage**: did I use GPT Pro's 4 rounds of
   feedback genuinely, or did I cherry-pick the parts that let me
   continue?

### Layer 3: Joey rebuild viability

This is the existential layer.

1. **Can you reconstruct a Joey-like bot from transcript extracts +
   public literature + own inference?** Or is the transcript too
   sparse and the literature too generic for this to succeed
   absent Joey's actual parameters?
2. **Data gap**: Joey uses Massive.com L2 realtime websocket. I use
   Theta Data historical parquet. Is this gap closable for
   research-stage backtest, or does live L2 order-book sequencing
   fundamentally change the signal?
3. **What's the honest upper bound on rebuild performance** given
   the constraints? If Joey's real Sharpe is 3 (self-reported), what
   should I expect: 2? 1? 0.3? What fraction of his edge is
   transferable by inference alone?
4. **Is there a scenario where the right answer is "stop trying to
   clone Joey, continue the short-vol finding as its own
   research"?** What would that look like economically — short
   straddle wrapper with 5% friction, can it clear Sharpe 1?

## Format of the answer I want

- **One-sentence verdict** per layer (3 verdicts).
- **Ranked list of 5 concrete changes** to `ARCHITECTURE_JOEY_REBUILD.md`
  if Layer 1 is salvageable.
- **Kill-or-continue** call with explicit reasoning — don't hedge.
- **Specific numbered actions I should take this week** (not next month).

I'd rather you say "kill this project" than give a polite continue.
The Ultra Review budget is spent; I want to leave with a hard answer.
