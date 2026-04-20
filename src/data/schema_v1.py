"""Parquet schema v1 for intraday 0DTE recorder.

Five datasets (not one sparse table):
  - option_quote
  - option_trade
  - option_greeks_1m       (REST-backfilled, not live)
  - option_open_interest   (REST daily)
  - index_price            (SPX index stream)

Schema constraints:
  - Live stream uses date + ms_of_day; REST uses timestamp string. Both are
    normalized to event_ts_utc AND raw fields are preserved.
  - Live stream strike is integer in 1/10 cent; REST strike is dollar float.
    Canonical contract key uses strike_1dc (integer 1/10 cent).
  - source_mode column distinguishes stream vs REST rows so downstream
    code can filter or join.

Partitioning:
  {dataset}/root=SPXW/date=YYYY-MM-DD/hour=HH/part-*.parquet  (quote/trade/index)
  {dataset}/root=SPXW/date=YYYY-MM-DD/part-*.parquet          (greeks/OI)

Compression: zstd.
Writer: PyArrow (buffer 5-10 sec, flush on threshold).
"""
from __future__ import annotations

import pyarrow as pa

# Shared key columns for all OPTION datasets
_SHARED_OPTION_FIELDS = [
    pa.field("source_mode", pa.string()),              # stream | rest_history | rest_snapshot | rest_trade_quote
    pa.field("event_type", pa.string()),               # quote | trade | greeks_1m | open_interest | index_price
    pa.field("feed_family", pa.string()),              # opra | theta_computed | cboe_cgif
    pa.field("root", pa.string()),                     # SPX | SPXW
    pa.field("underlying_symbol", pa.string()),        # derived: SPX
    pa.field("settlement_style", pa.string()),         # AM | PM | null
    pa.field("expiration_yyyymmdd", pa.int32()),
    pa.field("expiration_date", pa.date32()),
    pa.field("strike_1dc", pa.int32()),                # canonical contract key (1/10 cent)
    pa.field("strike", pa.float64()),                  # dollars
    pa.field("right", pa.string()),                    # C | P

    pa.field("event_ts_utc", pa.timestamp("ms", tz="UTC")),
    pa.field("source_timestamp_text", pa.string()),    # raw REST timestamp
    pa.field("raw_date_yyyymmdd", pa.int32()),         # raw stream date
    pa.field("ms_of_day", pa.int32()),                 # raw stream ms_of_day

    pa.field("ingest_ts_utc", pa.timestamp("ms", tz="UTC")),
    pa.field("header_type", pa.string()),              # QUOTE | TRADE | etc.
    pa.field("header_status", pa.string()),
]

# ----- option_quote -----
OPTION_QUOTE_FIELDS = _SHARED_OPTION_FIELDS + [
    pa.field("bid_size", pa.int32()),
    pa.field("bid_exchange", pa.int16()),
    pa.field("bid", pa.float64()),
    pa.field("bid_condition", pa.int16()),
    pa.field("ask_size", pa.int32()),
    pa.field("ask_exchange", pa.int16()),
    pa.field("ask", pa.float64()),
    pa.field("ask_condition", pa.int16()),

    # derived at ingest (avoid backfill later)
    pa.field("mid", pa.float64()),
    pa.field("spread", pa.float64()),
    pa.field("spread_pct", pa.float64()),
]
OPTION_QUOTE_SCHEMA = pa.schema(OPTION_QUOTE_FIELDS)

# ----- option_trade -----
OPTION_TRADE_FIELDS = _SHARED_OPTION_FIELDS + [
    pa.field("sequence", pa.int64()),
    pa.field("size", pa.int32()),
    pa.field("condition", pa.int16()),
    pa.field("exchange", pa.int16()),
    pa.field("price", pa.float64()),

    # REST-only extended conditions; null for stream
    pa.field("ext_condition1", pa.int16()),
    pa.field("ext_condition2", pa.int16()),
    pa.field("ext_condition3", pa.int16()),
    pa.field("ext_condition4", pa.int16()),

    # derived from condition bucketing
    pa.field("condition_bucket", pa.string()),
    pa.field("is_cancel", pa.bool_()),
    pa.field("is_late_or_oos", pa.bool_()),
    pa.field("is_auction", pa.bool_()),
    pa.field("is_cross", pa.bool_()),
    pa.field("is_complex", pa.bool_()),
    pa.field("is_floor", pa.bool_()),
    pa.field("is_sweep", pa.bool_()),
    pa.field("is_single_leg_electronic", pa.bool_()),
    pa.field("aggressor_side", pa.string()),           # bid | ask | null
    pa.field("is_extended_hours", pa.bool_()),
]
OPTION_TRADE_SCHEMA = pa.schema(OPTION_TRADE_FIELDS)

# ----- option_greeks_1m -----
OPTION_GREEKS_FIELDS = _SHARED_OPTION_FIELDS + [
    pa.field("bid", pa.float64()),
    pa.field("ask", pa.float64()),

    pa.field("delta", pa.float64()),
    pa.field("theta", pa.float64()),
    pa.field("vega", pa.float64()),
    pa.field("rho", pa.float64()),
    pa.field("epsilon", pa.float64()),
    pa.field("lambda_", pa.float64()),                 # lambda is Python keyword
    pa.field("gamma", pa.float64()),
    pa.field("vanna", pa.float64()),
    pa.field("charm", pa.float64()),
    pa.field("vomma", pa.float64()),
    pa.field("veta", pa.float64()),
    pa.field("vera", pa.float64()),
    pa.field("speed", pa.float64()),
    pa.field("zomma", pa.float64()),
    pa.field("color", pa.float64()),
    pa.field("ultima", pa.float64()),
    pa.field("d1", pa.float64()),                      # docs sometimes type as string; coerce
    pa.field("d2", pa.float64()),
    pa.field("dual_delta", pa.float64()),
    pa.field("dual_gamma", pa.float64()),
    pa.field("implied_vol", pa.float64()),
    pa.field("iv_error", pa.float64()),                # wing diagnostic, do not ignore

    pa.field("underlying_timestamp_utc", pa.timestamp("ms", tz="UTC")),
    pa.field("underlying_price", pa.float64()),
]
OPTION_GREEKS_SCHEMA = pa.schema(OPTION_GREEKS_FIELDS)

# ----- option_open_interest -----
OPTION_OI_FIELDS = _SHARED_OPTION_FIELDS + [
    pa.field("open_interest", pa.int32()),
    pa.field("oi_report_ts_utc", pa.timestamp("ms", tz="UTC")),
]
OPTION_OI_SCHEMA = pa.schema(OPTION_OI_FIELDS)

# ----- index_price -----
# SPX index has no strike/expiry/right — separate schema, not in shared set
INDEX_PRICE_FIELDS = [
    pa.field("source_mode", pa.string()),
    pa.field("event_type", pa.string()),               # index_price
    pa.field("feed_family", pa.string()),              # cboe_cgif
    pa.field("root", pa.string()),                     # SPX

    pa.field("event_ts_utc", pa.timestamp("ms", tz="UTC")),
    pa.field("source_timestamp_text", pa.string()),
    pa.field("raw_date_yyyymmdd", pa.int32()),
    pa.field("ms_of_day", pa.int32()),
    pa.field("ingest_ts_utc", pa.timestamp("ms", tz="UTC")),
    pa.field("header_type", pa.string()),
    pa.field("header_status", pa.string()),

    pa.field("price", pa.float64()),
    pa.field("sequence", pa.int64()),
    pa.field("condition", pa.int16()),
    pa.field("exchange", pa.int16()),
    pa.field("size", pa.int32()),
]
INDEX_PRICE_SCHEMA = pa.schema(INDEX_PRICE_FIELDS)


# Mapping for writer
SCHEMAS = {
    "option_quote": OPTION_QUOTE_SCHEMA,
    "option_trade": OPTION_TRADE_SCHEMA,
    "option_greeks_1m": OPTION_GREEKS_SCHEMA,
    "option_open_interest": OPTION_OI_SCHEMA,
    "index_price": INDEX_PRICE_SCHEMA,
}
