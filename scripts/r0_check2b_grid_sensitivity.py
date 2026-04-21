"""r0_check2b: entry × window grid scan for wall-as-target.

check2 KILLed with entry=14:30, window=85min. Hypothesis: those
parameters are wrong, not the mechanism. This diagnostic tests
every (entry_time × window) combination from reasonable set.

If ANY (entry, window) shows T_disc or T2 beats T_spot by ≥10% MAE
reduction → R0 is rescuable with that parameter choice.
If NO cell does → R0 mechanism is dead regardless of parameters.

Produces a heatmap-style output over the grid.

Cost: 952 days × 6 entries × 4 windows ≈ 23k day-tests.
Reuses GEX computation per (day × entry_time): 952 × 6 = 5712
distinct GEX snapshots. Estimated runtime 40-60 min.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.gex.calculator import calculate_gex_profile, identify_levels  # noqa: E402

DATA_ROOT = REPO_ROOT / "data" / "historical_0dte"
OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

ENTRY_TIMES = [
    ("10:00", 10 * 60),
    ("11:00", 11 * 60),
    ("12:00", 12 * 60),
    ("13:00", 13 * 60),
    ("14:00", 14 * 60),
    ("14:30", 14 * 60 + 30),
]

WINDOWS = [30, 60, 85, 120]  # minutes


def load_day_greeks_oi(day_dir: Path) -> tuple[dict, pd.DataFrame] | None:
    """Load per-minute underlying_price series (any strike) and static OI."""
    greeks_dir = day_dir / "greeks"
    oi_dir = day_dir / "oi"
    if not greeks_dir.exists() or not oi_dir.exists():
        return None

    # OI
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

    # For each strike×right, load its greeks for full day
    greeks_per_sk: dict = {}
    spot_series = None
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
        strike = float(g.iloc[0]["strike"])
        right = "C" if str(g.iloc[0]["right"]).upper().startswith("C") else "P"
        # keep (mins -> gamma) and (mins -> underlying_price)
        greeks_per_sk[(strike, right)] = g[["mins", "gamma", "underlying_price"]].copy()
        if spot_series is None:
            spot_series = g[["mins", "underlying_price"]].copy()
            spot_series = spot_series[spot_series["underlying_price"] > 0]
            spot_series = spot_series.set_index("mins")["underlying_price"]

    if not greeks_per_sk or spot_series is None:
        return None

    return greeks_per_sk, oi_df, spot_series


def compute_targets_at(greeks_per_sk: dict, oi_df: pd.DataFrame,
                       entry_mins: int, spot: float) -> dict:
    """Compute T_spot, T1, T2, T_disc at given entry time using cached data."""
    rows = []
    for (strike, right), df_gk in greeks_per_sk.items():
        sel = df_gk[df_gk["mins"] == entry_mins]
        if sel.empty:
            continue
        gamma = float(sel.iloc[0]["gamma"])
        if gamma <= 0:
            continue
        rows.append({"strike": strike, "right": right, "gamma": gamma})
    if not rows:
        return {}
    greek_df = pd.DataFrame(rows)
    options_df = greek_df.merge(oi_df, on=["strike", "right"], how="left")
    options_df["open_interest"] = options_df["open_interest"].fillna(0)

    gex_profile = calculate_gex_profile(options_df, spot)
    levels = identify_levels(gex_profile, spot)
    cw = levels.call_wall
    pw = levels.put_wall

    t_spot = spot
    if cw is None and pw is None:
        t1 = t2 = t_disc = None
    else:
        if cw is None:
            t1 = pw
        elif pw is None:
            t1 = cw
        else:
            t1 = cw if abs(cw - spot) < abs(pw - spot) else pw

        if cw is not None and pw is not None:
            gex_c = abs(gex_profile.get(cw, 0.0))
            gex_p = abs(gex_profile.get(pw, 0.0))
            t2 = (gex_c * cw + gex_p * pw) / max(gex_c + gex_p, 1e-12)
        else:
            t2 = None

        cands = []
        if cw is not None:
            cands.append((cw, abs(gex_profile.get(cw, 0.0))))
        if pw is not None:
            cands.append((pw, abs(gex_profile.get(pw, 0.0))))
        if cw is not None and pw is not None:
            midpoint = (cw + pw) / 2
            midwall = min(gex_profile.keys(),
                          key=lambda k: abs(k - midpoint)) if gex_profile else None
            if midwall is not None:
                cands.append((midwall, abs(gex_profile.get(midwall, 0.0))))
        t_disc = max(cands, key=lambda x: x[1])[0] if cands else None

    return {"T_spot": t_spot, "T1": t1, "T2": t2, "T_disc": t_disc}


def main() -> int:
    day_dirs = sorted(DATA_ROOT.glob("date=*"))
    print(f"found {len(day_dirs)} day directories", file=sys.stderr)

    # Results grid: {(entry, window, target) -> list of abs errors}
    grid: dict[tuple[str, int, str], list[float]] = {}
    for etl, _ in ENTRY_TIMES:
        for w in WINDOWS:
            for t in ["T_spot", "T1", "T2", "T_disc"]:
                grid[(etl, w, t)] = []

    for i, dday in enumerate(day_dirs):
        data = load_day_greeks_oi(dday)
        if data is None:
            continue
        greeks_per_sk, oi_df, spot_series = data

        for entry_label, entry_mins in ENTRY_TIMES:
            if entry_mins not in spot_series.index:
                continue
            spot_at_entry = float(spot_series.loc[entry_mins])
            if spot_at_entry <= 0:
                continue

            try:
                targets = compute_targets_at(greeks_per_sk, oi_df,
                                             entry_mins, spot_at_entry)
            except Exception:
                continue
            if not targets:
                continue

            for window in WINDOWS:
                exit_mins = min(entry_mins + window, 15 * 60 + 55)
                # find closest available spot >= exit_mins
                avail = spot_series[spot_series.index >= exit_mins]
                if avail.empty:
                    continue
                spot_at_exit = float(avail.iloc[0])
                if spot_at_exit <= 0:
                    continue
                for tname, tval in targets.items():
                    if tval is None:
                        continue
                    grid[(entry_label, window, tname)].append(
                        abs(tval - spot_at_exit)
                    )

        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(day_dirs)}", file=sys.stderr)

    # Aggregate: compute MAE per cell
    mae_grid: dict = {}
    for (etl, w, tname), errors in grid.items():
        if not errors:
            continue
        key = f"{etl}|{w}min"
        mae_grid.setdefault(key, {})[tname] = {
            "n": int(len(errors)),
            "mae": round(float(np.mean(errors)), 3),
            "median_ae": round(float(np.median(errors)), 3),
        }

    # Improvement table: for each (entry, window), compute pct improvement
    # of each target over T_spot
    improvement = {}
    any_pass_cell: list[tuple[str, str, float]] = []
    any_marginal_cell: list[tuple[str, str, float]] = []

    for key, cells in mae_grid.items():
        spot_mae = cells.get("T_spot", {}).get("mae")
        if spot_mae is None:
            continue
        improvement[key] = {}
        for tname in ["T1", "T2", "T_disc"]:
            t_mae = cells.get(tname, {}).get("mae")
            if t_mae is None:
                continue
            imp = (spot_mae - t_mae) / spot_mae
            improvement[key][tname] = round(imp * 100, 2)
            if imp >= 0.10:
                any_pass_cell.append((key, tname, imp))
            elif imp > 0:
                any_marginal_cell.append((key, tname, imp))

    summary = {
        "n_days_total": len(day_dirs),
        "entry_times_tested": [e[0] for e in ENTRY_TIMES],
        "windows_tested_min": WINDOWS,
        "mae_grid": mae_grid,
        "improvement_pct_over_spot": improvement,
        "any_pass_cell_count": len(any_pass_cell),
        "best_pass_cells": sorted(any_pass_cell, key=lambda x: -x[2])[:5],
        "any_marginal_cell_count": len(any_marginal_cell),
        "best_marginal_cells": sorted(any_marginal_cell, key=lambda x: -x[2])[:5],
    }

    print("\n=== r0_check2b grid sensitivity ===")
    print(json.dumps(summary, indent=2))

    out_json = OUT_DIR / "r0_check2b_grid_sensitivity_result.json"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nsaved: {out_json}")

    print("\n=== VERDICT ===")
    if any_pass_cell:
        b = sorted(any_pass_cell, key=lambda x: -x[2])[0]
        print(f"  R0 RESCUABLE: best cell {b[0]}/{b[1]} improves "
              f"{b[2]*100:.1f}% over T_spot. Re-run check2 with "
              f"these parameters before accepting kill.")
    elif any_marginal_cell:
        b = sorted(any_marginal_cell, key=lambda x: -x[2])[0]
        print(f"  R0 MARGINAL: best cell {b[0]}/{b[1]} improves only "
              f"{b[2]*100:.1f}% over T_spot. Below 10% threshold. "
              f"Stronger evidence for mechanism failure.")
    else:
        print(f"  R0 CONFIRMED KILL: no (entry, window) combination "
              f"allows any wall-based target to beat T_spot. "
              f"Mechanism failure, not measurement artifact.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
