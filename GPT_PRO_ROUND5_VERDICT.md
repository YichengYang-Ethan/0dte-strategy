# Round 5 Verdict — Theta Options Pro Integration

## Summary

GPT Pro Round 5 confirmed several constraints and uncovered several real blockers that would have cost days to discover in code. Verdict is accepted with **two independent modifications** where Round 5 was overly conservative or missed items.

## What Round 5 confirmed (accepted as-is)

1. **No bulk live quote stream** — Pro caps simultaneous quote subscriptions at 15,000 contracts. Bulk quote streaming listed on roadmap but not shipped. Trades have a bulk stream; quotes do not.
2. **No live Greeks stream** — Greeks available only via REST 1-min history / snapshot. Theta computes them (BSM European + bisection IV).
3. **OI is daily** — updated ~06:30 ET, reflects prior-day close. Not intraday.
4. **SPX is AM-settled monthly; SPXW is PM-settled daily/weekly** — SPX 0DTE is legacy-only in practice; real 0DTE live work is SPXW.
5. **Expiring SPXW trades until 3:00 PM CT, non-expiring until 3:15 PM CT** — recorder window unchanged but exit logic must gate on expiring status.
6. **Reconnect = resume from now** — no replay/backfill of missed messages. Must patch gaps from REST later.
7. **Stream uses `date + ms_of_day` integer format; REST uses timestamp string; strikes in 1/10 cent vs dollars** — schema must normalize but preserve raw.
8. **Full trade stream includes surrounding quote + OHLC messages** — confusing; use contract-by-contract for MVP.
9. **Python 3.14 risk** — Theta examples tested on 3.11. Keep dependencies minimal.
10. **OPRA condition code practical bucketing** — {0, 18} baseline single-leg LOB; {95} optional sweep; {125-129, 35-38, 130-144} non-LOB; {2, 5, 6, 13, 15, 57, 65} late/OOS; {40-44} hard discard.

## Independent modifications

### MOD 1: Expand scope from "0DTE only" to "0-3DTE" for live quote streaming

**GPT Pro recommended**: record 0DTE only to stay under 15k cap.
**My analysis**: miscounted contract volume.

SPXW active strike envelope around spot is ~±5% for 0DTE, slightly wider for 1-3DTE. Per expiration that is roughly 80 strikes × 2 rights = 160 contracts. Total:

- 0DTE only: ~160 contracts
- 0-3DTE (4 expirations): ~640-1280 contracts
- Well under 15k cap with 10x+ headroom

The research brief explicitly identified 1-3DTE as "context" for OI anchor. Restricting to 0DTE removes the prior-close positioning context that the academic feature set relies on.

**Decision**: live-record **0-3DTE**, add runtime monitor for active subscription count. Kill gate: if count exceeds 10,000 at any point, drop to 0-1DTE.

### MOD 2: Add items Round 5 did not flag

**a. Disk space budget**
Active SPXW 0-3DTE with ~1000 contracts, realistic ~5-10 quote updates/second across the active subset = ~120k-250k quote rows/day, ~20k trade rows/day. Compressed parquet estimate: ~400 MB/day, ~100 GB/year. Needs monitor, not blocker.

**b. Theta Terminal startup orchestration**
Recorder must not connect blindly. Sequence: (1) ensure Terminal running, (2) verify `mdds/status` + `fpss/status` healthy, (3) then open WebSocket. Failure to verify Terminal state = silent no-data recording. First-hour deliverable must include this.

**c. Python 3.14 websockets compat — run first**
Theta examples tested on 3.11. My environment is 3.14. Before writing the recorder, verify `websockets` package (or chosen async lib) works on 3.14 with Theta Terminal. 1-hour spike before any production code.

**d. Market calendar**
Holidays, half-days (day after Thanksgiving, Christmas Eve), early closes. Not Day 1, but Week 2. `pandas_market_calendars` or `exchange_calendars` already exists; don't reinvent.

## Committed technical decisions

### Scope
- Live stream: **SPXW 0-3DTE quotes + trades only** (not full chain, not market-wide)
- SPX 0DTE: skip (legacy AM-settled, rarely active same-day)
- Greeks: REST 1-min history, fetched daily EOD
- OI: REST snapshot, fetched daily
- Underlying: separate SPX index stream (`sec_type: INDEX`, `root: SPX`)

### Subscription pattern
- Contract-by-contract quote + trade
- Incrementing request IDs in `sub_registry`
- Reconnect → resubscribe entire registry with new IDs, log gap window
- `MAX_STREAMS_REACHED` → narrow universe, alert

### Storage
- 5 separate parquet datasets (not one sparse table)
- Canonical column vocabulary shared across stream + REST
- Partitioning: `{dataset}/root=/date=YYYY-MM-DD/hour=HH/`
- Compression: zstd
- Write pattern: 5-10 second microbatch, PyArrow writer

### What we explicitly do NOT build Night 1
- Recomputed Greeks
- Feature engineering
- Historical backfill
- Multi-day rollover
- Holiday calendar
- Full trade stream
- 1-3DTE live quotes (only after 0DTE count verified)
  - wait — MOD 1 says do 0-3DTE. Clarify: Night 1 = 0DTE only to verify plumbing works. Expand to 0-3DTE once Night 1 runs clean for 30 minutes.

## Night 1 scope — minimal viable recorder

1. Verify Terminal running + healthy
2. List SPXW 0DTE contracts via REST
3. Connect single WebSocket
4. Subscribe contract-by-contract (quote + trade) with incrementing req_id
5. Parse only STATUS / REQ_RESPONSE / QUOTE / TRADE
6. Write 5-sec microbatches to parquet
7. Log metrics every 10 sec
8. On disconnect: reconnect, resubscribe from registry, log gap
9. Run 30 min clean = Night 1 success

## Week 1 expansion

- Day 1: 0DTE SPXW verify clean
- Day 2: expand to 1DTE SPXW
- Day 3: expand to 2-3DTE SPXW
- Day 4: add Greeks + OI REST daily EOD job
- Day 5: add SPX index stream
- Day 6-7: QA + chain state reconstruction test (M1 kill gate)

## Risk register

| Risk | Mitigation |
|------|-----------|
| Python 3.14 websockets incompatibility | 1-hour compat spike before code |
| Terminal crashes mid-session | Supervisor script restarts Terminal + recorder |
| Disconnect during peak period | Gap logging + REST backfill (Week 2) |
| 15k cap hit after 1-3DTE expansion | Runtime monitor, fallback to 0-1DTE |
| Schema drift between vendor versions | Canonical schema + `source_mode` column + raw fields preserved |
| Night 1 never runs clean 30 min | Review Theta Discord, REST-only fallback for first week of backtest data |
