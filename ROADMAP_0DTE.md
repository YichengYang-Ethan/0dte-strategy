# 0DTE Intraday Roadmap — Falsification Spike

## Committed framing

**This is a 6-12 week falsification spike, NOT a production build.**

**Thesis (rewritten)**: Can option-flow concentration, strike proximity, IV-surface shifts, and liquidity regime proxies produce a small, execution-robust intraday SPX edge?

**Primary goal**: decide if the mechanism is strong enough to survive live fills. Expected outcome is iterate-or-kill, not deploy.

## Three commitments (non-negotiable)

1. **Thesis**: dealer-state + flow-concentration proxies, NOT "predict MM puppet master"
2. **Scope**: 6-12 week falsification spike, NOT ship-to-profit
3. **Kill criteria**: pre-committed in writing before any paper trading, enforced without renegotiation

## Milestones (GitHub)

| # | Milestone | Weeks | Exit criterion |
|---|-----------|-------|----------------|
| M1 | Data recorder + QA | 1-2 | Deterministic chain state reconstruction verified |
| M2 | Replay engine + feature lab | 2-4 | Feature pipeline stable across signing variants |
| M3 | Execution simulator calibration | 4-5 | Calibrated fills from quote history, not "mid+35%" |
| M4 | Falsification baselines | 5-6 | Beat 3 dumb baselines on in-sample slice |
| M5 | IB execution state machine | 6-8 | Full state machine handles entry/exit/partial/disconnect |
| M6 | Frozen-parameter paper trade | 8-10 | 100+ paper signals, no tuning during phase |
| M7 | Decision review | 10-12 | Formal iterate-or-kill decision with memo |

## Pre-committed kill criteria

Per GPT Pro Round 4 review (`GPT_PRO_0DTE_VERDICT.md`):

| Trigger | Action |
|---------|--------|
| Week 1-4: cannot reconstruct chain state deterministically | **KILL** — broken tape |
| Week 4-5: flow proxy unstable across signing methods | **STOP** claiming dealer-pressure; rescope |
| 100 paper trades: expectancy ≤ 0, OR winner avg < +45%, OR loser avg worse than −55% | **KILL or pause** |
| 250 paper trades: PF < 1.1, OR matches dumb baseline, OR top-10 trades > 50% P&L | **KILL** |
| 500 signals: 95% CI lower bound ≤ 0 after costs | **KILL** — inference failure |
| Any phase: round-trip cost > 20% premium, OR > 25% modeled edge | **KILL** — execution mismatch |

## Out of scope

- Cartoon "MM puppet master" mechanism
- Live "OI surged at strike X" detector (OI is daily, not intraday — this is a fake signal)
- Max-pain prediction
- Per-stock specialization beyond SPX/SPXW (single-ticker plays like NVDA/MRVL deferred to post-M7)
- Machine learning beyond penalized logistic (per Round 1-2 guidance: "that's how you turn 824 days into fan fiction")
- massive.com subscription (public docs show no aggressor-side field; use Theta + quote rule)

## Reference

- `GPT_PRO_0DTE_BRIEF.md` — research request
- `GPT_PRO_0DTE_VERDICT.md` — committed findings and constraints
- `PROJECT_STATUS.md` — 1DTE archive rationale
- `README.md` — two-strategy repo overview
