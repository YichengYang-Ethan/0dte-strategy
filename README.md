# 0DTE Strategy Research

Research and implementation of SPX 0DTE options strategies, with a long
archival trail of prior attempts.

**Current direction:** practitioner-inspired reconstruction (rule-based,
event-triggered, long-gamma, target-price engine). See
[`ARCHITECTURE_R0_REBUILD.md`](ARCHITECTURE_R0_REBUILD.md) for the
active R0 spec.

---

## Project timeline (most recent first)

| Phase | Status | Ref |
|-------|--------|-----|
| **practitioner-inspired reconstruction (R0 architecture)** | **active** | `ARCHITECTURE_R0_REBUILD.md` |
| Short-vol exploratory branch | archived | `ARCHIVE_SHORT_VOL_BRANCH.md` |
| Intraday 5-day MVP (direction-first) | falsified | `logs/intraday_day3_report.md` |
| Daily/overnight baselines M1-M4 | falsified | `GPT_PRO_M4_FALSIFICATION_COMPLETE.md` |
| 1DTE swing (prior project) | archived | tag `v1-1dte-archive` |

Each row is a complete falsification or pivot decision, backed by an
external review (GPT Pro) verdict. Nothing is "paused" or "on hold" —
if it isn't in the active row, it's dead or on a branch.

---

## Active phase: practitioner reconstruction

### What it is

A rule-based SPX 0DTE trading system reconstructed from a field research
transcript with a friend ("the reference operator") who runs a live bot. **Not a
replication** — transcript doesn't give code-level spec and the reference operator won't
be asked for clarifications. Honest framing is **practitioner-inspired
reconstruction from transcript + public literature + own inference**.

### What's different from the prior work

| Axis | Prior attempt | practitioner rebuild |
|------|---------------|-------------|
| direction | tried short-vol; tried regression | **long gamma** (buy ATM call/put/butterfly) |
| entry timing | fixed 15:00 ET decision | **event / structure triggered**, minute resolution |
| target | regression on signed_ret_pct / realized_var | **rule-based target price engine** |
| method | OLS + Bonferroni | **grid-searched integer weights** |
| features | delta/gamma flow + HHI + atm±1% GEX | walls + bucketed Vanna + IV spike + abnormal flow |
| instrument | ATM only | **call / put / butterfly** by target geometry |
| exit | fixed 15:55 ET | **dynamic** (target hit / structure fail / stop / time) |

### Stages

Five stages, each with a pre-declared kill gate (see
`ARCHITECTURE_R0_REBUILD.md` §6):

- **R1** — Vanna pipeline (bucketed by expiry, dealer-signed OI-weighted)
- **R2** — Structural features (call/put walls, IV spike, abnormal flow)
- **R3** — Target engine + dumb-baseline kill gate
- **R4** — Long-gamma PnL with conservative (ask-in/bid-out) fills
- **R5** — Nested walk-forward grid search + stability gate

Total: ~10 days, stop-don't-rationalize at every gate.

---

## Archived branches

### Short-vol exploratory branch

A statistically significant finding that `atm_gex_skew` predicts
intraday realized variance compression (matches Dim-Eraker-Vilkov
2024). **Not the active path** — structurally unrelated to the reference operator's
long-gamma bot. Full details: `ARCHIVE_SHORT_VOL_BRANCH.md`.

- Tag: `v2-short-vol-exploratory-archive`
- Branch: `archive/short-vol-exploratory`
- Findings: V1 state-only ΔR² = +0.008 over persistence baseline
  (Bonferroni-significant). Too small to survive short-straddle
  wrapper costs.

### 1DTE swing (prior project)

EOD → next-EOD swing on SPY 1DTE 0.70Δ calls. Full GEX/Vanna-driven
signal, 3 rounds of GPT Pro review, overnight gap risk unmitigated.
Archived in favor of intraday.

- Tag: `v1-1dte-archive`
- Findings: signal captured conditional drift (PF 1.67 full-sample),
  but long-call wrapper ate ~41% of edge; debit spread ate ~95%.

---

## Data

- **Theta Data Pro** (~$40/mo Value tier): historical 1-min OPRA
  trades/quotes + Greeks for SPX. 952 days downloaded (2022-07 to
  2026-04). 16 GB, ATM ±3% strike range.
- **IB Gateway paper** (port 4002, DUH719324): planned execution venue
  for future live trading. Delayed SPY $711 as of 2026-04-20.

Not used (but flagged):
- Massive.com L2 websocket ($200/mo) — the reference operator's data source. Current
  Massive docs expose NBBO but no documented options L2 depth. Theta
  Data historical is sufficient for research stage.

---

## Repo layout

```
ARCHITECTURE_R0_REBUILD.md   ← R0 pre-registration (active)
ARCHIVE_SHORT_VOL_BRANCH.md    ← what's in the short-vol archive

src/pipeline/
├── leak_safe.py               ← leak-safe primitives (reusable)
└── intraday_features.py       ← short-vol feature extraction (archive)

scripts/                       ← one-shot analyses per stage
├── intraday_day1_labels.py    ← labels (reusable)
├── intraday_day2_features.py  ← short-vol features (archive)
├── intraday_day2_5_diagnostics.py  ← archive
└── intraday_day3_baselines.py      ← archive

data/
├── historical_0dte/           ← 952 days Theta Data parquets (16 GB, gitignored)
├── intraday_labels.parquet    ← reusable for practitioner rebuild
└── intraday_features.parquet  ← archive

logs/                          ← per-stage reports
GPT_PRO_*.md                   ← external review briefs + verdicts
```

---

## GPT Pro review history

Each pivot or kill decision is backed by a dated external review. Full
set preserved in repo root; newest first:

| Date | Brief | Verdict topic |
|------|-------|---------------|
| 2026-04-20 | `GPT_PRO_REALIGN_PATH.md` | Am I on the reference operator's path or drifting? |
| 2026-04-19 | `GPT_PRO_DAY2_5_UNEXPECTED.md` | Direction dead, volatility surfaces — snooping? |
| 2026-04-18 | `GPT_PRO_M4_FALSIFICATION_COMPLETE.md` | M1-M4 all failed — pivot direction |
| 2026-04-17 | `GPT_PRO_BASELINE1_V2.md` | Median-spot leak — edge was artifact |
| 2026-04-16 | `GPT_PRO_0DTE_BRIEF.md` | Initial 0DTE research scope |

---

## Risk / disclaimer

Research code, not investment advice. 0DTE options can lose 100% of
premium in minutes. No position is live.

## License

MIT (see `LICENSE`).
