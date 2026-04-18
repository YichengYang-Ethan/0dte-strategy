"""GEX (Gamma Exposure) and Vanna Exposure calculator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class GEXLevels:
    call_wall: Optional[float]
    put_wall: Optional[float]
    total_gex: float
    regime: str  # "POSITIVE_GAMMA" or "NEGATIVE_GAMMA"
    spot: float
    gex_by_strike: dict[float, float]
    zero_gex: Optional[float]


@dataclass
class VannaExposure:
    total_vanna: float
    direction: str  # "BULLISH_VANNA" or "BEARISH_VANNA" or "NEUTRAL"


def calculate_gex_profile(
    options_df: pd.DataFrame,
    spot: float,
) -> dict[float, float]:
    """
    Calculate Gamma Exposure per strike using SpotGamma standard formula.

    GEX_strike = gamma × OI × 100 × spot² × 0.01

    This represents the dollar delta change per 1% move in the underlying.
    SpotGamma convention: calls positive, puts negative (assumes dealer short).

    Limitation: assumes ALL open interest is dealer-short. Breaks when
    institutions are net sellers (e.g., covered call overwriting) or at
    strikes with heavy inter-dealer flow. Without CBOE-level trade
    direction data, this is the best available approximation.

    For 0DTE contracts: EOD OI does not capture same-day-open contracts.
    Use intraday volume as supplemental proxy (see volume_proxy_gex).

    Reference: Barbon & Buraschi "Gamma Fragility" (2021, SSRN 3725454)

    Args:
        options_df: DataFrame with columns [strike, gamma, open_interest, right]
                    Optionally includes 'volume' for intraday proxy.
        spot: current underlying price

    Returns:
        dict mapping strike -> net GEX value (dollars of delta per 1% move)
    """
    gex = {}

    for _, row in options_df.iterrows():
        strike = row["strike"]
        gamma = row["gamma"]
        right = row["right"]

        # Use OI if available, fall back to volume as proxy for 0DTE
        oi = row.get("open_interest", 0) or 0
        if oi == 0:
            oi = row.get("volume", 0) or 0

        if oi == 0 or gamma == 0:
            continue

        # SpotGamma standard: gamma × OI × 100 × S² × 0.01
        exposure = gamma * oi * 100 * spot * spot * 0.01

        if right == "C":
            gex[strike] = gex.get(strike, 0.0) + exposure
        else:
            gex[strike] = gex.get(strike, 0.0) - exposure

    return gex


def identify_levels(gex_profile: dict[float, float], spot: float) -> GEXLevels:
    """
    Identify key GEX levels.

    Call Wall: strike with max positive GEX above spot → resistance
    Put Wall: strike with max |negative GEX| below spot → support
    0-GEX Flip: where cumulative GEX crosses zero → vol regime change
    """
    if not gex_profile:
        return GEXLevels(
            call_wall=None, put_wall=None, total_gex=0,
            regime="NEUTRAL", spot=spot, gex_by_strike={}, zero_gex=None,
        )

    above_spot = {k: v for k, v in gex_profile.items() if k >= spot and v > 0}
    below_spot = {k: v for k, v in gex_profile.items() if k <= spot and v < 0}

    call_wall = max(above_spot, key=above_spot.get) if above_spot else None
    put_wall = min(below_spot, key=below_spot.get) if below_spot else None

    total_gex = sum(gex_profile.values())
    regime = "POSITIVE_GAMMA" if total_gex > 0 else "NEGATIVE_GAMMA"

    # Find zero-GEX crossing
    strikes_sorted = sorted(gex_profile.keys())
    zero_gex = None
    for i in range(len(strikes_sorted) - 1):
        v1 = gex_profile[strikes_sorted[i]]
        v2 = gex_profile[strikes_sorted[i + 1]]
        if v1 * v2 < 0:
            weight = abs(v1) / (abs(v1) + abs(v2))
            zero_gex = strikes_sorted[i] + weight * (strikes_sorted[i + 1] - strikes_sorted[i])
            if abs(zero_gex - spot) / spot < 0.02:
                break

    return GEXLevels(
        call_wall=call_wall,
        put_wall=put_wall,
        total_gex=total_gex,
        regime=regime,
        spot=spot,
        gex_by_strike=gex_profile,
        zero_gex=zero_gex,
    )


def calculate_vanna_exposure(
    options_df: pd.DataFrame,
    spot: float,
    max_dte_days: int = 45,
) -> VannaExposure:
    """
    Total Vanna exposure (VEX) under SqueezeMetrics/FlashAlpha industry convention:

        VEX = Σ  vanna_i × OI_i × 100 × S × k_i × 0.01
        k = +1 for calls, -1 for puts   (customer-net-long convention)

    Units: dollar delta change per 1 vol point (1 IV percentage point).

    Sources cross-validated:
    - Academic: Barbon & Buraschi (2021), Baltussen et al. (JFE 2021), SqueezeMetrics whitepaper
    - Industry: FlashAlpha /concepts/vex, Menthor Q, SpotGamma, Proshotv2 reference impl
    - Linear S scaling (not S²) is a hard consensus — GEX uses S², VEX uses S¹

    Empirical calibration on 113 days of SPY: VEX in [8e7, 2e9], median ~6.6e8.
    Old hard-coded ±1e6 threshold was 3 orders of magnitude too small, which is why
    every day fired BULLISH_VANNA. Tercile classification is done by the caller
    (calculate_vanna_exposure returns raw value, signal generator buckets it).

    max_dte_days: cap included expirations at N days to avoid LEAPS dominance.
    """
    df = options_df.copy()
    if "dte_years" in df.columns:
        df = df[df["dte_years"] * 365 <= max_dte_days]

    if df.empty:
        return VannaExposure(total_vanna=0.0, direction="NEUTRAL")

    vanna = df["vanna"].fillna(0.0).astype(float)
    oi = df["open_interest"].astype(float)
    k = np.where(df["right"] == "C", 1.0, -1.0)

    total_vanna = float((vanna * oi * 100 * spot * 0.01 * k).sum())

    # Direction is now set by caller using a rolling tercile (walk-forward, no lookahead).
    # Default to NEUTRAL for backward compat; callers should use total_vanna directly.
    return VannaExposure(total_vanna=total_vanna, direction="NEUTRAL")
