"""OPRA condition code → segmentation bucket mapping.

Reference: Theta Data docs
https://docs.thetadata.us/Articles/Errors-Exchanges-Conditions/Trade-Conditions.html

Per Dong (AEA 2026), underlying price impact is concentrated in single-leg
limit-order-book electronic trades. Auctions and multi-leg trades transmit
much less information to spot. This module classifies OPRA condition codes
so the feature pipeline can segment trades by execution type.

Bucket definitions:
- single_leg_electronic: code {0, 18} — main "LOB impact" signal set
- single_leg_sweep:      code {95}    — ISO sweep, kept separate
- single_leg_auction:    code {125, 126}
- single_leg_cross:      code {127, 128}
- single_leg_floor:      code {129}
- complex_or_multileg:   legacy {35, 36, 37, 38} + modern {130-144}
- auction_openish:       exchange open auctions
- auction_closeish:      exchange close auctions
- auction_reopen:        halt reopens
- late_or_out_of_sequence: {2, 5, 6, 13, 15, 57, 65} — flag, don't use naively
- cancel:                {40-44} — HARD DISCARD
- aggressor_bid/ask:     {145, 146} — metadata only
- extended_hours:        {148}
- unknown:               anything not mapped
"""
from __future__ import annotations

COND_BUCKET: dict[int, str] = {
    # single-leg electronic (main signal)
    0: "single_leg_electronic",
    18: "single_leg_electronic",

    # single-leg sweep (optional separate bucket)
    95: "single_leg_sweep",

    # exchange auctions (open/close/halt-reopen)
    62: "auction_openish",
    63: "auction_closeish",
    66: "auction_openish",
    68: "auction_openish",
    69: "auction_closeish",
    89: "auction_openish",
    92: "auction_closeish",
    97: "auction_reopen",
    98: "auction_closeish",

    # single-leg non-LOB
    125: "single_leg_auction",
    126: "single_leg_auction",
    127: "single_leg_cross",
    128: "single_leg_cross",
    129: "single_leg_floor",

    # complex / multileg / stock-option complex
    35: "complex_or_multileg",
    36: "complex_or_multileg",
    37: "complex_or_multileg",
    38: "complex_or_multileg",
    130: "complex_or_multileg",
    131: "complex_or_multileg",
    132: "complex_or_multileg",
    133: "complex_or_multileg",
    134: "complex_or_multileg",
    135: "complex_or_multileg",
    136: "complex_or_multileg",
    137: "complex_or_multileg",
    138: "complex_or_multileg",
    139: "complex_or_multileg",
    140: "complex_or_multileg",
    141: "complex_or_multileg",
    142: "complex_or_multileg",
    143: "complex_or_multileg",
    144: "complex_or_multileg",

    # late / out-of-sequence / anomaly (flag, don't naively use)
    2: "late_or_out_of_sequence",
    5: "late_or_out_of_sequence",
    6: "late_or_out_of_sequence",
    13: "late_or_out_of_sequence",
    15: "late_or_out_of_sequence",
    57: "late_or_out_of_sequence",
    65: "late_or_out_of_sequence",

    # HARD DISCARD
    40: "cancel",
    41: "cancel",
    42: "cancel",
    43: "cancel",
    44: "cancel",

    # metadata (keep for aggressor classification)
    145: "aggressor_bid",
    146: "aggressor_ask",

    # extended hours
    148: "extended_hours",
}

# code sets for fast membership tests
KEEP_FOR_IMPACT_BASELINE = frozenset({0, 18})
SINGLE_LEG_SWEEP = frozenset({95})
NON_LOB_SINGLE_LEG = frozenset({125, 126, 127, 128, 129})
COMPLEX_OR_MULTILEG = frozenset(
    {35, 36, 37, 38} | set(range(130, 145))
)
LATE_OR_OOS = frozenset({2, 5, 6, 13, 15, 57, 65})
HARD_DISCARD = frozenset({40, 41, 42, 43, 44})
AGGRESSOR_CODES = frozenset({145, 146})
AUCTION_CODES = frozenset({62, 63, 66, 68, 69, 89, 92, 97, 98})
EXTENDED_HOURS = frozenset({148})


def classify(condition: int) -> str:
    """Return bucket name for an OPRA condition code. Defaults to 'unknown'."""
    return COND_BUCKET.get(condition, "unknown")


def is_cancel(condition: int) -> bool:
    return condition in HARD_DISCARD


def is_single_leg_electronic(condition: int) -> bool:
    return condition in KEEP_FOR_IMPACT_BASELINE


def is_late_or_oos(condition: int) -> bool:
    return condition in LATE_OR_OOS


def is_auction(condition: int) -> bool:
    return condition in AUCTION_CODES or condition in {125, 126}


def is_cross(condition: int) -> bool:
    return condition in {127, 128}


def is_complex(condition: int) -> bool:
    return condition in COMPLEX_OR_MULTILEG


def is_floor(condition: int) -> bool:
    return condition == 129


def is_sweep(condition: int) -> bool:
    return condition in SINGLE_LEG_SWEEP


def aggressor_side(condition: int) -> str | None:
    """Return 'bid' or 'ask' if condition encodes aggressor, else None."""
    if condition == 145:
        return "bid"
    if condition == 146:
        return "ask"
    return None
