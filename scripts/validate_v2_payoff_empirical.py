"""V2: Empirical check of the reference operator's payoff claims (-40% / +300%).

Tests whether the reference operator's self-reported payoff geometry holds on unconditional
0.20Δ OTM 0DTE calls across 952 days. This is not a claim that the reference operator's
SIGNAL doesn't beat this baseline — it's a claim that his payoff NUMBERS
(-40% avg loss, +300% avg win) should be reachable on *some* subset of
days if the mechanism exists, and that the unconditional distribution
tells us what's mechanically possible vs what requires edge.

Key question: is "+300% win / -40% loss" even a reachable payoff pair
on 0.20Δ 0DTE calls held 09:45 → 15:55? Or is the reference operator cherry-picking from
memory?

Procedure:
  For each of ~952 days:
    1. Pick a call strike such that |delta| ≈ 0.20 at 09:45 ET
    2. Compute entry fill price (ask @ 09:45 — the reference operator's method)
    3. Walk minute-by-minute from 09:46 to 15:55
    4. Under each stop-rule (none, -40%, -60%, -100%):
         - track running P/L as (current_mid - entry_fill) / entry_fill
         - stop out when running P/L <= stop
         - otherwise exit at 15:55 bid
    5. Record final P/L % and whether stop fired
  Aggregate across days. Report:
    - loss distribution: median, mean, p10, p90, when side=loss
    - win distribution: median, mean, p10, p90, when side=win
    - win rate per stop-rule
    - compare to the reference operator's -40% / +300% claim

Kill criteria: no "kill" — this is diagnostic. But a strong finding
(median win < +80% gross) means the reference operator's +300% is conditional on his
signal and NOT an unconditional baseline — which reshapes what
peer_payoff_model.py represents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "historical_0dte"
OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

TARGET_DELTA = 0.20
ENTRY_HHMM_MIN = 9 * 60 + 45
EXIT_HHMM_MIN = 15 * 60 + 55
STOP_LEVELS = [None, -0.40, -0.60, -1.00]


def strike_from_path(path: Path) -> float:
    return float(path.name.split("strike=")[1].split("_")[0])


def pick_entry_contract(day_dir: Path) -> tuple[Path, Path] | None:
    """Pick a call strike nearest to 0.20 delta at 09:45 ET.

    Returns (greeks_path, quote_path) or None if no viable contract.
    """
    greeks_dir = day_dir / "greeks"
    quote_dir = day_dir / "quote"
    if not greeks_dir.exists() or not quote_dir.exists():
        return None

    best_path: Path | None = None
    best_diff = float("inf")

    for pq in greeks_dir.glob("*_right=C.parquet"):
        try:
            df = pd.read_parquet(pq, columns=["timestamp", "delta", "underlying_price"])
        except Exception:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["mins"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
        row = df[df["mins"] == ENTRY_HHMM_MIN]
        if row.empty or row["delta"].iloc[0] <= 0 or row["underlying_price"].iloc[0] <= 0:
            continue
        d = float(row["delta"].iloc[0])
        diff = abs(d - TARGET_DELTA)
        if diff < best_diff:
            best_diff = diff
            best_path = pq

    if best_path is None:
        return None

    strike = strike_from_path(best_path)
    quote_path = quote_dir / f"strike={strike:.3f}_right=C.parquet"
    if not quote_path.exists():
        return None

    return best_path, quote_path


def simulate_trade(quote_path: Path) -> dict | None:
    """Simulate ONE trade across all stop levels using one minute bars.

    Entry: ask at 09:45
    Mid-path: mid at each minute 09:46 → 15:55
    Exit: bid at 15:55 if no stop hits
    Stop: triggered if mid drops to (entry * (1 + stop)) at any minute
    """
    try:
        df = pd.read_parquet(
            quote_path,
            columns=["timestamp", "bid", "ask"],
        )
    except Exception:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["mins"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    df = df[(df["bid"] > 0) & (df["ask"] > df["bid"])].copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2

    entry_row = df[df["mins"] == ENTRY_HHMM_MIN]
    if entry_row.empty:
        return None
    entry_fill = float(entry_row["ask"].iloc[0])  # the reference operator: pay full spread
    if entry_fill <= 0.01:
        return None

    path = df[(df["mins"] > ENTRY_HHMM_MIN) & (df["mins"] <= EXIT_HHMM_MIN)]
    if path.empty:
        return None

    running_pnl_pct = (path["mid"] - entry_fill) / entry_fill
    exit_row = path[path["mins"] == EXIT_HHMM_MIN]
    exit_price = float(exit_row["bid"].iloc[0]) if not exit_row.empty else 0.01
    terminal_pnl_pct = (exit_price - entry_fill) / entry_fill

    out = {"entry_fill": entry_fill, "exit_price": exit_price,
           "strike": strike_from_path(quote_path)}

    for stop in STOP_LEVELS:
        key = "none" if stop is None else f"stop{int(stop*100)}"
        if stop is None:
            out[f"{key}_pnl_pct"] = float(terminal_pnl_pct)
            out[f"{key}_stopped"] = False
            continue
        hits = running_pnl_pct <= stop
        if hits.any():
            out[f"{key}_pnl_pct"] = float(stop)
            out[f"{key}_stopped"] = True
        else:
            out[f"{key}_pnl_pct"] = float(terminal_pnl_pct)
            out[f"{key}_stopped"] = False
    return out


def summarize(series: pd.Series) -> dict:
    return {
        "n": int(len(series)),
        "median": float(series.median()),
        "mean": float(series.mean()),
        "p10": float(series.quantile(0.10)),
        "p90": float(series.quantile(0.90)),
    }


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        pair = pick_entry_contract(dday)
        if pair is None:
            continue
        trade = simulate_trade(pair[1])
        if trade is None:
            continue
        trade["date"] = dday.name.replace("date=", "")
        rows.append(trade)
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)} "
                  f"(kept {len(rows)})", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days: {len(df)}", file=sys.stderr)

    summary: dict = {
        "n_days": int(len(df)),
        "target_delta": TARGET_DELTA,
        "entry": "ask at 09:45",
        "exit": "bid at 15:55 or stop hit",
        "by_stop_level": {},
    }

    for stop in STOP_LEVELS:
        key = "none" if stop is None else f"stop{int(stop*100)}"
        pnls = df[f"{key}_pnl_pct"]
        stops = df[f"{key}_stopped"] if stop is not None else None
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        wr = float((pnls > 0).mean())
        pf_num = float(wins.sum())
        pf_den = float(-losses.sum())
        pf = pf_num / pf_den if pf_den > 0 else float("inf")

        summary["by_stop_level"][key] = {
            "n": int(len(pnls)),
            "win_rate": round(wr, 3),
            "profit_factor": round(pf, 3) if np.isfinite(pf) else "inf",
            "stopped_rate": round(float(stops.mean()), 3) if stops is not None else None,
            "wins": summarize(wins) if len(wins) else None,
            "losses": summarize(losses) if len(losses) else None,
            "overall": summarize(pnls),
        }

    # the reference operator comparison
    joey_check = {
        "joey_claim": {"loss_cap": -0.40, "typical_win_gross": +3.00},
        "empirical_at_stop40": {
            "median_loss": summary["by_stop_level"]["stop-40"]["losses"]["median"]
                if summary["by_stop_level"]["stop-40"]["losses"] else None,
            "median_win": summary["by_stop_level"]["stop-40"]["wins"]["median"]
                if summary["by_stop_level"]["stop-40"]["wins"] else None,
            "p90_win": summary["by_stop_level"]["stop-40"]["wins"]["p90"]
                if summary["by_stop_level"]["stop-40"]["wins"] else None,
        },
    }
    summary["joey_comparison"] = joey_check

    print("\n=== V2 the reference operator payoff empirical ===")
    print(json.dumps(summary, indent=2))

    out_json = OUT_DIR / "v2_joey_payoff_empirical_result.json"
    out_csv = OUT_DIR / "v2_joey_payoff_empirical_trades.csv"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    # Verdict text
    print("\n=== Verdict ===")
    jc = joey_check["empirical_at_stop40"]
    if jc["median_win"] is not None and jc["median_win"] < 0.80:
        print(f"  the reference operator's +300% typical win is NOT reachable on unconditional "
              f"0.20Δ 0DTE calls. Empirical median win = +{jc['median_win']*100:.1f}%.")
        print(f"  Implication: the reference operator's claim is CONDITIONAL on his signal, "
              f"not unconditional baseline. peer_payoff_model.py's +300% "
              f"should be flagged as signal-conditional.")
    elif jc["median_win"] is not None and jc["median_win"] < 2.50:
        print(f"  the reference operator's +300% is AT THE EDGE of unconditional distribution. "
              f"Empirical median win = +{jc['median_win']*100:.1f}%.")
    else:
        print(f"  Empirical median win = +{jc['median_win']*100:.1f}% — "
              f"the reference operator's +300% is plausible as unconditional baseline.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
