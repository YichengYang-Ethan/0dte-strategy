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
    Calculate Gamma Exposure per strike.

    GEX_strike = gamma × OI × 100 × spot

    Calls: MM typically short → dealer is long gamma → positive GEX
    Puts: MM typically short → put gamma hedge reverses → negative GEX

    Args:
        options_df: DataFrame with columns [strike, gamma, open_interest, right]
        spot: current underlying price

    Returns:
        dict mapping strike -> net GEX value
    """
    gex = {}

    for _, row in options_df.iterrows():
        strike = row["strike"]
        gamma = row["gamma"]
        oi = row["open_interest"]
        right = row["right"]  # "C" or "P"

        exposure = gamma * oi * 100 * spot

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
) -> VannaExposure:
    """
    Calculate total Vanna exposure.

    Vanna = dDelta/dIV.
    When IV drops (bullish move), positive vanna → MM sells delta → bearish pressure.
    When IV drops + negative vanna → MM buys delta → bullish reinforcement.
    """
    total_vanna = 0.0

    for _, row in options_df.iterrows():
        vanna = row.get("vanna", 0.0)
        if pd.isna(vanna):
            continue
        oi = row["open_interest"]
        right = row["right"]

        exposure = vanna * oi * 100
        if right == "P":
            exposure = -exposure
        total_vanna += exposure

    if total_vanna > 1e6:
        direction = "BULLISH_VANNA"
    elif total_vanna < -1e6:
        direction = "BEARISH_VANNA"
    else:
        direction = "NEUTRAL"

    return VannaExposure(total_vanna=total_vanna, direction=direction)
