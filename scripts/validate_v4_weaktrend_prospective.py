"""V4: Weak-trend prospective identification test.

Tests the load-bearing claim in docs/strategy_delta_vs_peer.md §5:
   "weak-trend no-trade is free alpha because the reference operator's BE WR there is 58%"

That claim requires the regime classifier to label weak-trend days
*prospectively at 10:00 ET*, not retrospectively. If prospective
classification is noise, we would be "filtering losing days after the
fact" — not a real edge.

Procedure:
  1. For each of ~952 trading days, load underlying_price minute series
     from greeks parquet (any strike works — underlying_price is the
     same across strikes for that day).
  2. Retrospective label: weak_trend iff
        (high_full_day - low_full_day) / vwap_full_day  <  0.6 * ATR20
  3. Prospective label at 10:00 ET: weak_trend iff
        (high_0930_1000 - low_0930_1000) / vwap_0930_1000  <  0.6 * ATR20
  4. Report agreement matrix, precision, recall, F1.

Kill: precision < 55% or recall < 40% — §5 free alpha dies; we delete
that optimization point from strategy_delta_vs_peer.md.

Diagnostic: no new backtest; no new signal; just a label agreement test.
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

ATR_WINDOW = 20
WEAK_TREND_THRESHOLD = 0.60       # retrospective threshold, same prospective
OPEN_WINDOW_END_HHMM = "10:00:00"  # prospective classifier cutoff


def load_day_underlying(day_dir: Path) -> pd.Series | None:
    """Extract underlying_price minute series from any greeks parquet.

    underlying_price is redundant across strikes — picking the first
    file with a non-trivial series is fine.
    """
    greeks_dir = day_dir / "greeks"
    if not greeks_dir.exists():
        return None
    for pq in greeks_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(pq, columns=["timestamp", "underlying_price"])
        except Exception:
            continue
        df = df[df["underlying_price"] > 0]
        if df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")["underlying_price"].sort_index()
        # Require at least 60 minutes of data to trust the series
        if len(df) < 60:
            continue
        return df
    return None


def range_stats(series: pd.Series) -> tuple[float, float, float]:
    """Return (high, low, vwap_proxy) from a price series.

    vwap_proxy = time-averaged price (equal weight per minute bar).
    """
    return float(series.max()), float(series.min()), float(series.mean())


def day_realized_range_pct(series: pd.Series) -> float:
    hi, lo, vwap = range_stats(series)
    if vwap <= 0:
        return float("nan")
    return (hi - lo) / vwap


def open_window_range_pct(series: pd.Series) -> float:
    """Range over 09:30 → 10:00 ET using the series index."""
    start = series.index.min().normalize() + pd.Timedelta(hours=9, minutes=30)
    end = series.index.min().normalize() + pd.Timedelta(hours=10, minutes=0)
    window = series[(series.index >= start) & (series.index <= end)]
    if len(window) < 15:
        return float("nan")
    return day_realized_range_pct(window)


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        date = dday.name.replace("date=", "")
        series = load_day_underlying(dday)
        if series is None or len(series) < 60:
            continue
        full_range = day_realized_range_pct(series)
        open_range = open_window_range_pct(series)
        if np.isnan(full_range) or np.isnan(open_range):
            continue
        rows.append({
            "date": date,
            "full_range_pct": full_range,
            "open_range_pct": open_range,
            "minutes": len(series),
        })
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)}", file=sys.stderr)

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days: {len(df)}", file=sys.stderr)

    # ATR20: rolling mean of full_range_pct, shifted by 1 to avoid same-day leak
    # Retrospective normalizer: full-day range vs its own 20d mean
    df["full_atr20"] = df["full_range_pct"].rolling(ATR_WINDOW, min_periods=5).mean().shift(1)
    # Prospective normalizer: open-window range vs its own 20d mean (apples-to-apples)
    df["open_atr20"] = df["open_range_pct"].rolling(ATR_WINDOW, min_periods=5).mean().shift(1)
    df = df.dropna(subset=["full_atr20", "open_atr20"]).reset_index(drop=True)
    print(f"after ATR warmup: {len(df)}", file=sys.stderr)

    df["weak_retro"] = df["full_range_pct"] < WEAK_TREND_THRESHOLD * df["full_atr20"]
    df["weak_prosp"] = df["open_range_pct"] < WEAK_TREND_THRESHOLD * df["open_atr20"]

    tp = int(((df["weak_prosp"]) & (df["weak_retro"])).sum())
    fp = int(((df["weak_prosp"]) & (~df["weak_retro"])).sum())
    fn = int((~(df["weak_prosp"]) & (df["weak_retro"])).sum())
    tn = int((~(df["weak_prosp"]) & (~df["weak_retro"])).sum())
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and not np.isnan(precision) and not np.isnan(recall)
          else float("nan"))
    accuracy = (tp + tn) / total

    base_rate_retro = (tp + fn) / total
    base_rate_prosp = (tp + fp) / total

    kill = (precision < 0.55) or (recall < 0.40)

    result = {
        "days_usable": int(total),
        "base_rate_retrospective_weak": round(base_rate_retro, 3),
        "base_rate_prospective_weak": round(base_rate_prosp, 3),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": round(precision, 3) if not np.isnan(precision) else None,
        "recall": round(recall, 3) if not np.isnan(recall) else None,
        "f1": round(f1, 3) if not np.isnan(f1) else None,
        "accuracy": round(accuracy, 3),
        "kill_triggered": kill,
        "kill_reason": (
            f"precision {precision:.2f} < 0.55" if precision < 0.55
            else f"recall {recall:.2f} < 0.40" if recall < 0.40
            else None
        ),
    }

    print("\n=== V4 weak-trend prospective identification ===")
    print(json.dumps(result, indent=2))

    out_json = OUT_DIR / "v4_weaktrend_prospective_result.json"
    out_csv = OUT_DIR / "v4_weaktrend_prospective_labels.csv"
    with out_json.open("w") as f:
        json.dump(result, f, indent=2)
    df[["date", "full_range_pct", "open_range_pct", "full_atr20", "open_atr20",
        "weak_retro", "weak_prosp"]].to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    if kill:
        print("\nKILL: §5 (weak-trend no-trade) free-alpha claim must be "
              "removed from strategy_delta_vs_peer.md.")
    else:
        print("\nPASS: prospective classifier viable for §5 gate. "
              "Proceed to R3 regime filter implementation (post-check).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
