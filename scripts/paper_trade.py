"""Paper-trade signal logger for strategy v4.

Run daily AFTER market close + OI publication (Theta Data publishes EOD OI
around 7-8 AM ET next morning). Two modes:

  --mode signal: compute today's signal from yesterday's EOD data, log entry
  --mode fill:   fetch yesterday's EOD spot, close out the pending entry from
                 2 days ago (which expired at yesterday's close)

Log file: `paper_trade_log.csv` with columns:
  signal_date, entry_expected_date, exit_date, signal, strike, entry_price,
  exit_spot, exit_intrinsic, pnl, notes

Workflow example (Mon → Tue → Wed):
  Mon 16:00 — market closes, Mon EOD data captured
  Tue 08:00 — Theta publishes Mon's EOD OI
  Tue 09:00 — this script runs with --mode signal
              computes Mon-EOD signal; if triggered, logs entry row
              (entry_expected_date=Tue, exit_date=Wed)
  Wed 08:00 — Tue EOD OI available
  Wed 09:00 — script runs with --mode fill
              finds the Mon-triggered entry, fetches Wed EOD (not yet — we fetch
              what's on disk: Tue EOD), computes realized P&L vs entry strike

Because we hold N→N+1, P&L is realized when Tue EOD data becomes available on
Wed morning. All timestamps in the log are the ACTUAL calendar dates the
positions would have been held.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import logging
import os
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

load_dotenv(".env")
asyncio.set_event_loop(asyncio.new_event_loop())
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.data.enrich import enrich_day, _get_client
from src.data.historical import download_day
from src.gex.greeks import enrich_greeks
from src.gex.calculator import calculate_gex_profile, identify_levels, calculate_vanna_exposure
from src.signal.generator import generate_signal
from src.backtest.engine import BacktestConfig
from src.backtest.fill_simulator import FillSimulator

LOG_PATH = Path("paper_trade_log.csv")
DATA_DIR = Path("data/historical/spy")


def _fetch_and_enrich(d: date) -> bool:
    """Ensure we have enriched parquet for date d."""
    parquet = DATA_DIR / f"{d.strftime('%Y%m%d')}.parquet"
    client = _get_client()

    if not parquet.exists():
        logging.info(f"Downloading {d} OI...")
        if not download_day(client, "SPY", d, DATA_DIR):
            logging.error(f"Download failed for {d}")
            return False

    return enrich_day(client, "SPY", d, parquet)


def _next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n = n + timedelta(days=1)
    return n


def _load_log() -> pd.DataFrame:
    if LOG_PATH.exists():
        return pd.read_csv(LOG_PATH)
    return pd.DataFrame(columns=[
        "signal_date", "entry_expected_date", "exit_date",
        "signal", "strike", "right", "entry_price",
        "exit_spot", "exit_intrinsic", "pnl", "status", "notes",
    ])


def _save_log(df: pd.DataFrame):
    df.to_csv(LOG_PATH, index=False)


def run_signal(signal_date: date):
    """Compute the v4 strategy signal for `signal_date` and log the entry row.

    signal_date is the day whose EOD data drives the decision. The expected
    entry happens the following trading day, exit the day after that.
    """
    if not _fetch_and_enrich(signal_date):
        return

    fp = DATA_DIR / f"{signal_date.strftime('%Y%m%d')}.parquet"
    bar = pd.read_parquet(fp)
    if bar.empty or "spot" not in bar.columns:
        logging.error("No enriched data"); return

    spot = float(bar["spot"].dropna().iloc[0])
    bar = enrich_greeks(bar, spot, as_of=signal_date)
    gex = calculate_gex_profile(bar, spot)
    lv = identify_levels(gex, spot)
    vanna = calculate_vanna_exposure(bar, spot)

    # Same 13:00 anchor as backtest
    signal_dt = datetime.combine(signal_date, datetime.min.time()).replace(hour=13)
    sig = generate_signal(lv, vanna, signal_dt)

    entry_day = _next_trading_day(signal_date)
    exit_day = _next_trading_day(entry_day)

    log = _load_log()

    if sig.direction == "NEUTRAL":
        pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall) if (lv.call_wall and lv.put_wall and lv.call_wall > lv.put_wall) else None
        note = f"NO_SIGNAL regime={lv.regime} pos={pos:.2f}" if pos is not None else f"NO_SIGNAL regime={lv.regime}"
        logging.info(f"{signal_date}: {note}")
        log = pd.concat([log, pd.DataFrame([{
            "signal_date": signal_date, "entry_expected_date": None, "exit_date": None,
            "signal": "NEUTRAL", "strike": None, "right": None, "entry_price": None,
            "exit_spot": None, "exit_intrinsic": None, "pnl": None,
            "status": "SKIPPED", "notes": note,
        }])], ignore_index=True)
        _save_log(log); return

    # Signal triggered — pick the 0.70 delta call at the next-day expiry
    cfg = BacktestConfig()
    target_exp = entry_day.strftime("%Y%m%d")
    right = "C" if sig.direction == "BULLISH" else "P"
    cand = bar[
        (bar["expiry"] == target_exp) & (bar["right"] == right) &
        (bar["bid"] > 0) & (bar["ask"] > 0) & (bar["delta"].abs() > 0.05)
    ]
    if cand.empty:
        logging.warning(f"No {target_exp} {right} contracts in chain")
        return

    cand = cand.assign(dd=(cand["delta"].abs() - cfg.target_delta).abs()).sort_values("dd")
    row = cand.iloc[0]
    strike = float(row["strike"])
    bid, ask = float(row["bid"]), float(row["ask"])

    fill = FillSimulator().simulate_entry(bid, ask, "BUY", signal_dt)
    if not fill.filled:
        logging.warning(f"Simulated fill rejected: {fill.reason}")
        return

    log = pd.concat([log, pd.DataFrame([{
        "signal_date": signal_date,
        "entry_expected_date": entry_day,
        "exit_date": exit_day,
        "signal": sig.direction,
        "strike": strike, "right": row["right"],
        "entry_price": fill.fill_price,
        "exit_spot": None, "exit_intrinsic": None, "pnl": None,
        "status": "PENDING",
        "notes": f"{sig.reason} conf={sig.confidence}",
    }])], ignore_index=True)
    _save_log(log)
    logging.info(
        f"{signal_date} SIGNAL {sig.direction} {strike}{row['right']} "
        f"@ ${fill.fill_price:.2f} (entry target {entry_day}, exit {exit_day})"
    )


def run_fill():
    """Fill in exit P&L for any PENDING rows whose exit_date has passed and
    whose exit-day EOD data is now on disk."""
    log = _load_log()
    pending = log[log["status"] == "PENDING"].copy()
    if pending.empty:
        logging.info("No pending positions to fill")
        return

    updated = False
    for idx, r in pending.iterrows():
        exit_date = pd.to_datetime(r["exit_date"]).date()
        fp = DATA_DIR / f"{exit_date.strftime('%Y%m%d')}.parquet"
        if not fp.exists():
            if not _fetch_and_enrich(exit_date):
                logging.warning(f"Cannot fill {r['signal_date']}: no exit data for {exit_date}")
                continue

        bar = pd.read_parquet(fp)
        spot_vals = bar["spot"].dropna() if "spot" in bar.columns else pd.Series()
        if spot_vals.empty:
            logging.warning(f"No spot in exit data for {exit_date}")
            continue

        exit_spot = float(spot_vals.iloc[0])
        K = float(r["strike"])
        intrinsic = max(exit_spot - K, 0.0) if r["right"] == "C" else max(K - exit_spot, 0.0)
        entry_price = float(r["entry_price"])
        pnl = (intrinsic - entry_price) * 100  # 1 contract

        log.loc[idx, "exit_spot"] = exit_spot
        log.loc[idx, "exit_intrinsic"] = intrinsic
        log.loc[idx, "pnl"] = pnl
        log.loc[idx, "status"] = "CLOSED"
        updated = True
        logging.info(
            f"FILLED {r['signal_date']}→{exit_date}: "
            f"K={K} entry=${entry_price:.2f} exit_intrinsic=${intrinsic:.2f} PnL=${pnl:+.0f}"
        )

    if updated:
        _save_log(log)


def print_summary():
    log = _load_log()
    if log.empty:
        print("Empty log")
        return
    closed = log[log["status"] == "CLOSED"]
    if closed.empty:
        print(f"Log has {len(log)} rows, 0 closed positions")
        return
    pnl_total = closed["pnl"].sum()
    wins = (closed["pnl"] > 0).sum()
    pf_den = -closed[closed["pnl"] < 0]["pnl"].sum()
    pf = closed[closed["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    print(f"Paper trades: N={len(closed)} WR={wins/len(closed)*100:.1f}% "
          f"PnL=${pnl_total:+.0f} PF={pf:.2f}")
    print(log.to_string(index=False))


def _last_trading_day(from_date: date = None) -> date:
    d = (from_date or date.today()) - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d


def run_daily():
    """Cron-friendly: first settle pending positions, then compute last trading
    day's signal. Safe to run every morning regardless of weekends/holidays."""
    logging.info("=== Daily paper trade run ===")
    run_fill()
    run_signal(_last_trading_day())
    print()
    print_summary()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["signal", "fill", "summary", "daily"])
    ap.add_argument("--date", help="Signal date YYYY-MM-DD (defaults to last trading day)")
    args = ap.parse_args()

    if args.mode == "signal":
        d = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else _last_trading_day()
        run_signal(d)
    elif args.mode == "fill":
        run_fill()
    elif args.mode == "summary":
        print_summary()
    elif args.mode == "daily":
        run_daily()
