# 0DTE Options Strategy

GEX/Vanna-driven intraday trading on SPY/SPX 0DTE options.

## How it works

1. Fetches full options chain every 5 minutes (IBKR or Theta Data)
2. Calculates Gamma Exposure (GEX) profile across all strikes
3. Identifies key levels: call wall (resistance), put wall (support), 0-GEX flip
4. Calculates Vanna exposure for directional confirmation
5. Generates trade signal with confidence score
6. Executes 0DTE option trades via IBKR with risk limits

## Setup

```bash
cp .env.example .env
# Edit .env with your credentials

pip install -e ".[dev]"

# Paper trading
python main.py

# Scan only (no trades)
python main.py --scan-only
```

## Architecture

```
src/
├── gex/          # GEX + Vanna calculation
├── signal/       # Trade signal generation
├── execution/    # IBKR order execution + position management
├── risk/         # Risk limits (daily loss, position size, time windows)
├── data/         # Options data fetching (IBKR, Theta Data)
└── backtest/     # Historical backtesting framework
```

## Risk

This is not investment advice. 0DTE options can lose 100% of premium in minutes.
