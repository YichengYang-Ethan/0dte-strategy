"""V3: Empirical support for the 09:30-09:45 no-trade filter.

reference-operator intel #17: "no signals in first 15 min after open".

If the 09:30-09:45 window is empirically noisier than 09:45-10:00+ (in
terms of price / spread / wall-level instability), the rule is sound and
we should keep our existing 09:45 no_trade_before setting. If the
variance profile is flat, his rule is cargo-culted and we should either
relax it or find a different session boundary.

Procedure:
  For each day, sample one representative near-ATM call strike. Record
  minute-level mid-price and bid-ask spread. Compute:
    - variance of mid returns per minute in three windows:
        A: 09:30-09:45
        B: 09:45-10:00
        C: 10:00-15:00
    - mean spread as % of mid in each window
  Aggregate across days. Report window medians + ratios.

Kill: if A-window variance is NOT materially higher than C-window, our
09:45 filter is uninformed. Not a kill for the whole project — just
demotes reference-operator intel #17 from "validated" to "matches our guess, no
empirical support."

Diagnostic only. No signal code touched.
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


def pick_atm_call(day_dir: Path) -> Path | None:
    """Pick the ATM call for this day using 10:00 underlying_price.

    Falls back to median strike if underlying unavailable.
    """
    greeks_dir = day_dir / "greeks"
    quote_dir = day_dir / "quote"
    if not quote_dir.exists():
        return None

    spot = None
    if greeks_dir.exists():
        for pq in greeks_dir.glob("*_right=C.parquet"):
            try:
                df = pd.read_parquet(pq, columns=["timestamp", "underlying_price"])
            except Exception:
                continue
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            ten = df["timestamp"].dt.normalize().iloc[0] + pd.Timedelta(hours=10)
            near = df.iloc[(df["timestamp"] - ten).abs().argsort()[:1]]
            if not near.empty:
                spot = float(near["underlying_price"].iloc[0])
                break

    calls = list(quote_dir.glob("*_right=C.parquet"))
    if not calls:
        return None

    def strike_of(p: Path) -> float:
        return float(p.name.split("strike=")[1].split("_")[0])

    if spot is None or spot <= 0:
        strikes = sorted(calls, key=strike_of)
        return strikes[len(strikes) // 2]
    return min(calls, key=lambda p: abs(strike_of(p) - spot))


def window_stats(df: pd.DataFrame, start_min: int, end_min: int) -> dict:
    """Stats for window defined by minutes-since-midnight (exchange tz assumed)."""
    ts = df["timestamp"]
    mask = (ts.dt.hour * 60 + ts.dt.minute >= start_min) & \
           (ts.dt.hour * 60 + ts.dt.minute < end_min)
    w = df[mask].copy()
    if len(w) < 5:
        return {}
    w["mid"] = (w["bid"] + w["ask"]) / 2
    w = w[w["mid"] > 0]
    if len(w) < 5:
        return {}
    w["ret"] = w["mid"].pct_change()
    w["spread_pct"] = (w["ask"] - w["bid"]) / w["mid"]
    return {
        "ret_var": float(w["ret"].var()),
        "ret_std": float(w["ret"].std()),
        "spread_pct_mean": float(w["spread_pct"].mean()),
        "spread_pct_median": float(w["spread_pct"].median()),
        "n": int(len(w)),
    }


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        quote_pq = pick_atm_call(dday)
        if quote_pq is None:
            continue
        try:
            df = pd.read_parquet(
                quote_pq,
                columns=["timestamp", "bid", "ask"],
            )
        except Exception:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[(df["bid"] > 0) & (df["ask"] > df["bid"])]
        if len(df) < 60:
            continue

        a = window_stats(df, 9 * 60 + 30, 9 * 60 + 45)   # 09:30-09:45
        b = window_stats(df, 9 * 60 + 45, 10 * 60)       # 09:45-10:00
        c = window_stats(df, 10 * 60, 15 * 60)            # 10:00-15:00
        if not (a and b and c):
            continue

        rows.append({
            "date": dday.name.replace("date=", ""),
            "A_ret_std": a["ret_std"],
            "B_ret_std": b["ret_std"],
            "C_ret_std": c["ret_std"],
            "A_spread_pct": a["spread_pct_median"],
            "B_spread_pct": b["spread_pct_median"],
            "C_spread_pct": c["spread_pct_median"],
        })
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)}", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1

    summary = {
        "days_usable": int(len(df)),
        "ret_std": {
            "A_0930_0945_median": round(df["A_ret_std"].median(), 6),
            "B_0945_1000_median": round(df["B_ret_std"].median(), 6),
            "C_1000_1500_median": round(df["C_ret_std"].median(), 6),
            "A_over_C_ratio": round(df["A_ret_std"].median() / df["C_ret_std"].median(), 2),
            "B_over_C_ratio": round(df["B_ret_std"].median() / df["C_ret_std"].median(), 2),
        },
        "spread_pct": {
            "A_0930_0945_median": round(df["A_spread_pct"].median(), 4),
            "B_0945_1000_median": round(df["B_spread_pct"].median(), 4),
            "C_1000_1500_median": round(df["C_spread_pct"].median(), 4),
            "A_over_C_ratio": round(df["A_spread_pct"].median() / df["C_spread_pct"].median(), 2),
        },
    }

    A_over_C = summary["ret_std"]["A_over_C_ratio"]
    verdict = (
        "SUPPORTED — 09:30-09:45 return vol is materially higher than 10:00-15:00"
        if A_over_C >= 1.5
        else "WEAK_SUPPORT — first 15 min is only modestly noisier"
        if A_over_C >= 1.15
        else "NOT_SUPPORTED — 09:30-09:45 is not materially noisier than the core session"
    )
    summary["verdict"] = verdict

    print("\n=== V3 open filter empirical support ===")
    print(json.dumps(summary, indent=2))

    out_json = OUT_DIR / "v3_open_filter_result.json"
    out_csv = OUT_DIR / "v3_open_filter_by_day.csv"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
