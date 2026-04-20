# Baseline 1: Signed Flow Predictor — Report

Generated: 2026-04-20T07:23:15.234378
Data: 951 days (2022-07-01 → 2026-04-16)
Filter: single-leg electronic only (condition ∈ {0, 18})
Aggressor rule: trade price vs 1-min quote mid
Signal: net signed flow z-score by year, threshold |z| >= 0.5

## 1. Direction Prediction Accuracy (sign test)
- **Volume-signed**: 59.2% correct direction (951 days)
- **Premium-signed**: 56.4% correct direction (951 days)
- (50% = coin flip, need > ~52.5% to be statistically meaningful on this N)

## 2. Trade Performance (when |z| >= threshold)
| Signal | N | WR | Mean/trade | Total | Sharpe | PF |
|--------|---|-----|-----------|-------|--------|-----|
| Vol-signed | 588 | 61.4% | +0.202% | +118.64% | 3.45 | 1.83 |
| Premium-signed | 561 | 59.9% | +0.174% | +97.59% | 2.75 | 1.62 |

## 3. By Year (vol-signed)
| Year | N | WR | Mean/trade | Total | Sharpe | PF |
|------|---|-----|-----------|-------|--------|-----|
| 2022 | 80 | 56.2% | +0.105% | +8.40% | 1.23 | 1.21 |
| 2023 | 156 | 67.3% | +0.292% | +45.58% | 6.52 | 3.02 |
| 2024 | 157 | 58.6% | +0.182% | +28.58% | 3.61 | 1.87 |
| 2025 | 155 | 60.0% | +0.154% | +23.93% | 2.51 | 1.61 |
| 2026 | 40 | 65.0% | +0.304% | +12.15% | 5.35 | 2.38 |

## 4. By IV Regime (vol-signed)
| Regime | N | WR | Mean/trade | Total | Sharpe | PF |
|--------|---|-----|-----------|-------|--------|-----|
| low_vol | 197 | 62.9% | +0.144% | +28.30% | 4.11 | 2.01 |
| mid_vol | 203 | 61.1% | +0.235% | +47.71% | 4.97 | 2.25 |
| high_vol | 188 | 60.1% | +0.227% | +42.63% | 2.71 | 1.56 |

## 5. Sensitivity: Exclude Tariff Shock 2025-04-07..10
(4 days removed, remaining: 947)
| Sample | N | WR | Mean/trade | Total | Sharpe | PF |
|--------|---|-----|-----------|-------|--------|-----|
| full | 588 | 61.4% | +0.202% | +118.64% | 3.45 | 1.83 |
| excl. tariff | 588 | 61.4% | +0.202% | +118.64% | 3.45 | 1.83 |

## 6. Unconditional Baseline (always long SPX)
- Mean next-day return: **+0.071%**
- WR: **54.3%**
- Sharpe: **1.20**

## 7. Signal Distribution
- Days signal fires long: **296**
- Days signal fires short: **292**
- Days no signal: **363**

## 8. Verdict
- Direction accuracy edge over coin flip: **+9.20 pp**
- Mean trade return (filtered): **+0.202%**
- **VERDICT: Weak but plausible edge. Proceed to bootstrap CI + walk-forward.**