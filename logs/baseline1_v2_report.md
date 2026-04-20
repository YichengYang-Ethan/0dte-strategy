# Baseline 1 v2 — Rolling Z-score + True Close-to-Close

Generated: 2026-04-20T07:38:31.375304
Evaluation days (after 60d warmup): 920
Threshold: |z| >= 0.5
Rolling window: 60 days, shifted by 1 (strict walk-forward)

## 1. v1 vs v2 Comparison (Vol-signed)
| Version | Signal Spec | Return Spec | N | WR | Mean | Sharpe | PF |
|---------|-------------|-------------|---|-----|------|--------|-----|
| v1 (in-sample z) | year z-score | median-spot return | 575 | 61.4% | +0.199% | 3.41 | 1.82 |
| v1.5 | year z-score | **true close** | 575 | 51.0% | +0.004% | 0.06 | 1.01 |
| v2 (walk-fwd) | **rolling 60d z** | **true close** | 598 | 52.0% | +0.003% | 0.05 | 1.01 |

## 2. Direction Prediction Accuracy
- v1 (year z-score) predictions: **51.7%** correct (920 days)
- v2 (rolling z-score) predictions: **51.8%** correct
- Coin flip: 50%

## 3. Signal Distribution v2
- Long: 303, Short: 295, No signal: 322

## 4. By Year (v2 — rolling z, true close)
| Year | N | WR | Mean | Sharpe | PF |
|------|---|-----|------|--------|-----|
| 2022 | 66 | 56.1% | -0.139% | -1.35 | 0.80 |
| 2023 | 162 | 50.6% | +0.025% | 0.51 | 1.09 |
| 2024 | 162 | 49.4% | +0.010% | 0.19 | 1.03 |
| 2025 | 166 | 53.0% | +0.007% | 0.10 | 1.02 |
| 2026 | 42 | 57.1% | +0.099% | 1.71 | 1.35 |

## 5. Unconditional Baseline (true close-to-close)
- Mean: **+0.059%**
- WR: **55.0%**
- Sharpe: **0.91**

## 6. Verdict
- v1 excess Sharpe over unconditional: **+2.49**
- v2 excess Sharpe over unconditional: **-0.87**

**VERDICT**: After walk-forward + true close, edge collapses to noise. Bulk of v1 Sharpe was in-sample z-score leakage.