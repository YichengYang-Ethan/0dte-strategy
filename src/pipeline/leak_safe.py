"""Leak-safe primitives for 0DTE research pipeline.

Per GPT Pro Baseline 1 post-mortem, all target-construction and normalization
MUST respect strict timestamp cutoffs. This module provides vetted primitives
that fail closed on leakage.

Core contract:
  - A "signal time cutoff" is an ET time-of-day string, default "15:55".
  - close_spot(day_dir): last underlying_price at or before cutoff.
  - compute_day_flow(day_dir): aggregates only trades <= cutoff.
  - rolling_zscore(series, window=60): shift-1 trailing, never includes t itself.

Additionally provides a `future_poison_test` function: randomizes all data
after the cutoff and verifies a computation returns the same result. Any
function that depends only on pre-cutoff data MUST be invariant.
"""
from __future__ import annotations
import logging
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Signal cutoff: 15:55 ET (before the 15:59 last 1-min bar).
# Rationale: SPXW expiring contracts stop trading 15:00 CT (4:00 PM ET); for
# non-expiring same-day-signal decisions we reserve a 4-minute execution buffer
# before the 15:59 close. For strict walk-forward research, using 15:55 means
# ~4 minutes of data are excluded from the signal even when it could have been
# available in principle. Prefer false caution.
DEFAULT_CUTOFF_ET = "15:55"

# Trading-day calendar boundaries (ET)
MARKET_OPEN_ET = "09:30"
MARKET_CLOSE_ET = "16:00"


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------

def parse_ts_col(df: pd.DataFrame, col: str = "timestamp") -> pd.DataFrame:
    """Add '_time_of_day_et' column parsed from ISO timestamp.

    Assumes input timestamps are ET (matches Theta REST convention).
    """
    df = df.copy()
    df["_time_of_day_et"] = df[col].str.slice(11, 16)
    return df


def is_before_cutoff(ts_str_col: pd.Series, cutoff: str = DEFAULT_CUTOFF_ET) -> pd.Series:
    """Vectorized: True if HH:MM <= cutoff.

    Timestamps shaped like '2026-04-17T09:30:00.000' — we compare chars [11:16].
    """
    return ts_str_col.str.slice(11, 16) <= cutoff


# ---------------------------------------------------------------------------
# Close-spot computation (leak-safe)
# ---------------------------------------------------------------------------

def close_spot_leak_safe(day_dir: Path, cutoff: str = DEFAULT_CUTOFF_ET) -> tuple[date, float]:
    """Return (date, last underlying_price at or before cutoff).

    NEVER uses data after cutoff. Fails closed: returns nan if no price found.

    Prior bug: using median(underlying_price) across the whole day included
    last-30-minute bars (post-cutoff), which leaked future info into the
    "signal time" spot estimate.
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()
    files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not files:
        return d, np.nan

    best_ts = ""
    best_price = np.nan
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["timestamp", "underlying_price"])
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            # Strict cutoff filter
            df = df[df["timestamp"].str.slice(11, 16) <= cutoff]
            if df.empty:
                continue
            idx = df["timestamp"].idxmax()
            if df.loc[idx, "timestamp"] > best_ts:
                best_ts = df.loc[idx, "timestamp"]
                best_price = float(df.loc[idx, "underlying_price"])
        except Exception:
            continue

    return d, best_price


# ---------------------------------------------------------------------------
# Signed flow computation (leak-safe)
# ---------------------------------------------------------------------------

def compute_day_flow_leak_safe(
    day_dir: Path, cutoff: str = DEFAULT_CUTOFF_ET
) -> dict | None:
    """Signed flow aggregate for one day, using only trades at or before cutoff.

    Returns dict with:
      date, signed_net_vol, signed_net_premium, n_trades_classified, n_trades_total
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()
    trade_files = sorted((day_dir / "trade").glob("*.parquet"))
    if not trade_files:
        return None

    trades = pd.concat([pd.read_parquet(f) for f in trade_files], ignore_index=True)
    if trades.empty:
        return None

    # LEAK-SAFE CUTOFF: strict <= cutoff
    trades = trades[trades["timestamp"].str.slice(11, 16) <= cutoff].copy()
    if trades.empty:
        return None

    n_total = len(trades)

    # Single-leg electronic only (Dong AEA 2026)
    trades = trades[trades["condition"].isin([0, 18])].copy()
    if trades.empty:
        return None

    # Load quotes (also cutoff-filtered)
    quote_files = sorted((day_dir / "quote").glob("*.parquet"))
    if not quote_files:
        return None
    quotes = pd.concat([pd.read_parquet(f) for f in quote_files], ignore_index=True)
    quotes = quotes[quotes["timestamp"].str.slice(11, 16) <= cutoff].copy()
    quotes = quotes[(quotes["bid"] > 0) & (quotes["ask"] > 0)]
    if quotes.empty:
        return None

    quotes["min_bucket"] = quotes["timestamp"].str[:16]
    quotes["mid"] = (quotes["bid"] + quotes["ask"]) / 2
    quote_mid = (
        quotes.groupby(["strike", "right", "min_bucket"])["mid"].last().reset_index()
    )

    trades["min_bucket"] = trades["timestamp"].str[:16]
    merged = trades.merge(quote_mid, on=["strike", "right", "min_bucket"], how="left")
    merged = merged.dropna(subset=["mid"])

    merged["side"] = 0
    merged.loc[merged["price"] > merged["mid"], "side"] = 1
    merged.loc[merged["price"] < merged["mid"], "side"] = -1
    merged = merged[merged["side"] != 0].copy()

    merged["signed_size"] = merged["side"] * merged["size"]
    merged["signed_premium"] = merged["side"] * merged["size"] * merged["price"]

    calls = merged[merged["right"] == "CALL"]
    puts = merged[merged["right"] == "PUT"]

    signed_net_vol = calls["signed_size"].sum() - puts["signed_size"].sum()
    signed_net_prem = calls["signed_premium"].sum() - puts["signed_premium"].sum()

    return {
        "date": d,
        "cutoff": cutoff,
        "signed_net_vol": int(signed_net_vol),
        "signed_net_premium": float(signed_net_prem),
        "n_trades_classified": len(merged),
        "n_trades_total": n_total,
    }


# ---------------------------------------------------------------------------
# Rolling z-score (leak-safe)
# ---------------------------------------------------------------------------

def rolling_zscore_shifted(
    series: pd.Series, window: int = 60, min_periods: int | None = None
) -> pd.Series:
    """Trailing rolling z-score shifted by 1 (strict walk-forward).

    z_t = (x_t - mean(x_{t-window}..x_{t-1})) / std(x_{t-window}..x_{t-1})

    Never includes x_t in its own normalizer.
    """
    if min_periods is None:
        min_periods = max(window // 2, 30)
    roll_mean = series.rolling(window, min_periods=min_periods).mean().shift(1)
    roll_std = series.rolling(window, min_periods=min_periods).std().shift(1)
    return (series - roll_mean) / roll_std


# ---------------------------------------------------------------------------
# Intraday spot series + realized variance (leak-safe)
# ---------------------------------------------------------------------------

def intraday_spot_series_leak_safe(
    day_dir: Path, start: str = "09:30", end: str = "15:55"
) -> pd.DataFrame:
    """Return 1-min spot series (timestamp, underlying_price) within [start, end].

    Sources underlying_price from ALL contracts' greeks parquets, takes median
    per minute to denoise (many contracts observe the same underlying).
    Clips to cutoff [start, end] strictly.
    """
    files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=["min_bucket", "spot"])

    rows = []
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["timestamp", "underlying_price"])
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            df["min_bucket"] = df["timestamp"].str.slice(0, 16)
            df["tod"] = df["timestamp"].str.slice(11, 16)
            df = df[(df["tod"] >= start) & (df["tod"] <= end)]
            if df.empty:
                continue
            rows.append(df[["min_bucket", "underlying_price"]])
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=["min_bucket", "spot"])

    big = pd.concat(rows, ignore_index=True)
    # Median per minute across contracts (denoise)
    grouped = big.groupby("min_bucket")["underlying_price"].median().reset_index()
    grouped.columns = ["min_bucket", "spot"]
    grouped = grouped.sort_values("min_bucket").reset_index(drop=True)
    return grouped


def realized_variance_leak_safe(
    day_dir: Path, t: str = "15:00", end: str = "15:55"
) -> dict:
    """Sum of squared 1-min log returns from decision time t to end.

    Also returns spot at t and at end for signed/abs return computation.
    """
    series = intraday_spot_series_leak_safe(day_dir, start=t, end=end)
    if len(series) < 2:
        return {"realized_var": np.nan, "spot_t": np.nan, "spot_end": np.nan, "n_bars": 0}

    log_ret = np.log(series["spot"]).diff().dropna()
    realized_var = float((log_ret ** 2).sum())

    return {
        "realized_var": realized_var,
        "spot_t": float(series["spot"].iloc[0]),
        "spot_end": float(series["spot"].iloc[-1]),
        "n_bars": len(series),
    }


def intraday_labels_leak_safe(day_dir: Path, decision_time: str = "15:00") -> dict | None:
    """Compute the 3 intraday labels prescribed by the MVP plan.

    Labels are all from decision_time t → 15:55 ET:
      - signed_ret_pct: (spot_end − spot_t) / spot_t × 100
      - abs_ret_pct: |signed_ret_pct|
      - realized_var: sum of squared 1-min log returns in [t, 15:55]
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()
    rv = realized_variance_leak_safe(day_dir, t=decision_time, end="15:55")
    if np.isnan(rv["spot_t"]) or np.isnan(rv["spot_end"]) or rv["spot_t"] <= 0:
        return None

    signed = (rv["spot_end"] - rv["spot_t"]) / rv["spot_t"] * 100

    return {
        "date": d,
        "decision_time": decision_time,
        "spot_t": rv["spot_t"],
        "spot_end": rv["spot_end"],
        "n_bars": rv["n_bars"],
        "signed_ret_pct": signed,
        "abs_ret_pct": abs(signed),
        "realized_var": rv["realized_var"],
    }


# ---------------------------------------------------------------------------
# Future-poison regression test
# ---------------------------------------------------------------------------

def future_poison_test(
    day_dir: Path,
    computation: Callable[[Path, str], dict | None],
    cutoff: str = DEFAULT_CUTOFF_ET,
    seed: int = 42,
) -> tuple[bool, dict, dict]:
    """Poison all post-cutoff data, rerun computation, verify result unchanged.

    Returns (passed, result_original, result_poisoned).

    If computation depends ONLY on pre-cutoff data, results must be identical.
    Any difference = leak.
    """
    import tempfile
    import shutil

    # Original result
    result_original = computation(day_dir, cutoff)
    if result_original is None:
        return True, {}, {}  # nothing to check

    # Copy day_dir to temp, poison post-cutoff rows
    with tempfile.TemporaryDirectory() as tmp:
        tmp_day = Path(tmp) / day_dir.name
        shutil.copytree(day_dir, tmp_day)

        rng = np.random.default_rng(seed)

        for ds in ("quote", "trade", "greeks"):
            sub = tmp_day / ds
            if not sub.exists():
                continue
            for f in sub.glob("*.parquet"):
                df = pd.read_parquet(f)
                if df.empty or "timestamp" not in df.columns:
                    continue
                post_mask = df["timestamp"].str.slice(11, 16) > cutoff
                if not post_mask.any():
                    continue
                # Scramble numeric columns in post-cutoff rows
                numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                for c in numeric_cols:
                    df.loc[post_mask, c] = rng.uniform(-1e9, 1e9, size=post_mask.sum())
                df.to_parquet(f, compression="zstd", index=False)

        # Re-run computation on poisoned data
        result_poisoned = computation(tmp_day, cutoff)

    # Compare — should be identical (modulo dict ordering)
    if result_poisoned is None:
        return False, result_original, {}

    passed = True
    diffs = {}
    for k, v_orig in result_original.items():
        v_pois = result_poisoned.get(k)
        if isinstance(v_orig, (int, float, np.integer, np.floating)):
            if not np.isclose(v_orig, v_pois, equal_nan=True):
                passed = False
                diffs[k] = (v_orig, v_pois)
        elif v_orig != v_pois:
            passed = False
            diffs[k] = (v_orig, v_pois)

    return passed, result_original, result_poisoned


# ---------------------------------------------------------------------------
# Self-test on import (optional, run via __main__)
# ---------------------------------------------------------------------------

def _run_self_tests(sample_date: str = "2024-06-03"):
    """Run the core tests on one real day. Called from CLI."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
    day_dir = DATA_DIR / f"date={sample_date}"

    print(f"=== Testing leak-safe primitives on {sample_date} ===\n")

    # Test 1: close_spot respects cutoff
    d, spot_1555 = close_spot_leak_safe(day_dir, cutoff="15:55")
    _, spot_1400 = close_spot_leak_safe(day_dir, cutoff="14:00")
    print(f"Test 1: close spot at cutoff 15:55 → {spot_1555:.2f}")
    print(f"         close spot at cutoff 14:00 → {spot_1400:.2f}")
    assert not np.isnan(spot_1555), "cutoff 15:55 should yield spot"
    assert not np.isnan(spot_1400), "cutoff 14:00 should yield spot"
    # 14:00 spot ≠ 15:55 spot (SPX moves intraday)
    assert abs(spot_1555 - spot_1400) > 0.01, "cutoff should change result"
    print("  ✓ close_spot respects cutoff\n")

    # Test 2: rolling z-score is shift-1
    series = pd.Series(range(100, 200))  # 100 days of increasing values
    z = rolling_zscore_shifted(series, window=30)
    # Day 30's z-score should be based on days 0-29 (trailing window shifted by 1)
    assert z.isna()[:30].all(), "first 30 values must be NaN (not enough history)"
    assert z.notna()[30:].all(), "after warmup all values should be defined"
    print("Test 2: rolling z-score shift-1 ✓\n")

    # Test 3: flow computation
    flow = compute_day_flow_leak_safe(day_dir, cutoff="15:55")
    flow_1400 = compute_day_flow_leak_safe(day_dir, cutoff="14:00")
    print(f"Test 3: flow @ 15:55: signed_net_vol={flow['signed_net_vol']:,} ({flow['n_trades_classified']} trades)")
    print(f"        flow @ 14:00: signed_net_vol={flow_1400['signed_net_vol']:,} ({flow_1400['n_trades_classified']} trades)")
    assert flow["n_trades_classified"] > flow_1400["n_trades_classified"], "later cutoff should include more trades"
    print("  ✓ flow respects cutoff (more trades = later cutoff)\n")

    # Test 4: future-poison test (the big one)
    print("Test 4: Future-poison test on compute_day_flow_leak_safe...")
    passed, orig, pois = future_poison_test(day_dir, compute_day_flow_leak_safe, cutoff="15:55")
    if passed:
        print("  ✓ PASSED — computation is invariant to post-cutoff data")
        print(f"    original signed_net_vol: {orig['signed_net_vol']}")
        print(f"    poisoned signed_net_vol: {pois['signed_net_vol']}")
    else:
        print("  ✗ FAILED — computation uses post-cutoff data (LEAK!)")
        print(f"    original: {orig}")
        print(f"    poisoned: {pois}")

    # Test 5: close_spot poison test
    print("\nTest 5: Future-poison test on close_spot_leak_safe...")
    # Adapt for tuple-returning function
    def close_spot_dict(dd, c):
        d, s = close_spot_leak_safe(dd, c)
        return {"date": d, "close_spot": s} if not np.isnan(s) else None
    passed2, orig2, pois2 = future_poison_test(day_dir, close_spot_dict, cutoff="15:55")
    if passed2:
        print("  ✓ PASSED — close_spot is invariant to post-cutoff data")
        print(f"    original close_spot: {orig2['close_spot']:.2f}")
        print(f"    poisoned close_spot: {pois2['close_spot']:.2f}")
    else:
        print("  ✗ FAILED — close_spot uses post-cutoff data (LEAK!)")
        print(f"    original: {orig2}, poisoned: {pois2}")

    print("\n=== DONE ===")
    return passed and passed2


if __name__ == "__main__":
    ok = _run_self_tests()
    import sys
    sys.exit(0 if ok else 1)
