# Scripts

## Paper-trade runner

```bash
# Run daily (cron-friendly)
cd ~/0dte-strategy && python3 scripts/paper_trade.py --mode daily

# Or split by phase
python3 scripts/paper_trade.py --mode fill      # settle pending exits
python3 scripts/paper_trade.py --mode signal    # compute last-trading-day signal
python3 scripts/paper_trade.py --mode summary   # show log + running P&L

# Backfill a specific date
python3 scripts/paper_trade.py --mode signal --date 2026-03-13
```

### Suggested cron (runs 8:30 AM ET = 7:30 AM CT)

```cron
30 7 * * 1-5 cd ~/0dte-strategy && /usr/bin/env python3 scripts/paper_trade.py --mode daily >> ~/0dte-strategy/paper_trade_cron.log 2>&1
```

Theta Data publishes EOD OI ~7-8 AM ET the next morning, so 8:30 AM ET is the
earliest safe run time.

## Data pipeline

- `download_oos.py` — downloads 2025-05-15 → 2025-10-30 OI (1st OOS)
- `download_extended.py` — downloads 2024-01-02 → 2025-05-14 OI (2nd OOS)
- `enrich_oos.py` — fills in real EOD quotes + spot + IV on all parquets

## Validation

- `validate_oos.py` — IS vs ORIG_OOS split (232 days)
- `validate_extended.py` — IS vs ORIG_OOS vs EXT_OOS split (574 days)
