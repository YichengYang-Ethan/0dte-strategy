# GPT Pro Research Brief — Theta Options Pro Integration (Round 5)

## Context

Starting a 6-12 week falsification-spike project to test an intraday dealer-pressure thesis on SPX 0DTE options. The strategy framing, kill criteria, and 7-milestone roadmap have been committed already — this round is purely about **data plumbing**: how to get the right Theta Data Options Pro stream into local parquet cleanly and correctly the first time, without spending 3-5 days on trial-and-error.

**Extended thinking.** Be technically precise. I'd rather get a long right answer now than a wrong short one.

## Committed infrastructure choices

- Data vendor: **Theta Data Options Pro** ($160/mo, upgrading tonight from Standard $80). Not buying massive.com — prior research confirmed their public docs show no aggressor-side field.
- Broker: **IBKR** for execution (paper account first, options permissions approved). moomoo as backup.
- Language: **Python 3.14** on macOS
- Storage: **parquet** via pandas (current 1DTE project archive already uses this)
- Recording target: **SPX + SPXW intraday chain**, 0DTE + 1-3DTE for context, all strikes, full trading day (8:30 AM - 3:15 PM CT)
- Time horizon: **1-minute bars** primary; event-level trades/quotes preserved for replay

## What I need from you

### Q1. Theta Options Pro WebSocket schema — concrete field list

For each of these streams, tell me the exact field names + types + whether it's part of OPRA standard or a Theta extension:

1. **Option NBBO quote stream** (every bid/ask update)
2. **Option trade stream** (every reported trade with size/exchange/condition)
3. **1-min Greeks endpoint** (whatever they deliver at the bar boundary: delta/gamma/theta/vega/vanna/charm/IV + underlying)
4. **Open interest endpoint** (daily update per their docs — confirm timing)
5. **Underlying price stream** (for SPX index level; is this a separate subscription?)

Where fields differ between WebSocket real-time and REST historical endpoints, flag the differences. I want one parquet schema that covers both.

### Q2. OPRA condition codes — the practical subset

There are ~90 OPRA condition code values defined. For a 0DTE bot doing single-leg LOB vs auction vs multi-leg segmentation (per Dong's AEA 2026 evidence), I need:

- Which codes indicate single-leg limit-order-book execution (the ones that matter for underlying impact)?
- Which codes indicate exchange auctions (SPY/SPX opening auction, QOO, etc.)?
- Which codes indicate multi-leg / complex orders / spread trades?
- Which codes are "late report" / "out of sequence" (need to filter out or handle specially)?
- Which codes are "cancelled trade" (must discard)?

I want a concrete map from OPRA code → segmentation bucket, usable in production code.

### Q3. Subscribing to SPX + SPXW full chain without hitting rate limits

Theta's pricing page advertises Pro has "stream every option trade", but SPX + SPXW in 2026 is ~60-90k strike/expiry combinations on a normal day. Strategies:

- Should I subscribe to the full chain symbol-by-symbol (one WebSocket sub per contract) or is there a chain-level bulk subscription?
- What's the practical message rate for SPX+SPXW full chain on an active day?
- What's the right way to filter: only active expirations (0-3 DTE)? Only strikes within ±5% of spot? Both?
- Are there published rate limits (messages/sec, concurrent subscriptions, bandwidth)?
- How do reconnects work if I fall behind — snapshot replay, message backfill, or just re-subscribe-from-now?

### Q4. SPX vs SPXW vs SPXQ vs EOM — expiration code disambiguation

Cboe lists several SPX-family expiration types:

- **SPX** — traditional 3rd-Friday monthly, AM-settled
- **SPXW** — weekly + EOD, PM-settled, daily expirations Mon-Fri
- **SPXQ** — quarterly
- **EOM** — end-of-month

For 0DTE, I care about SPXW daily expirations primarily. Tell me:

- How to identify each type in Theta's expiration field (is there a `root` / `option_type` / expiration-class code)?
- AM-settled (SPX) vs PM-settled (SPXW): settlement timing and implications for 0DTE — AM settlement happens at market open using SOQ (Special Opening Quotation), so AM-settled contracts are actually "done trading" by 3rd Friday close of prior day in practice. Confirm this is right.
- On 3rd-Friday weeks, is there a risk of pulling SPX and SPXW into the same chain analysis by mistake?
- Same question for quarterly roll days (end of March, June, Sept, Dec).

### Q5. Greeks — Theta-computed vs exchange-delivered

Theta advertises Greeks in both their historical EOD and streaming tiers. But Greeks aren't standard OPRA; they're computed. Questions:

- Does Theta compute Greeks themselves (what IV model — BSM, CRR, something else)?
- Are the Greeks computed using the NBBO mid, last trade, or something else as the option price input?
- How do they handle IV computation in deep-ITM / deep-OTM wings where mid is unstable?
- Can I request the raw underlying price they used alongside each Greeks snapshot, so I can recompute myself if needed?
- For 0DTE specifically, the last hour of trading has extreme gamma and Greeks instability. Do they clip / regularize / truncate, or do they pass through raw computed values?

For my feature pipeline I'm considering computing Greeks myself from scratch using BSM to have full control. Am I better off using theirs or rolling my own?

### Q6. Reconnection and gap handling — their SDK behavior

If my recorder disconnects mid-session:

- Does their Python SDK auto-reconnect?
- On reconnect, does it backfill the missed messages, or just start fresh from now?
- Is there a message sequence number I can use to detect gaps on my end?
- What's the expected recovery time on typical network blips vs sustained disconnects?
- How should I architect the recorder to be robust: single process with auto-reconnect, or a supervisor + worker pattern?

### Q7. Storage format — parquet schema v1

Draft a concrete parquet schema that:

- Supports both real-time streaming writes (append-friendly) and historical REST backfill (batch-friendly) without schema change
- Preserves enough OPRA detail for segmentation (condition codes, exchange)
- Stores both raw and derived fields (raw bid/ask AND mid AND spread_pct)
- Handles intraday OI snapshots (even if "daily" update, store the timestamp of the update)
- Is efficient at ~60-90k rows/minute on active days

Propose a schema. Specifically:

- Column names (final — I don't want to refactor)
- Dtypes (int32 vs int64 vs float32 vs float64 tradeoffs)
- Partitioning scheme (one file per day? per hour? by root?)
- Compression (zstd vs snappy vs lz4)

### Q8. Known pitfalls and vendor-specific gotchas

Please list every Theta-specific quirk you know:

- Bugs documented in their issue tracker or Discord
- Timing issues (e.g. their timestamps in UTC vs exchange time, nanosecond vs millisecond)
- Known data quality issues (missing Greeks on certain strikes, stale quotes, etc.)
- Historical vs real-time inconsistencies
- Anything about holidays / half-days / early closes that will break naive date logic
- How they represent 0DTE differently from 1DTE+ (same-day expiry edge cases)

### Q9. Minimum viable recorder — concrete first-hour plan

If I were handing this to a senior dev tonight, what's the narrowest possible first-hour deliverable that:

1. Connects to Theta Options Pro WebSocket
2. Subscribes to SPX + SPXW 0DTE for today
3. Writes every quote and trade to local parquet
4. Logs basic health metrics (messages/sec, gaps, errors)

I want the minimum viable recorder, not the final one. First-hour target is "does it run cleanly for 30 minutes without crashing and produce a non-trivial parquet file". Give me a pseudocode skeleton or checklist I can execute against.

### Q10. What I should explicitly NOT try to build in the recorder

To avoid scope creep on the first night, what should I resist adding until after the basic stream is stable? Things like:

- Greeks recomputation
- Feature engineering
- Backfill
- Multi-day session rollover
- Performance optimization

I want a "minimum useful, maximum deferred" list so I don't gold-plate Phase 1.

## Format for your response

Please go section by section. Cite Theta's own documentation URLs where possible (pricing / API / blog / docs pages). If Theta's docs don't specify something clearly, say "Theta docs don't specify — my best guess is X based on Y". Don't make up field names.

Flag the top 3 things most likely to waste 1-2 days if I don't know them before writing the first line of code.

Not looking for strategy-level discussion here. Only plumbing. Prior rounds (archived) handled thesis + feature set + execution + validation + kill criteria.

Brutal on data realism. If Theta Pro can't actually deliver what I'm assuming, say so explicitly. $160/mo only matters if what arrives is what I think is arriving.
