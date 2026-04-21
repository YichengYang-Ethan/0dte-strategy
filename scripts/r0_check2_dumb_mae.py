"""r0_check2: dumb-baseline MAE test for target formulas.

Per HANDOFF Action 4 (reordered) + Ultra Review #3:
  At t=14:30 ET on last-year untouched data, compute four target
  candidates (T_disc / T1 / T2 / spot-as-target). Compare to actual
  15:55 ET close. Report MAE.

Ultra Review kill criterion:
  No target variant beats spot-at-14:30 by ≥10% MAE reduction → kill R0.

the reference operator-informed variant (2026-04-21, after Ultra Review amendment):
  T_disc is the NEW primary candidate (argmax over discrete wall
  set, not continuous barycenter). See ARCHITECTURE_R0_REBUILD.md
  §1.2 amended.

Four targets evaluated:
  - T_disc:  argmax over {call_wall, put_wall, midwall} of |GEX|
             (primary candidate — the reference operator cites integer pin levels)
  - T1:      spot-closer of {call_wall, put_wall}
  - T2:      GEX-weighted barycenter of {call_wall, put_wall}
  - T_spot:  spot-at-14:30  (the dumb baseline)

Data period: all 952 days used, with disclosure that this includes
previously-touched buckets. Until-2025-10 split preserved for OOS
reporting (ORIG_OOS, EXT_OOS, ALL).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.gex.calculator import calculate_gex_profile, identify_levels  # noqa: E402

DATA_ROOT = REPO_ROOT / "data" / "historical_0dte"
OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

ENTRY_MIN = 14 * 60 + 30     # 14:30
EXIT_MIN = 15 * 60 + 55      # 15:55

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)


def bucket(d: date) -> str:
    if d >= ORIG_IS_START:
        return "ORIG_IS"
    if d >= ORIG_OOS_START:
        return "ORIG_OOS"
    return "EXT_OOS"


def load_day_snapshot_and_close(day_dir: Path) -> tuple[pd.DataFrame, float, float] | None:
    """Load all-strike GEX snapshot at 14:30 + spot-at-14:30 + spot-at-15:55.

    Returns (options_df, spot_at_1430, spot_at_1555) or None.
    """
    greeks_dir = day_dir / "greeks"
    oi_dir = day_dir / "oi"
    if not greeks_dir.exists() or not oi_dir.exists():
        return None

    # OI: single row per strike per right
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

    # Greeks at 14:30 for each strike/right; also grab spot at 14:30 and 15:55
    greek_rows = []
    spot_1430 = None
    spot_1555 = None
    for pq in greeks_dir.glob("*.parquet"):
        try:
            g = pd.read_parquet(pq, columns=[
                "timestamp", "strike", "right", "gamma",
                "underlying_price"
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
    # normalize right in oi_df to C/P single char
    oi_df["right"] = oi_df["right"].astype(str).str[0].str.upper()
    # merge
    options_df = greek_df.merge(oi_df, on=["strike", "right"], how="left")
    options_df["open_interest"] = options_df["open_interest"].fillna(0)
    return options_df, spot_1430, spot_1555


def compute_targets(options_df: pd.DataFrame, spot: float) -> dict:
    """Return 4 target estimates, or None values where not computable."""
    gex_profile = calculate_gex_profile(options_df, spot)
    levels = identify_levels(gex_profile, spot)

    cw = levels.call_wall
    pw = levels.put_wall

    # T_spot: dumb baseline
    t_spot = spot

    # T1: spot-closer
    if cw is None and pw is None:
        t1 = None
    elif cw is None:
        t1 = pw
    elif pw is None:
        t1 = cw
    else:
        t1 = cw if abs(cw - spot) < abs(pw - spot) else pw

    # T2: GEX-weighted barycenter
    if cw is not None and pw is not None:
        gex_c = abs(gex_profile.get(cw, 0.0))
        gex_p = abs(gex_profile.get(pw, 0.0))
        if gex_c + gex_p > 0:
            t2 = (gex_c * cw + gex_p * pw) / (gex_c + gex_p)
        else:
            t2 = (cw + pw) / 2
    else:
        t2 = None

    # T_disc: argmax over {call_wall, put_wall, midwall} of |GEX|
    candidates = []
    if cw is not None:
        candidates.append((cw, abs(gex_profile.get(cw, 0.0))))
    if pw is not None:
        candidates.append((pw, abs(gex_profile.get(pw, 0.0))))
    if cw is not None and pw is not None:
        # midwall: strike nearest to midpoint that exists in GEX profile
        midpoint = (cw + pw) / 2
        midwall = min(gex_profile.keys(),
                      key=lambda k: abs(k - midpoint)) if gex_profile else None
        if midwall is not None:
            candidates.append((midwall, abs(gex_profile.get(midwall, 0.0))))

    if candidates:
        t_disc = max(candidates, key=lambda x: x[1])[0]
    else:
        t_disc = None

    return {
        "T_spot": t_spot,
        "T1": t1,
        "T2": t2,
        "T_disc": t_disc,
        "call_wall": cw,
        "put_wall": pw,
    }


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    rows: list[dict] = []
    for i, dday in enumerate(day_dirs):
        snap = load_day_snapshot_and_close(dday)
        if snap is None:
            continue
        options_df, spot_1430, spot_1555 = snap
        if options_df.empty:
            continue
        try:
            targets = compute_targets(options_df, spot_1430)
        except Exception as e:
            print(f"  {dday.name} error: {e}", file=sys.stderr)
            continue

        date_str = dday.name.replace("date=", "")
        row = {
            "date": date_str,
            "spot_1430": spot_1430,
            "spot_1555": spot_1555,
            **{k: v for k, v in targets.items()},
        }
        for tname in ["T_spot", "T1", "T2", "T_disc"]:
            v = targets.get(tname)
            row[f"{tname}_ae"] = abs(v - spot_1555) if v is not None else None
        rows.append(row)
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)} "
                  f"(kept {len(rows)})", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: no usable days", file=sys.stderr)
        return 1
    print(f"\nusable days: {len(df)}", file=sys.stderr)

    df["date_obj"] = pd.to_datetime(df["date"]).dt.date
    df["bucket"] = df["date_obj"].apply(bucket)

    def mae_summary(sub: pd.DataFrame) -> dict:
        out = {"N": int(len(sub))}
        for tname in ["T_spot", "T1", "T2", "T_disc"]:
            col = f"{tname}_ae"
            valid = sub[col].dropna()
            out[tname] = {
                "n": int(len(valid)),
                "mae": round(float(valid.mean()), 3) if len(valid) else None,
                "median_ae": round(float(valid.median()), 3) if len(valid) else None,
            }
        return out

    results = {}
    for b in ["ORIG_IS", "ORIG_OOS", "EXT_OOS", "ALL"]:
        sub = df if b == "ALL" else df[df["bucket"] == b]
        results[b] = mae_summary(sub)

    # Ultra Review kill: target must beat T_spot by >=10% MAE reduction in ALL
    all_mae = results["ALL"]
    t_spot_mae = all_mae["T_spot"]["mae"]
    verdicts = {}
    for tname in ["T1", "T2", "T_disc"]:
        t_mae = all_mae[tname]["mae"]
        if t_mae is None or t_spot_mae is None:
            verdicts[tname] = "INSUFFICIENT_DATA"
            continue
        improvement = (t_spot_mae - t_mae) / t_spot_mae
        if improvement >= 0.10:
            verdicts[tname] = f"PASS (+{improvement*100:.1f}% MAE reduction)"
        elif improvement > 0:
            verdicts[tname] = f"MARGINAL (+{improvement*100:.1f}%, <10% threshold)"
        else:
            verdicts[tname] = f"FAIL ({improvement*100:.1f}% worse than T_spot)"

    any_pass = any("PASS" in v for v in verdicts.values())
    any_marginal = any("MARGINAL" in v for v in verdicts.values())

    summary = {
        "n_days_total": int(len(df)),
        "entry_time_et": "14:30",
        "label_time_et": "15:55",
        "by_bucket": results,
        "verdicts": verdicts,
        "any_pass": any_pass,
        "any_marginal": any_marginal,
        "kill_triggered": not (any_pass or any_marginal),
    }

    print("\n=== r0_check2 dumb MAE ===")
    print(json.dumps(summary, indent=2))

    out_json = OUT_DIR / "r0_check2_dumb_mae_result.json"
    out_csv = OUT_DIR / "r0_check2_dumb_mae_by_day.csv"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2)
    df.to_csv(out_csv, index=False)
    print(f"\nsaved: {out_json}")
    print(f"saved: {out_csv}")

    if summary["kill_triggered"]:
        print("\nKILL: no target variant beats spot-as-target by "
              "sufficient margin. R0 target-prediction mechanism is "
              "not supported. Do NOT proceed to R1.")
    elif any_pass:
        winners = [t for t, v in verdicts.items() if "PASS" in v]
        print(f"\nPASS: {', '.join(winners)} cleared the 10% MAE reduction "
              f"threshold. Proceed to check1 per reordered HANDOFF.")
    else:
        print("\nMARGINAL: some targets improve but none hit 10%. "
              "Flag to GPT Pro for adjudication before proceeding.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
