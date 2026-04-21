"""r0_check3: dealer-sign stability across VIX regimes.

The load-bearing check per GPT Pro Q3 and HANDOFF §9: is customer
net flow sign (and thus dealer sign) stable enough across volatility
regimes that a GEX-based target formula is meaningful?

If customer net call buying flips sign across low-vol vs high-vol
days (e.g. low-vol = net buy calls, high-vol = net sell calls), then
"dealers are short gamma" is regime-dependent and R0's whole
mechanism story breaks — every feature and target downstream flips
sign with it.

Procedure:
  1. For each of ~952 days, use compute_day_flow_leak_safe-style
     logic to get signed volume separately for calls and puts with
     cutoff 15:55.
  2. Classify each day by VIX proxy = ATM SPX IV at 10:00 ET from
     greeks parquet (leak-safe: we don't look at post-10:00 data
     to classify regime).
  3. Bucket by VIX proxy tercile: low / mid / high.
  4. Aggregate signed_call_vol and signed_put_vol within each
     tercile.

Kill thresholds (per our T1.1 decision, 2026-04-21):
  - HARD KILL:  sign of signed_call_vol or signed_put_vol flips
                across terciles (e.g. low=+ high=-)
  - SOFT KILL:  |magnitude ratio| across terciles > 3x
                (same sign but unstable scale)
  - PASS:       sign stable AND magnitude ratio < 2x

Outputs:
  logs/r0_check3_dealer_sign_result.json
  logs/r0_check3_dealer_sign_by_day.csv
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "historical_0dte"
OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

CUTOFF = "15:55"


def atm_iv_at_1000(day_dir: Path) -> float | None:
    """VIX proxy: median ATM SPX IV at 10:00 ET from greeks parquet.

    Uses 10:00 only (leak-safe for regime classification of that day).
    """
    greeks_dir = day_dir / "greeks"
    if not greeks_dir.exists():
        return None

    # Collect IV at 10:00 from strikes near spot; pick ATM-ish
    rows = []
    for pq in greeks_dir.glob("*_right=C.parquet"):
        try:
            df = pd.read_parquet(
                pq,
                columns=["timestamp", "delta", "underlying_price", "implied_vol"],
            )
        except Exception:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["mins"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
        row = df[df["mins"] == 10 * 60]  # 10:00
        if row.empty:
            continue
        r = row.iloc[0]
        if r["delta"] <= 0 or r["underlying_price"] <= 0 or r["implied_vol"] <= 0:
            continue
        rows.append({
            "delta": float(r["delta"]),
            "iv": float(r["implied_vol"]),
        })

    if not rows:
        return None
    # ATM call delta ≈ 0.5. Pick IVs of options with |delta - 0.5| < 0.15.
    # Median as the regime proxy.
    atm = [r["iv"] for r in rows if abs(r["delta"] - 0.5) < 0.15]
    if not atm:
        # fallback: overall median
        return float(np.median([r["iv"] for r in rows]))
    return float(np.median(atm))


def day_signed_flow(day_dir: Path) -> dict | None:
    """Returns dict with signed_call_vol, signed_put_vol (separate).

    Lee-Ready signing on trade price vs minute-mid quote.
    Filters to single-leg electronic (condition ∈ {0, 18}) per Dong AEA 2026.
    """
    trade_files = sorted((day_dir / "trade").glob("*.parquet"))
    quote_files = sorted((day_dir / "quote").glob("*.parquet"))
    if not trade_files or not quote_files:
        return None

    trades = pd.concat([pd.read_parquet(f) for f in trade_files], ignore_index=True)
    if trades.empty:
        return None

    trades = trades[trades["timestamp"].str.slice(11, 16) <= CUTOFF].copy()
    trades = trades[trades["condition"].isin([0, 18])]
    if trades.empty:
        return None

    quotes = pd.concat([pd.read_parquet(f) for f in quote_files], ignore_index=True)
    quotes = quotes[quotes["timestamp"].str.slice(11, 16) <= CUTOFF]
    quotes = quotes[(quotes["bid"] > 0) & (quotes["ask"] > 0)]
    if quotes.empty:
        return None

    quotes["min_bucket"] = quotes["timestamp"].str[:16]
    quotes["mid"] = (quotes["bid"] + quotes["ask"]) / 2
    quote_mid = (quotes.groupby(["strike", "right", "min_bucket"])["mid"]
                 .last().reset_index())

    trades["min_bucket"] = trades["timestamp"].str[:16]
    merged = trades.merge(quote_mid, on=["strike", "right", "min_bucket"], how="left")
    merged = merged.dropna(subset=["mid"])

    merged["side"] = 0
    merged.loc[merged["price"] > merged["mid"], "side"] = 1
    merged.loc[merged["price"] < merged["mid"], "side"] = -1
    merged = merged[merged["side"] != 0].copy()
    if merged.empty:
        return None

    merged["signed_size"] = merged["side"] * merged["size"]

    calls = merged[merged["right"] == "CALL"]
    puts = merged[merged["right"] == "PUT"]

    return {
        "signed_call_vol": int(calls["signed_size"].sum()),
        "signed_put_vol": int(puts["signed_size"].sum()),
        "n_call_trades": int(len(calls)),
        "n_put_trades": int(len(puts)),
    }


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        iv = atm_iv_at_1000(dday)
        flow = day_signed_flow(dday)
        if iv is None or flow is None:
            continue
        date_str = dday.name.replace("date=", "")
        rows.append({
            "date": date_str,
            "vix_proxy_iv": iv,
            "signed_call_vol": flow["signed_call_vol"],
            "signed_put_vol": flow["signed_put_vol"],
            "n_call_trades": flow["n_call_trades"],
            "n_put_trades": flow["n_put_trades"],
        })
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)} "
                  f"(kept {len(rows)})", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days: {len(df)}", file=sys.stderr)

    # Tercile classification
    t_low, t_high = df["vix_proxy_iv"].quantile([0.333, 0.667]).tolist()
    def classify(iv: float) -> str:
        if iv <= t_low:
            return "low"
        if iv <= t_high:
            return "mid"
        return "high"
    df["vix_tercile"] = df["vix_proxy_iv"].apply(classify)

    # Per-tercile signed-flow means
    agg = df.groupby("vix_tercile").agg(
        n_days=("date", "count"),
        signed_call_vol_mean=("signed_call_vol", "mean"),
        signed_put_vol_mean=("signed_put_vol", "mean"),
        iv_median=("vix_proxy_iv", "median"),
    ).round(2)

    call_means = agg["signed_call_vol_mean"].to_dict()
    put_means = agg["signed_put_vol_mean"].to_dict()

    def sign_test(means: dict) -> dict:
        signs = {k: (1 if v > 0 else -1 if v < 0 else 0) for k, v in means.items()}
        all_signs = set(signs.values())
        sign_stable = all_signs.issubset({1, 0}) or all_signs.issubset({-1, 0})
        abs_values = [abs(v) for v in means.values() if v != 0]
        mag_ratio = max(abs_values) / min(abs_values) if len(abs_values) >= 2 and min(abs_values) > 0 else float("inf")
        return {"signs": signs, "stable": sign_stable,
                "mag_ratio": round(mag_ratio, 2)}

    call_test = sign_test(call_means)
    put_test = sign_test(put_means)

    def verdict(t: dict) -> str:
        if not t["stable"]:
            return "HARD_KILL (sign flips across terciles)"
        if t["mag_ratio"] > 3.0:
            return f"SOFT_KILL (magnitude ratio {t['mag_ratio']}x > 3x)"
        if t["mag_ratio"] > 2.0:
            return f"MARGINAL (magnitude ratio {t['mag_ratio']}x > 2x but <3x)"
        return f"PASS (stable, magnitude ratio {t['mag_ratio']}x < 2x)"

    call_verdict = verdict(call_test)
    put_verdict = verdict(put_test)

    # Overall verdict: worst of the two
    overall_kill = "HARD_KILL" in call_verdict or "HARD_KILL" in put_verdict \
                   or "SOFT_KILL" in call_verdict or "SOFT_KILL" in put_verdict
    overall = "HARD_KILL" if "HARD_KILL" in (call_verdict + put_verdict) \
              else "SOFT_KILL" if "SOFT_KILL" in (call_verdict + put_verdict) \
              else "MARGINAL" if "MARGINAL" in (call_verdict + put_verdict) \
              else "PASS"

    result = {
        "n_days": int(len(df)),
        "vix_tercile_cutoffs": {
            "low_high_bound": round(t_low, 4),
            "mid_high_bound": round(t_high, 4),
        },
        "per_tercile": agg.to_dict("index"),
        "call_flow_test": {**call_test, "verdict": call_verdict},
        "put_flow_test": {**put_test, "verdict": put_verdict},
        "overall_verdict": overall,
        "kill_triggered": overall_kill,
    }

    print("\n=== r0_check3 dealer-sign stability ===")
    print(json.dumps(result, indent=2, default=str))

    out_json = OUT_DIR / "r0_check3_dealer_sign_result.json"
    out_csv = OUT_DIR / "r0_check3_dealer_sign_by_day.csv"
    with out_json.open("w") as f:
        json.dump(result, f, indent=2, default=str)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    if overall_kill:
        print(f"\nKILL: {overall}. Dealer sign is not regime-stable. "
              f"R0 GEX thesis does not hold uniformly. Investigate "
              f"regime-switched formulation or stop R0.")
    elif overall == "MARGINAL":
        print(f"\nMARGINAL: proceed to check2 with cautious interpretation. "
              f"Magnitude instability means dealer exposure size varies "
              f"materially across regimes; target formula must not assume "
              f"stationary dealer sensitivity.")
    else:
        print(f"\nPASS: dealer sign is regime-stable. R0 target formula "
              f"can assume consistent dealer positioning across VIX regimes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
