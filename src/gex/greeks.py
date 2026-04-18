"""Compute higher-order Greeks (Vanna, Charm, Vomma) from BSM."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm


def bsm_d1(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    return (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def bsm_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return bsm_d1(S, K, T, r, sigma, q) - sigma * math.sqrt(T)


def compute_vanna(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0,
) -> float:
    """
    Vanna = dDelta/dSigma = -e^(-qT) * N'(d1) * d2 / sigma

    Measures how delta changes when IV changes.
    Critical for understanding MM hedging flow when vol moves.
    """
    if T <= 1e-8 or sigma <= 1e-8:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    d2_val = d1 - sigma * math.sqrt(T)
    nprime_d1 = norm.pdf(d1)
    return -math.exp(-q * T) * nprime_d1 * d2_val / sigma


def compute_charm(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0,
) -> float:
    """
    Charm = dDelta/dT (delta decay).
    How delta changes as time passes — important for intraday 0DTE.
    """
    if T <= 1e-8 or sigma <= 1e-8:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    d2_val = d1 - sigma * math.sqrt(T)
    nprime_d1 = norm.pdf(d1)
    term1 = -q * math.exp(-q * T) * norm.cdf(d1)
    term2 = math.exp(-q * T) * nprime_d1 * (
        2 * (r - q) * T - d2_val * sigma * math.sqrt(T)
    ) / (2 * T * sigma * math.sqrt(T))
    return term1 + term2


def compute_delta(S, K, T, r, sigma, is_call, q=0.0):
    if T <= 1e-8 or sigma <= 1e-8 or S <= 0 or K <= 0:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    if is_call:
        return math.exp(-q * T) * norm.cdf(d1)
    return -math.exp(-q * T) * norm.cdf(-d1)


def compute_gamma(S, K, T, r, sigma, q=0.0):
    if T <= 1e-8 or sigma <= 1e-8 or S <= 0 or K <= 0:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    return math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))


def compute_vega(S, K, T, r, sigma, q=0.0):
    if T <= 1e-8 or sigma <= 1e-8 or S <= 0 or K <= 0:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    return S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T) / 100  # per 1 vol point


def compute_theta(S, K, T, r, sigma, is_call, q=0.0):
    if T <= 1e-8 or sigma <= 1e-8 or S <= 0 or K <= 0:
        return 0.0
    d1 = bsm_d1(S, K, T, r, sigma, q)
    d2 = d1 - sigma * math.sqrt(T)
    term1 = -S * math.exp(-q * T) * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
    if is_call:
        term2 = -r * K * math.exp(-r * T) * norm.cdf(d2)
        term3 = q * S * math.exp(-q * T) * norm.cdf(d1)
    else:
        term2 = r * K * math.exp(-r * T) * norm.cdf(-d2)
        term3 = -q * S * math.exp(-q * T) * norm.cdf(-d1)
    return (term1 + term2 + term3) / 365  # per calendar day


def enrich_greeks(
    options_df: pd.DataFrame,
    spot: float,
    r: float = 0.05,
    as_of=None,
) -> pd.DataFrame:
    """
    Add Vanna/Charm and (re)compute Delta/Gamma/Vega/Theta from the `iv` column.

    Expects columns: strike, right, iv, expiry (or dte_years).
    All Greeks are recomputed from real IV; any pre-existing values are overwritten.

    Args:
        as_of: datetime/date to compute DTE against. Defaults to datetime.now()
               (live mode); pass the trade date for backtest mode.
    """
    df = options_df.copy()

    if "dte_years" not in df.columns:
        if "dte_minutes" in df.columns:
            df["dte_years"] = df["dte_minutes"] / (252 * 6.5 * 60)
        elif "expiry" in df.columns:
            from datetime import date as _date, datetime
            if as_of is None:
                now = datetime.now()
            elif isinstance(as_of, _date) and not isinstance(as_of, datetime):
                now = datetime.combine(as_of, datetime.min.time()).replace(hour=9, minute=30)
            else:
                now = as_of
            def _calc_dte(exp_str):
                try:
                    exp = datetime.strptime(str(exp_str)[:8], "%Y%m%d").replace(hour=16)
                    remaining = (exp - now).total_seconds()
                    return max(remaining / (252 * 6.5 * 3600), 1e-8)
                except Exception:
                    return 1e-8
            df["dte_years"] = df["expiry"].apply(_calc_dte)
        else:
            df["dte_years"] = 1 / 252

    deltas, gammas, vegas, thetas, vannas, charms = [], [], [], [], [], []
    for _, row in df.iterrows():
        iv = row.get("iv", 0.0)
        if pd.isna(iv) or iv <= 0:
            deltas.append(0.0); gammas.append(0.0); vegas.append(0.0)
            thetas.append(0.0); vannas.append(0.0); charms.append(0.0)
            continue
        T = row["dte_years"]
        K = row["strike"]
        is_call = row["right"] == "C"
        deltas.append(compute_delta(spot, K, T, r, iv, is_call))
        gammas.append(compute_gamma(spot, K, T, r, iv))
        vegas.append(compute_vega(spot, K, T, r, iv))
        thetas.append(compute_theta(spot, K, T, r, iv, is_call))
        vannas.append(compute_vanna(spot, K, T, r, iv))
        charms.append(compute_charm(spot, K, T, r, iv))

    df["delta"] = deltas
    df["gamma"] = gammas
    df["vega"] = vegas
    df["theta"] = thetas
    df["vanna"] = vannas
    df["charm"] = charms
    return df
