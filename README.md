# Options Strategy Research

Research and implementation of two distinct GEX/Vanna-driven options strategies on SPY/SPX.

## Two Strategies

### 1. 1DTE Swing (archived — `v1-1dte-archive` tag)

EOD → next-EOD swing on SPY 0.70Δ 1DTE calls, signal-gated by dealer-gamma regime + position-in-range.

**Status**: Research complete, archived after 3 rounds of GPT Pro review.

**Key findings**:
- Signal captures conditional drift in SPY spot return (Y2023 PF 1.17, full-sample PF 1.67, t ≈ 2.06)
- Long-call wrapper eats ~41% of the delta-adjusted edge; debit spread eats ~95%
- Baltussen 2021 "hedging demand intraday momentum" thesis partially overturned by Adams 2024 Fed paper — mechanism weakened post-2023 0DTE boom
- Overnight gap risk not mitigated
- **Archived** in favor of intraday 0DTE

**Artifacts**:
- `src/` — full engine, GEX/Vanna calculator, signal generator, fill simulator
- `scripts/` — 4-tier OOS validator, bootstrap PF CIs, instrument sanity check
- `data/historical/spy/` — 825 days of v2-enriched parquets (2023-01-03 → 2026-04-17)
- `PROJECT_STATUS.md` — full rationale for pivot
- `GPT_PRO_*.md` — three rounds of external review

### 2. Intraday 0DTE (active — `feature/0dte-intraday` branch)

Fully automated intraday 0DTE bot on SPX (cash-settled European options), 1–3 hour holds, limit-bid-ask execution via IB API.

**Thesis**: MMs are profit-maximizing agents holding significant option book. When customer flow concentrates at a strike (OI buildup + IV spike + signed aggressor buying), MM delta hedging becomes constrained and their own book pressure creates mechanical incentive to push spot toward the strike that minimizes their book loss. This is the **active MM repositioning** thesis, distinct from passive dealer short-gamma pinning.

**Advantages over 1DTE**:
- Mechanism matches data time scale (intraday signal + intraday data + intraday execution)
- No overnight gap risk (all positions closed same day)
- Convex payoff geometry (70% WR / +100-1500% wins / −40% losses in reference implementation)
- Barbon-Buraschi Gamma Fragility literature still supports the mechanism at 0DTE expiry

**Current phase**: Design + GPT Pro research brief (`GPT_PRO_0DTE_BRIEF.md`)

## Data

- **Theta Data Standard** ($80/mo): historical EOD OI + Greeks + IV for SPY (used for 1DTE research + future intraday OI baseline)
- **Theta Data Options Pro** ($160/mo, planned): intraday 1-min OPRA quotes/trades + streaming Greeks for SPX 0DTE

## Broker

- **IB Gateway** (paper account, port 4002): primary for SPX 0DTE execution via ib_insync
- **moomoo OpenD** (localhost:11111): backup

## Repo Layout

```
src/
├── gex/          # GEX + Vanna calculation (shared across strategies)
├── signal/       # Trade signal generation (1DTE v5 rule)
├── execution/    # IBKR order execution + position management
├── risk/         # Risk limits (daily loss, position size, time windows)
├── data/         # Options data fetching (IBKR, Theta Data)
└── backtest/     # Historical backtesting framework (swing_1dte mode)

scripts/          # validation, bootstrap, instrument sanity checks
data/historical/  # 825 days SPY EOD parquets
```

## Setup

```bash
cp .env.example .env
# Edit .env with Theta credentials + IB connection info

pip install -e ".[dev]"
```

## Risk

This is research code, not investment advice. 0DTE options can lose 100% of premium in minutes.
