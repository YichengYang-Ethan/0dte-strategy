# CLAUDE.md — 0DTE Strategy Repo

**This file is loaded automatically when Claude works in this repo.**
**Read first, then `docs/R0_RIP_2026_04_21.md` for the full narrative.**

## Current state: ARCHIVED (2026-04-21)

This repo is the terminal artifact of a 0DTE research sprint that
empirically falsified its own core thesis. **No new strategy
development should start here without user reopening the question.**

- **GitHub:** `github.com/YichengYang-Ethan/0dte-strategy` — PUBLIC
- **Archive tag:** `v3-archive-r0-falsified`
- **Release:** <https://github.com/YichengYang-Ethan/0dte-strategy/releases/tag/v3-archive-r0-falsified>
- **Landing card:** `yichengyang-ethan.github.io/strategies` → "Code →" links here
- **Data on disk:** `data/historical_0dte/` (~16 GB, 952 days SPXW 0DTE
  minute-resolution, 2022-07 → 2026-04) — NOT in git
- **Private info scrubbed:** all references to a named peer ("Joey" in
  original field research) have been replaced with neutral terminology.
  Old commits in git history still contain the original names; scrubbing
  history was declined to preserve commit integrity.

## What we tested and killed (one-line each)

- **v5 swing_1dte (NEG_GAMMA + pos<0.15 → BULLISH 1DTE call):** PF 1.23-1.77
  across 574 days, but edge is overnight MR not GEX mechanism (check2c
  proved this). Y2023 bucket PF 0.78. Archived Apr 18.
- **R0 intraday target prediction (walls as pin attractors):** check2 KILL
  + check2b 24-cell grid 0 pass. Walls do not predict 15:55 spot from
  any (entry_time, window) combination.
- **A1 momentum-not-pin rebuild:** check2c showed 49.0% pin / 49.7%
  momentum hit rate — random walk, no directional mechanism at 85-min
  horizon.
- **A2 Joey-style frozen-feature pilot:** max single-feature lift 1.19×
  base rate vs pre-registered 2× threshold. No single frozen feature
  (GEX_state, pos_in_range, flow_sign, ATM_IV, overnight_gap, VIX_proxy)
  has prospective target-hit lift on 719 EXT_OOS days.
- **Strategy delta §5 (weak-trend no-trade "free alpha"):** V4 showed
  precision 0.34 / recall 0.38 on 30-min open-range prospective
  classifier. Not separable prospectively.

## What survived (preserved for reuse, documented as methodology)

- **`src/pipeline/leak_safe.py`** (439 LOC) — future-poison-tested
  leak-safe primitives. `compute_day_flow_leak_safe` uses Lee-Ready
  signing on single-leg electronic trades (condition ∈ {0, 18}, Dong
  AEA 2026 filter).
- **check3 finding:** dealers systematically net short calls AND puts
  across all 3 VIX terciles on our signing methodology. Stable mag
  ratios 1.34×–1.49×. This partially counter-evidences Adams 2024 SSRN
  4881008 on our specific subset of order flow. See
  `logs/r0_check3_dealer_sign_result.json`.
- **V2 finding:** Joey's +300% typical winner claim is real:
  unconditional median winner at −40% stop is +378% on 951 days of
  0.20Δ OTM SPXW calls. −40% stop PF 1.28 vs 0.97 no-stop. See
  `logs/v2_joey_payoff_empirical_result.json`.
- **4-tier OOS + bootstrap CI framework** — `scripts/validate_v5.py`,
  `scripts/validate_4tier.py`, `scripts/bootstrap_pf.py` templates.

## External reviews in the trail (do not re-litigate)

- **GPT Pro Rounds 1–5 (Apr 17-18):** killed OI-delta flow proxy,
  warned against "feature search = manufactured alpha" (Round 5).
- **Ultra Review (Apr 19):** 5 ranked amendments, 3-day pre-check
  mandate. See `ARCHITECTURE_R0_REBUILD.md` §1.2 for T_disc addition.
- **GPT Pro Round 6 (Apr 20 evening):** softened strategy_delta §1/§3/§4,
  reordered gates to check0 → check3 → check2 → check1.
- **GPT Pro Round 7 (Apr 21 morning):** post-kill pivot guidance. A3
  archive as default; A2 permitted as one-shot pre-registered pilot.
  Pilot failed; archive executed.

## What to do if user reopens this project

The following questions would need fresh empirical evidence, not
re-running the killed tests:

1. **Futures hedging hypothesis** (GPT Pro Round 7 Q1 rank 2) — requires
   ES minute data we don't have on disk. Would test whether dealer
   short-gamma hedging manifests in ES pin rather than SPX cash pin.
2. **L2 signed aggressor flow** — would require massive.com-tier
   subscription (~$200/mo). Gated behind paper-trade-proven baseline
   edge, which we don't have.
3. **Net-flow-conditioned payoff** — the V2 unconditional baseline
   (9.7% WR, +378% median winner) could be conditioned on an actual
   live flow signal. But this is the same "feature search" Round 5
   forbade; any revival requires a NEW pre-registered pilot spec
   stricter than A2's.

**Do NOT:** re-run R1-R5 under the killed R0 thesis; expand A2 features
after its empirical fail; pivot to another 0DTE variant without
user-explicit reopening.

## How to navigate the docs

1. `docs/R0_RIP_2026_04_21.md` — terminal research artifact (read this first)
2. `docs/validation_summary_2026_04_21.md` — full 10-test empirical trail
3. `docs/peer_bot_extracted_specs.md` — reference-system observations
4. `docs/peer_payoff_model.py` — V2-calibrated executable baseline
5. `docs/r0_post_mortem_2026_04_21.md` — decision-space analysis
6. `docs/strategy_delta_vs_peer.md` — 5 optimization points (all demoted)
7. `HANDOFF.md` — pre-archive operating document (kept for context)
8. `ARCHITECTURE_R0_REBUILD.md` — R0 pre-registration spec (now dead)

## Non-negotiables when editing this repo

- **Do not remove ARCHIVE NOTICE from HANDOFF.md.**
- **Do not re-add peer identity details** (names, university, WeChat
  origins) that were scrubbed for the public release.
- **Do not revive any killed hypothesis without pre-registering a new
  pilot spec** that is strictly stricter than A2's (hard-fail = archive).
- **Do not merge any new code to main without user approval.** Branch
  `feature/0dte-intraday` is the historical research branch; do not
  reuse it for new work.
