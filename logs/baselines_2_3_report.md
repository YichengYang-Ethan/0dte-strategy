# Baselines 2 & 3 — Leak-Safe Falsification Results

Generated: 2026-04-20T08:43:09.863412
Evaluation days: 921
Cutoff: 15:55 ET | Rolling: 60d shift-1 | Threshold: |z| ≥ 0.5

All signal computations use `src/pipeline/leak_safe.py` primitives.

## 1. Summary Table — All Baselines
| Baseline | Signal | N | WR | Dir Acc | Mean | Sharpe | PF | vs Uncond |
|----------|--------|---|-----|---------|------|--------|-----|-----------|
| Unconditional long SPX | — | 921 | 54.8% | 50% | +0.060% | **0.93** | — | 0.00 |
| **B1 v3** signed flow (recap) | quote-rule z-score | 592 | 53.7% | 52.0% | +0.025% | 0.41 | 1.08 | -0.53 |
| **B2** GEX skew (new) | OI×gamma z-score | 540 | 53.0% | 52.1% | -0.013% | **-0.22** | 0.96 | -1.15 |
| **B3** 30-min momentum (new) | spot return z-score | 489 | 46.4% | 48.0% | -0.115% | **-1.59** | 0.75 | -2.53 |

## 2. Baseline 2 (GEX skew) by Year
| Year | N | WR | Mean | Sharpe | PF |
|------|---|-----|------|--------|-----|
| 2022 | 57 | 56.1% | -0.115% | -1.23 | 0.80 |
| 2023 | 166 | 54.8% | +0.030% | 0.55 | 1.09 |
| 2024 | 150 | 51.3% | -0.006% | -0.13 | 0.98 |
| 2025 | 139 | 51.1% | -0.017% | -0.34 | 0.94 |
| 2026 | 28 | 53.6% | -0.067% | -0.94 | 0.85 |

## 3. Baseline 3 (intraday momentum) by Year
| Year | N | WR | Mean | Sharpe | PF |
|------|---|-----|------|--------|-----|
| 2022 | 53 | 35.8% | -0.405% | -4.36 | 0.48 |
| 2023 | 129 | 47.3% | -0.083% | -1.57 | 0.77 |
| 2024 | 137 | 42.3% | -0.075% | -1.37 | 0.80 |
| 2025 | 125 | 52.8% | -0.144% | -1.54 | 0.73 |
| 2026 | 45 | 51.1% | +0.099% | 1.54 | 1.28 |

## 4. Signal Distributions
- B2: Long 264, Short 276, No signal 381
- B3: Long 256, Short 233, No signal 432

## 5. Verdict
- Best signal-strategy Sharpe: **B1 v3** at **0.41**
- Unconditional Sharpe: **0.93**
- Excess over unconditional: **-0.52**

**VERDICT**: None of B1/B2/B3 surpasses unconditional-long by a meaningful margin. All three dumb baselines fail. Revisit thesis OR instrument.