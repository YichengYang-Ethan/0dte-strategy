"""Enrich parquets with Theta Data Standard official Greeks + IV.

Replaces enrich.py's BSM-inverted IV with Theta's exchange-sourced Greeks.
Standard subscription gives us:
  - option_history_greeks_eod: delta, gamma, theta, vega, vanna, charm, vomma,
    veta, speed, zomma, color, ultima, implied_vol, underlying_price — all at EOD
  - Accurate IV surface (not BSM-inverted from mid)

Differences from enrich.py:
  - spot from `underlying_price` column in greeks response (no separate stock call)
  - iv from official `implied_vol` (no brentq)
  - All Greeks stored directly; no BSM recomputation needed downstream

Output parquet columns: timestamp, strike, right, expiry, open_interest, spot,
bid, ask, close, volume, delta, gamma, theta, vega, vanna, charm, implied_vol
"""
from __future__ import annotations
import asyncio, logging, os, time
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)


def _ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _get_client():
    from thetadata import Client
    return Client(
        email=os.getenv("THETA_USERNAME", ""),
        password=os.getenv("THETA_PASSWORD", ""),
        dataframe_type="pandas",
    )


def enrich_day_v2(client, symbol: str, trade_date: date, parquet_path: Path) -> bool:
    """Re-enrich using Theta official Greeks. Overwrites existing parquet."""
    if not parquet_path.exists():
        logger.warning(f"Skip (missing): {parquet_path}")
        return False

    df = pd.read_parquet(parquet_path)
    if df.empty:
        return False

    # Idempotency: skip if already v2-enriched (has `theta_greek` marker column)
    if "theta_greek" in df.columns:
        logger.debug(f"Already v2-enriched: {parquet_path.name}")
        return True

    expirations = sorted(df["expiry"].unique())
    greek_rows = []
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(str(exp_str), "%Y%m%d").date()
        except ValueError:
            continue
        try:
            g = client.option_history_greeks_eod(
                symbol=symbol, expiration=exp_date,
                start_date=trade_date, end_date=trade_date,
            )
            if g is None or g.empty:
                continue
            for _, r in g.iterrows():
                right_raw = str(r.get("right", ""))
                right = "C" if right_raw.upper().startswith("C") else "P"
                greek_rows.append({
                    "strike": float(r["strike"]),
                    "right": right,
                    "expiry": exp_str,
                    "bid": float(r.get("bid", 0) or 0),
                    "ask": float(r.get("ask", 0) or 0),
                    "close": float(r.get("close", 0) or 0),
                    "volume": int(r.get("volume", 0) or 0),
                    "delta": float(r.get("delta", 0) or 0),
                    "gamma": float(r.get("gamma", 0) or 0),
                    "theta_greek": float(r.get("theta", 0) or 0),  # avoid clash with expiry
                    "vega": float(r.get("vega", 0) or 0),
                    "vanna": float(r.get("vanna", 0) or 0),
                    "charm": float(r.get("charm", 0) or 0),
                    "iv": float(r.get("implied_vol", 0) or 0),
                    "underlying_price": float(r.get("underlying_price", 0) or 0),
                })
            time.sleep(0.15)
        except Exception as e:
            logger.warning(f"Greeks fetch failed {exp_date}: {e}")
            time.sleep(0.5)

    if not greek_rows:
        logger.warning(f"No greeks for {trade_date}")
        return False

    g_df = pd.DataFrame(greek_rows)
    spot_vals = g_df["underlying_price"].dropna()
    spot = float(spot_vals.iloc[0]) if not spot_vals.empty else 0.0

    # Merge: keep OI from original df, replace everything else with Theta v2
    keep_cols = [c for c in df.columns if c in ["timestamp", "strike", "right", "expiry", "open_interest"]]
    df = df[keep_cols]

    merged = df.merge(g_df, on=["strike", "right", "expiry"], how="left")
    for col in ["bid", "ask", "close", "volume", "delta", "gamma", "theta_greek",
                "vega", "vanna", "charm", "iv", "underlying_price"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    merged["spot"] = spot

    # Rename theta_greek back to theta for engine compatibility; keep marker
    merged["theta"] = merged["theta_greek"]

    merged.to_parquet(parquet_path, index=False)
    n_iv = (merged["iv"] > 0).sum()
    n_delta = (merged["delta"].abs() > 0.01).sum()
    logger.info(
        f"v2-Enriched {parquet_path.name}: spot=${spot:.2f} "
        f"iv={n_iv}/{len(merged)} delta={n_delta}/{len(merged)}"
    )
    return True


def enrich_all_v2(symbol: str = "SPY", data_dir: str = "data/historical/spy") -> int:
    _ensure_event_loop()
    client = _get_client()
    dir_path = Path(data_dir)
    files = sorted(dir_path.glob("*.parquet"))
    logger.info(f"v2-Enriching {len(files)} files from {dir_path}")

    success = 0
    for fpath in files:
        try:
            d = datetime.strptime(fpath.stem, "%Y%m%d").date()
        except ValueError:
            continue
        if enrich_day_v2(client, symbol, d, fpath):
            success += 1
        time.sleep(0.2)

    logger.info(f"v2-Enriched {success}/{len(files)} days")
    return success


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/historical/spy")
    args = ap.parse_args()
    enrich_all_v2("SPY", args.data_dir)
