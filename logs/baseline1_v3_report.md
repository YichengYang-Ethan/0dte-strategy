# Baseline 1 v3 — Leak-Safe Rebuild

Generated: 2026-04-20T08:14:17.185449
Evaluation days: 921
Signal cutoff: 15:55 ET
Rolling window: 60d, shift-1 (strict walk-forward)
Threshold: |z| >= 0.5
Filter: condition ∈ {0, 18} (single-leg electronic)

All computations verified via `future_poison_test` — post-cutoff data has zero influence.

## 1. Sharpe Evolution (vol-signed, long+short signal)
| Version | Signal | Return | N | WR | Mean | Sharpe | PF |
|---------|--------|--------|---|-----|------|--------|-----|
| v1 | year z | median-spot | 575 | 61.4% | +0.199% | **3.41** | 1.82 |
| v1.5 | year z | true close | 575 | 51.0% | +0.004% | 0.06 | 1.01 |
| v2 | rolling z 60d | true close (no cutoff) | 598 | 52.0% | +0.003% | 0.05 | 1.01 |
| **v3 (leak-safe)** | **rolling z 60d shift-1** | **true close @ 15:55** | 592 | 53.7% | +0.025% | **0.41** | 1.08 |

## 2. Direction Accuracy
- v3 direction accuracy: **52.0%** (coin flip = 50%)

## 3. By Year (v3)
| Year | N | WR | Mean | Sharpe | PF |
|------|---|-----|------|--------|-----|
| 2022 | 65 | 61.5% | -0.141% | -1.36 | 0.79 |
| 2023 | 159 | 53.5% | +0.067% | 1.41 | 1.26 |
| 2024 | 161 | 50.9% | +0.032% | 0.63 | 1.11 |
| 2025 | 166 | 52.4% | +0.019% | 0.30 | 1.06 |
| 2026 | 41 | 58.5% | +0.126% | 2.11 | 1.46 |

## 4. Unconditional Baseline (always long SPX, true close-to-close)
- Mean: +0.060%/day
- WR: 54.8%
- Sharpe: **0.93**

## 5. Signal Distribution v3
- Long: 297, Short: 295, No signal: 329

## 6. Premium-signed variant (v3)
- N=567, WR=54.5%, mean=-0.004%, Sharpe=-0.06

## 7. Verdict
- v3 Sharpe: **0.41**
- Unconditional Sharpe: **0.93**
- Excess: **-0.53**

**VERDICT**: No meaningful excess edge over unconditional long SPX. Signal isn't useful.