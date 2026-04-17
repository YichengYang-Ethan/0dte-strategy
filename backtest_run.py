"""
Run backtest and generate report.

Usage:
    python backtest_run.py --data-dir data/historical      # Basic backtest
    python backtest_run.py --data-dir data/historical --sweep  # Parameter sweep
"""

from __future__ import annotations

import argparse
import logging

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.report import generate_report, print_report
from src.backtest.param_sweep import param_sweep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="0DTE Backtest")
    parser.add_argument("--data-dir", required=True, help="Path to historical data directory")
    parser.add_argument("--sweep", action="store_true", help="Run parameter sweep")
    parser.add_argument("--output", default="backtest_results.csv", help="Output CSV path")
    args = parser.parse_args()

    if args.sweep:
        results = param_sweep(args.data_dir)
        results.to_csv(args.output, index=False)
        print(f"\nSweep results saved to {args.output}")
    else:
        config = BacktestConfig()
        engine = BacktestEngine(config)
        trades_df = engine.run(args.data_dir)

        if not trades_df.empty:
            report = generate_report(trades_df)
            print_report(report)
            trades_df.to_csv(args.output, index=False)
            print(f"\nTrade log saved to {args.output}")
        else:
            print("No trades generated. Check data and signal parameters.")


if __name__ == "__main__":
    main()
