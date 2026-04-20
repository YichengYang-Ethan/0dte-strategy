"""Intraday feature extraction — leak-safe.

Per GPT Pro 5-day MVP Day 2 prescription. 4 feature families, all as-of
decision_time t (15:00 primary, 14:30 robustness).

Features:
  F1: Trailing signed flow (15m + 30m windows), delta/gamma-weighted
  F2: Cross-strike concentration (HHI, top-1 share, top-3 share)
  F3: Slow state near spot (OI × gamma at ATM ±1%)
  F4: Interaction: state × concentration × flow_direction

All from data in [t - 30min, t]. STRICTLY no post-t data used.
"""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _mins_from_hhmm(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _hhmm_from_mins(m: int) -> str:
    return f"{m//60:02d}:{m%60:02d}"


def load_day_enriched_window(
    day_dir: Path, t_hhmm: str = "15:00", window_min: int = 30
) -> pd.DataFrame:
    """Load all single-leg-electronic trades in [t-window, t] joined to
    quote-mid (for aggressor signing) and greeks (delta/gamma weights).

    Returns dataframe with columns:
      timestamp, strike, right, price, size, delta, gamma, mid, side, signed_size
    """
    t_min = _mins_from_hhmm(t_hhmm)
    start_hhmm = _hhmm_from_mins(max(0, t_min - window_min))
    end_hhmm = t_hhmm

    # --- Trades ---
    trade_files = sorted((day_dir / "trade").glob("*.parquet"))
    if not trade_files:
        return pd.DataFrame()
    trades = pd.concat([pd.read_parquet(f) for f in trade_files], ignore_index=True)
    if trades.empty:
        return pd.DataFrame()

    trades["tod"] = trades["timestamp"].str.slice(11, 16)
    trades = trades[(trades["tod"] >= start_hhmm) & (trades["tod"] <= end_hhmm)]
    trades = trades[trades["condition"].isin([0, 18])].copy()
    if trades.empty:
        return pd.DataFrame()
    trades["min_bucket"] = trades["timestamp"].str.slice(0, 16)

    # --- Quotes ---
    quote_files = sorted((day_dir / "quote").glob("*.parquet"))
    if not quote_files:
        return pd.DataFrame()
    quotes = pd.concat([pd.read_parquet(f) for f in quote_files], ignore_index=True)
    quotes["tod"] = quotes["timestamp"].str.slice(11, 16)
    quotes = quotes[(quotes["tod"] >= start_hhmm) & (quotes["tod"] <= end_hhmm)]
    quotes = quotes[(quotes["bid"] > 0) & (quotes["ask"] > 0)]
    if quotes.empty:
        return pd.DataFrame()
    quotes["min_bucket"] = quotes["timestamp"].str.slice(0, 16)
    quotes["mid"] = (quotes["bid"] + quotes["ask"]) / 2
    quote_mid = quotes.groupby(["strike", "right", "min_bucket"])["mid"].last().reset_index()

    # --- Greeks (delta/gamma) ---
    greek_files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not greek_files:
        return pd.DataFrame()
    greeks = pd.concat([pd.read_parquet(f, columns=["timestamp","strike","right","delta","gamma","underlying_price"]) for f in greek_files], ignore_index=True)
    greeks["tod"] = greeks["timestamp"].str.slice(11, 16)
    greeks = greeks[(greeks["tod"] >= start_hhmm) & (greeks["tod"] <= end_hhmm)]
    if greeks.empty:
        return pd.DataFrame()
    greeks["min_bucket"] = greeks["timestamp"].str.slice(0, 16)
    # Per (strike, right, minute) take latest (keep delta/gamma stable within minute)
    greeks_min = greeks.groupby(["strike", "right", "min_bucket"]).last().reset_index()

    # --- Join ---
    merged = trades.merge(
        quote_mid, on=["strike", "right", "min_bucket"], how="left"
    ).merge(
        greeks_min[["strike", "right", "min_bucket", "delta", "gamma", "underlying_price"]],
        on=["strike", "right", "min_bucket"], how="left"
    )
    merged = merged.dropna(subset=["mid", "delta", "gamma"])
    if merged.empty:
        return pd.DataFrame()

    merged["side"] = 0
    merged.loc[merged["price"] > merged["mid"], "side"] = 1
    merged.loc[merged["price"] < merged["mid"], "side"] = -1
    merged = merged[merged["side"] != 0].copy()
    merged["signed_size"] = merged["side"] * merged["size"]

    return merged


def compute_feature1_flow(merged: pd.DataFrame) -> dict:
    """Delta- and gamma-weighted signed flow. Split by call/put."""
    if merged.empty:
        return {}
    calls = merged[merged["right"] == "CALL"]
    puts = merged[merged["right"] == "PUT"]

    def w_flow(df, weight_col):
        return (df["signed_size"] * df[weight_col].abs()).sum()

    out = {
        "flow_delta_call": float(w_flow(calls, "delta")),
        "flow_delta_put": float(w_flow(puts, "delta")),
        "flow_gamma_call": float(w_flow(calls, "gamma")),
        "flow_gamma_put": float(w_flow(puts, "gamma")),
    }
    # Net bullish pressure:
    #   call BUY (+) bullish, call SELL (-) bearish
    #   put BUY (+) bearish, put SELL (-) bullish
    #   So net = flow_delta_call - flow_delta_put (as signed aggregator)
    out["flow_delta_net"] = out["flow_delta_call"] - out["flow_delta_put"]
    out["flow_gamma_net"] = out["flow_gamma_call"] - out["flow_gamma_put"]
    out["n_trades"] = int(len(merged))
    return out


def compute_feature2_concentration(merged: pd.DataFrame) -> dict:
    """HHI, top-1, top-3 share across strikes (using abs signed flow)."""
    if merged.empty:
        return {"hhi": np.nan, "top1_share": np.nan, "top3_share": np.nan}
    # Aggregate abs signed flow by strike (across call/put)
    per_strike = merged.groupby("strike")["signed_size"].apply(lambda x: x.abs().sum())
    total = per_strike.sum()
    if total == 0:
        return {"hhi": np.nan, "top1_share": np.nan, "top3_share": np.nan}
    shares = per_strike / total
    hhi = float((shares ** 2).sum())
    top1 = float(shares.max())
    top3 = float(shares.nlargest(3).sum())
    return {"hhi": hhi, "top1_share": top1, "top3_share": top3, "n_strikes": int(len(shares))}


def compute_feature3_slow_state(day_dir: Path, t_hhmm: str = "15:00") -> dict:
    """OI × gamma at strikes near ATM (± 1% of spot_t), calls vs puts."""
    # Spot at t
    greek_files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not greek_files:
        return {}

    # Efficient: only read needed columns
    gsample = []
    for f in greek_files:
        try:
            df = pd.read_parquet(f, columns=["timestamp", "strike", "right", "gamma", "underlying_price"])
            df["tod"] = df["timestamp"].str.slice(11, 16)
            df = df[df["tod"] <= t_hhmm]
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            df = df.sort_values("timestamp").tail(1)
            gsample.append(df)
        except Exception:
            continue
    if not gsample:
        return {}

    g = pd.concat(gsample, ignore_index=True)
    spot_t = g["underlying_price"].median()
    if spot_t <= 0:
        return {}

    # Load OI
    oi_files = sorted((day_dir / "oi").glob("*.parquet"))
    if not oi_files:
        return {"spot_t": float(spot_t)}
    oi = pd.concat([pd.read_parquet(f) for f in oi_files], ignore_index=True)

    merged = oi.merge(g[["strike", "right", "gamma"]], on=["strike", "right"], how="inner")
    if merged.empty:
        return {"spot_t": float(spot_t)}

    # ATM ± 1%
    lo, hi = spot_t * 0.99, spot_t * 1.01
    atm = merged[(merged["strike"] >= lo) & (merged["strike"] <= hi)].copy()
    if atm.empty:
        return {"spot_t": float(spot_t), "atm_strikes_found": 0}

    atm["gex"] = atm["open_interest"] * atm["gamma"] * 100 * (spot_t ** 2)
    call_gex = atm[atm["right"] == "CALL"]["gex"].sum()
    put_gex = atm[atm["right"] == "PUT"]["gex"].sum()

    return {
        "spot_t": float(spot_t),
        "atm_call_gex": float(call_gex),
        "atm_put_gex": float(put_gex),
        "atm_gex_skew": float(call_gex - put_gex),  # >0 = call-heavy structure
        "atm_gex_total": float(call_gex + put_gex),
        "atm_strikes_found": int(len(atm["strike"].unique())),
    }


def compute_features_one_day(day_dir: Path, t_hhmm: str = "15:00") -> dict | None:
    """Wrapper: run F1 + F2 + F3 for 15m and 30m windows at decision_time t.

    Returns all 4 feature families aggregated into one flat dict for parquet.
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()

    out = {"date": d, "decision_time": t_hhmm}

    # F1 + F2 for 15m and 30m windows
    for win in [15, 30]:
        merged = load_day_enriched_window(day_dir, t_hhmm=t_hhmm, window_min=win)
        f1 = compute_feature1_flow(merged)
        f2 = compute_feature2_concentration(merged)
        for k, v in f1.items():
            out[f"{k}_{win}m"] = v
        for k, v in f2.items():
            out[f"{k}_{win}m"] = v

    # F3 slow state (one-shot at t)
    f3 = compute_feature3_slow_state(day_dir, t_hhmm=t_hhmm)
    out.update(f3)

    # F4 Interaction (continuous):
    # interaction = state × concentration × flow_direction
    # state: sign of atm_gex_skew  (call-heavy positive)
    # concentration: top3_share_30m (more focused = larger)
    # flow_direction: sign of flow_delta_net_30m
    state_sign = np.sign(out.get("atm_gex_skew", 0) or 0)
    conc = out.get("top3_share_30m", np.nan)
    flow_sign = np.sign(out.get("flow_delta_net_30m", 0) or 0)
    flow_mag = abs(out.get("flow_delta_net_30m", 0) or 0)

    out["interaction_sign"] = float(state_sign * flow_sign)  # +1 same direction, -1 opposite
    out["interaction_weighted"] = float(state_sign * conc * flow_sign * np.log1p(flow_mag)) if not pd.isna(conc) else np.nan

    return out
