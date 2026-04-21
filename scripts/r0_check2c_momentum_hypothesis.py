"""r0_check2c: momentum-not-pin confirmatory test.

Pre-registered test per docs/r0_post_mortem_2026_04_21.md reconciliation
ranking #1. Directly tests whether NEG_GAMMA + extreme wall-proximity
produces:
  - BOUNCE TOWARD middle of range (pin hypothesis, R0 original), OR
  - BREAK AWAY from the wall (momentum hypothesis, Barbon-Buraschi 2021)

Method:
  For each of 952 days:
    1. At 14:30 ET, compute GEX profile, walls, pos_in_range, regime
    2. Filter to: NEG_GAMMA AND pos_in_range ∈ [0, 0.15] or [0.85, 1.0]
    3. Record spot_1430 and spot_1555
    4. For pos<0.15 near put_wall:
        pin would predict: spot RISES toward midpoint → return > 0
        momentum predicts: spot FALLS through put_wall → return < 0
    5. Similarly for pos>0.85 near call_wall.
    6. Count directional hits for each hypothesis.

Pre-registered criteria:
  - Pin:      >55% directional hits AWAY from extreme (bounce), signed
  - Momentum: >55% directional hits THROUGH extreme (continuation), signed
  - Neither dominant: no clear mechanism, R0 incoherent (Ranking 3)

Handles the NEG_GAMMA-only cases. POS_GAMMA excluded because
Barbon-Buraschi framework applies to NEG_GAMMA specifically.

Not a full R0 rebuild — just empirically asks "in the regime R0
claimed to predict, what's the actual directional mean?"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.gex.calculator import calculate_gex_profile, identify_levels  # noqa: E402

DATA_ROOT = REPO_ROOT / "data" / "historical_0dte"
OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

ENTRY_MIN = 14 * 60 + 30   # 14:30 (same as check2)
EXIT_MIN = 15 * 60 + 55    # 15:55
EXTREME_LOW = 0.15
EXTREME_HIGH = 0.85


def load_day(day_dir: Path):
    """Return (options_df_1430, spot_1430, spot_1555) or None."""
    greeks_dir = day_dir / "greeks"
    oi_dir = day_dir / "oi"
    if not greeks_dir.exists() or not oi_dir.exists():
        return None

    oi_rows = []
    for pq in oi_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(pq, columns=["strike", "right", "open_interest"])
        except Exception:
            continue
        if not df.empty:
            oi_rows.append(df)
    if not oi_rows:
        return None
    oi_df = pd.concat(oi_rows, ignore_index=True)
    oi_df["right"] = oi_df["right"].astype(str).str[0].str.upper()

    greek_rows = []
    spot_1430 = None
    spot_1555 = None
    for pq in greeks_dir.glob("*.parquet"):
        try:
            g = pd.read_parquet(pq, columns=[
                "timestamp", "strike", "right", "gamma", "underlying_price",
            ])
        except Exception:
            continue
        if g.empty:
            continue
        g["timestamp"] = pd.to_datetime(g["timestamp"])
        g["mins"] = g["timestamp"].dt.hour * 60 + g["timestamp"].dt.minute

        row14 = g[g["mins"] == ENTRY_MIN]
        if not row14.empty:
            r = row14.iloc[0]
            if r["gamma"] > 0:
                greek_rows.append({
                    "strike": float(r["strike"]),
                    "right": "C" if str(r["right"]).upper().startswith("C") else "P",
                    "gamma": float(r["gamma"]),
                })
            if spot_1430 is None and r["underlying_price"] > 0:
                spot_1430 = float(r["underlying_price"])

        row15 = g[g["mins"] == EXIT_MIN]
        if not row15.empty and spot_1555 is None:
            up = float(row15.iloc[0]["underlying_price"])
            if up > 0:
                spot_1555 = up

    if not greek_rows or spot_1430 is None or spot_1555 is None:
        return None

    greek_df = pd.DataFrame(greek_rows)
    options_df = greek_df.merge(oi_df, on=["strike", "right"], how="left")
    options_df["open_interest"] = options_df["open_interest"].fillna(0)
    return options_df, spot_1430, spot_1555


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        data = load_day(dday)
        if data is None:
            continue
        options_df, spot_1430, spot_1555 = data
        if options_df.empty:
            continue
        try:
            gex_profile = calculate_gex_profile(options_df, spot_1430)
            levels = identify_levels(gex_profile, spot_1430)
        except Exception:
            continue

        if levels.regime != "NEGATIVE_GAMMA":
            continue
        cw = levels.call_wall
        pw = levels.put_wall
        if cw is None or pw is None or cw <= pw:
            continue
        rng = cw - pw
        pos = (spot_1430 - pw) / rng
        if np.isnan(pos):
            continue
        ret_pct = (spot_1555 - spot_1430) / spot_1430

        classif = None
        expected_pin_sign = None
        expected_momentum_sign = None
        if pos < EXTREME_LOW:
            classif = "near_put_wall"
            expected_pin_sign = +1     # pin: bounce up toward midpoint
            expected_momentum_sign = -1  # momentum: break down through put_wall
        elif pos > EXTREME_HIGH:
            classif = "near_call_wall"
            expected_pin_sign = -1     # pin: bounce down toward midpoint
            expected_momentum_sign = +1  # momentum: break up through call_wall
        else:
            continue

        actual_sign = 1 if ret_pct > 0 else -1 if ret_pct < 0 else 0
        pin_hit = actual_sign == expected_pin_sign
        momentum_hit = actual_sign == expected_momentum_sign

        rows.append({
            "date": dday.name.replace("date=", ""),
            "regime": levels.regime,
            "pos_in_range": round(pos, 4),
            "classif": classif,
            "spot_1430": spot_1430,
            "spot_1555": spot_1555,
            "ret_pct_85min": round(ret_pct, 5),
            "actual_sign": actual_sign,
            "pin_hit": int(pin_hit),
            "momentum_hit": int(momentum_hit),
        })
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)} "
                  f"(kept {len(rows)})", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days (NEG_GAMMA + extreme pos): {len(df)}", file=sys.stderr)

    # Separate analysis by classif
    def analyze(sub: pd.DataFrame, name: str) -> dict:
        if sub.empty:
            return {"name": name, "n": 0}
        n = len(sub)
        pin_rate = float(sub["pin_hit"].mean())
        mom_rate = float(sub["momentum_hit"].mean())
        mean_ret = float(sub["ret_pct_85min"].mean())
        median_ret = float(sub["ret_pct_85min"].median())

        # Signed "magnitude of directional thesis"
        # For put_wall extremes, bullish pin vs bearish momentum.
        # Take mean return, sign tells us the dominant mechanism.
        if name == "near_put_wall":
            directional = mean_ret
            thesis = ("pin" if directional > 0 else
                      "momentum" if directional < 0 else "none")
        else:  # near_call_wall
            directional = -mean_ret  # flip so positive = pin, negative = momentum
            thesis = ("pin" if directional > 0 else
                      "momentum" if directional < 0 else "none")

        return {
            "name": name,
            "n": int(n),
            "pin_hit_rate": round(pin_rate, 3),
            "momentum_hit_rate": round(mom_rate, 3),
            "mean_ret_pct_85min": round(mean_ret * 100, 3),
            "median_ret_pct_85min": round(median_ret * 100, 3),
            "directional_strength_pct": round(directional * 100, 3),
            "thesis_signed": thesis,
        }

    put_stats = analyze(df[df["classif"] == "near_put_wall"], "near_put_wall")
    call_stats = analyze(df[df["classif"] == "near_call_wall"], "near_call_wall")

    # Overall verdict
    def pick_verdict(put: dict, call: dict) -> str:
        if put["n"] == 0 or call["n"] == 0:
            return "INSUFFICIENT_DATA"
        pin_rates = [put["pin_hit_rate"], call["pin_hit_rate"]]
        mom_rates = [put["momentum_hit_rate"], call["momentum_hit_rate"]]
        if all(p > 0.55 for p in pin_rates):
            return "PIN_SUPPORTED"
        if all(m > 0.55 for m in mom_rates):
            return "MOMENTUM_SUPPORTED"
        if pin_rates[0] > 0.55 or pin_rates[1] > 0.55:
            return "PIN_PARTIAL (one side only)"
        if mom_rates[0] > 0.55 or mom_rates[1] > 0.55:
            return "MOMENTUM_PARTIAL (one side only)"
        return "INCOHERENT (neither dominant)"

    verdict = pick_verdict(put_stats, call_stats)

    summary = {
        "n_days_total": len(day_dirs),
        "n_days_qualifying": int(len(df)),
        "pre_registered_criterion": "hit rate >55% for a thesis to count",
        "near_put_wall": put_stats,
        "near_call_wall": call_stats,
        "verdict": verdict,
    }

    print("\n=== r0_check2c momentum-vs-pin hypothesis ===")
    print(json.dumps(summary, indent=2))

    out_json = OUT_DIR / "r0_check2c_momentum_result.json"
    out_csv = OUT_DIR / "r0_check2c_momentum_days.csv"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    print("\n=== VERDICT ===")
    print(f"  {verdict}")
    if "MOMENTUM" in verdict and "PARTIAL" not in verdict:
        print("  → A1 (momentum-not-pin rebuild) has direct empirical "
              "support. Consider as primary pivot branch.")
    elif "PIN" in verdict and "PARTIAL" not in verdict:
        print("  → This contradicts check2/check2b — should not occur. "
              "Investigate.")
    elif "PARTIAL" in verdict:
        print("  → One side supports a thesis; other side ambiguous. "
              "Mechanism is directionally asymmetric.")
    elif "INCOHERENT" in verdict:
        print("  → Neither pin nor momentum dominates on ≥55% of days. "
              "A1 rebuild would not have empirical support. "
              "Prefer A2 (practitioner-style signal engineering) or A3 (archive).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
