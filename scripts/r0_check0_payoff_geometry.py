"""r0_check0: payoff geometry feasibility (GPT Pro 2026-04-21 recommendation).

Inserted BEFORE the three existing R0 pre-checks (check1/2/3) because
GPT Pro's Q3 verdict identified this as the most load-bearing prior
question: can the reference operator's claimed payoff (+300% gross before -40% stop within
10-60 min hold) even be mechanically reached on our data, unconditionally?

If the target-before-stop hit rate is too sparse or regime-unstable, the
entire R0 direction is unsupported and R1-R5 should not proceed.

Complements V2: V2 measured end-of-day bid exits at 15:55. This script
measures intraday hit-rate of +300% TARGET BEFORE -40% STOP within
the reference operator's stated 10-60 minute holding window. Different question; both
needed.

Procedure:
  For each of ~952 days:
    1. Pick 0.20Δ OTM call at 09:45 (match the reference operator premium universe)
    2. Compute entry fill = ask at 09:45 (the reference operator fill convention)
    3. Walk minute path for 60 minutes (or until 15:55, whichever first)
    4. Record first event:
        TARGET_HIT  if bid >= entry * 4.00 (+300% gross)
        STOP_HIT    if mid <= entry * 0.60 (-40%)
        TIMEOUT     60 minutes elapsed, neither hit
        EOD_HIT     <60 min from 15:55, exit at 15:55 bid

Per-day outcome recorded; aggregate over all 952 days.

Kill criteria (pre-registered, GPT Pro):
  - TARGET_HIT rate < 3% of days → payoff geometry not reachable unconditionally
  - TARGET_HIT rate concentrated on single regime (>80% on squeeze-only)
    → the reference operator's payoff is regime-conditional, not a usable baseline

Diagnostic output includes:
  - Overall hit rate surface
  - Hit rate by prospective regime (using V4 classifier even though
    V4 showed precision 34% — here we use it only as a bucket label,
    not a trading gate)
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
ENTRY_MIN = 9 * 60 + 45   # 09:45
HOLD_MINUTES = 60
EOD_MIN = 15 * 60 + 55
TARGET_MULT = 4.00        # +300% gross
STOP_MULT = 0.60          # -40% gross


def strike_from_path(path: Path) -> float:
    return float(path.name.split("strike=")[1].split("_")[0])


def pick_entry_contract(day_dir: Path) -> tuple[Path, Path] | None:
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
        row = df[df["mins"] == ENTRY_MIN]
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


def simulate_path(quote_path: Path) -> dict | None:
    try:
        df = pd.read_parquet(quote_path, columns=["timestamp", "bid", "ask"])
    except Exception:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["mins"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    df = df[(df["bid"] > 0) & (df["ask"] > df["bid"])].copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2

    entry_row = df[df["mins"] == ENTRY_MIN]
    if entry_row.empty:
        return None
    entry_fill = float(entry_row["ask"].iloc[0])
    if entry_fill <= 0.01:
        return None

    exit_cutoff_min = min(ENTRY_MIN + HOLD_MINUTES, EOD_MIN)
    path = df[(df["mins"] > ENTRY_MIN) & (df["mins"] <= exit_cutoff_min)].copy()
    if path.empty:
        return None

    target_price = entry_fill * TARGET_MULT
    stop_price = entry_fill * STOP_MULT

    outcome = "TIMEOUT"
    exit_price = float(path.iloc[-1]["bid"])
    exit_min = int(path.iloc[-1]["mins"])
    for _, row in path.iterrows():
        if row["bid"] >= target_price:
            outcome = "TARGET_HIT"
            exit_price = float(row["bid"])
            exit_min = int(row["mins"])
            break
        if row["mid"] <= stop_price:
            outcome = "STOP_HIT"
            exit_price = entry_fill * STOP_MULT
            exit_min = int(row["mins"])
            break

    if outcome == "TIMEOUT" and exit_min >= EOD_MIN:
        outcome = "EOD_HIT"

    pnl_pct = (exit_price - entry_fill) / entry_fill
    return {
        "outcome": outcome,
        "pnl_pct": float(pnl_pct),
        "mins_to_exit": int(exit_min - ENTRY_MIN),
        "entry_fill": entry_fill,
        "target_price": target_price,
        "stop_price": stop_price,
    }


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        pair = pick_entry_contract(dday)
        if pair is None:
            continue
        result = simulate_path(pair[1])
        if result is None:
            continue
        result["date"] = dday.name.replace("date=", "")
        rows.append(result)
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)} "
                  f"(kept {len(rows)})", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days: {len(df)}", file=sys.stderr)

    counts = df["outcome"].value_counts().to_dict()
    total = int(len(df))
    rates = {k: round(v / total, 4) for k, v in counts.items()}

    target_hit_rate = rates.get("TARGET_HIT", 0.0)
    stop_hit_rate = rates.get("STOP_HIT", 0.0)

    kill_sparsity = target_hit_rate < 0.03

    # For regime concentration check, we'd join V4's labels. Simple version
    # here: report if TARGET_HIT days cluster in any 3-month window.
    if rates.get("TARGET_HIT", 0):
        hits = df[df["outcome"] == "TARGET_HIT"].copy()
        hits["date"] = pd.to_datetime(hits["date"])
        hits["ym"] = hits["date"].dt.to_period("M")
        month_counts = hits["ym"].value_counts()
        top3 = int(month_counts.head(3).sum())
        concentration = top3 / max(1, int(month_counts.sum()))
    else:
        concentration = 0.0

    kill_regime = concentration > 0.80

    result = {
        "n_days": total,
        "params": {
            "target_delta": TARGET_DELTA,
            "entry_min": ENTRY_MIN,
            "hold_minutes": HOLD_MINUTES,
            "target_mult": TARGET_MULT,
            "stop_mult": STOP_MULT,
            "entry": "ask",
            "exit": "bid at target, stop price at stop, bid at timeout",
        },
        "outcome_rates": rates,
        "target_before_stop_hit_rate": target_hit_rate,
        "stop_before_target_hit_rate": stop_hit_rate,
        "top3_month_concentration": round(concentration, 3),
        "kill_triggered": kill_sparsity or kill_regime,
        "kill_reason": (
            f"target hit rate {target_hit_rate:.3f} < 0.03"
            if kill_sparsity
            else f"top-3-month concentration {concentration:.3f} > 0.80"
            if kill_regime
            else None
        ),
        "mean_pnl_pct": round(float(df["pnl_pct"].mean()), 4),
        "median_pnl_pct": round(float(df["pnl_pct"].median()), 4),
        "mean_mins_to_exit": round(float(df["mins_to_exit"].mean()), 1),
    }

    print("\n=== r0_check0 payoff geometry feasibility ===")
    print(json.dumps(result, indent=2))

    out_json = OUT_DIR / "r0_check0_payoff_geometry_result.json"
    out_csv = OUT_DIR / "r0_check0_payoff_geometry_days.csv"
    with out_json.open("w") as f:
        json.dump(result, f, indent=2)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    if kill_sparsity:
        print(f"\nKILL: target +{int((TARGET_MULT-1)*100)}% before stop "
              f"{int((STOP_MULT-1)*100)}% within {HOLD_MINUTES}min only "
              f"reachable on {target_hit_rate*100:.1f}% of days. "
              f"the reference operator's payoff geometry is not supported unconditionally.")
    elif kill_regime:
        print(f"\nKILL: target hits cluster {concentration*100:.0f}% in 3 "
              f"months. the reference operator's payoff is regime-locked, not generalizable.")
    else:
        print(f"\nPASS: target reachable on {target_hit_rate*100:.1f}% of "
              f"days, distributed across the sample. R0 payoff geometry "
              f"is feasible baseline.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
