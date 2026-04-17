"""Parameter sweep for strategy optimization.

Grid search over TP/SL/trailing/confidence thresholds.
Outputs Sharpe, win rate, and PnL for each combination.
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.report import generate_report

logger = logging.getLogger(__name__)


def param_sweep(
    data_dir: str | Path,
    tp_range: list[float] = None,
    sl_range: list[float] = None,
    trail_activate_range: list[float] = None,
    trail_pct_range: list[float] = None,
    confidence_range: list[float] = None,
    target_delta_range: list[float] = None,
) -> pd.DataFrame:
    """
    Grid search over exit parameters.

    Returns DataFrame with one row per parameter combination,
    columns: all params + sharpe, win_rate, total_pnl, profit_factor, max_dd.
    """
    if tp_range is None:
        tp_range = [0.75, 1.0, 1.5, 2.0]
    if sl_range is None:
        sl_range = [-0.3, -0.5, -0.7]
    if trail_activate_range is None:
        trail_activate_range = [0.3, 0.5, 0.75]
    if trail_pct_range is None:
        trail_pct_range = [0.2, 0.3, 0.4]
    if confidence_range is None:
        confidence_range = [0.55, 0.60, 0.65, 0.70]
    if target_delta_range is None:
        target_delta_range = [0.20, 0.25, 0.30]

    combos = list(itertools.product(
        tp_range, sl_range, trail_activate_range,
        trail_pct_range, confidence_range, target_delta_range,
    ))

    logger.info(f"Running parameter sweep: {len(combos)} combinations")

    results = []
    for i, (tp, sl, trail_act, trail_pct, conf, delta) in enumerate(combos):
        config = BacktestConfig(
            tp_pct=tp,
            sl_pct=sl,
            trail_activate=trail_act,
            trail_pct=trail_pct,
            min_confidence=conf,
            target_delta=delta,
        )

        engine = BacktestEngine(config)
        trades_df = engine.run(data_dir)
        report = generate_report(trades_df)

        results.append({
            "tp_pct": tp,
            "sl_pct": sl,
            "trail_activate": trail_act,
            "trail_pct": trail_pct,
            "min_confidence": conf,
            "target_delta": delta,
            "total_trades": report.total_trades,
            "win_rate": report.win_rate,
            "total_pnl": report.total_pnl,
            "sharpe": report.sharpe,
            "sortino": report.sortino,
            "profit_factor": report.profit_factor,
            "max_drawdown": report.max_drawdown,
            "calmar": report.calmar,
            "avg_slippage": report.avg_slippage_entry + report.avg_slippage_exit,
        })

        if (i + 1) % 10 == 0:
            logger.info(f"Sweep progress: {i+1}/{len(combos)}")

    df = pd.DataFrame(results)
    df = df.sort_values("sharpe", ascending=False)

    # Print top 5
    print("\nTop 5 parameter combinations by Sharpe:")
    print(df.head(5).to_string(index=False))

    return df
