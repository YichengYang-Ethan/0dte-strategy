# Leak-Safe Pipeline Verification Report

Generated: 2026-04-20T08:21:17.939860

## T1: Future-Poison on 10 Stratified Days

**Status**: ✅ PASSED

| date            | flow_passed   | spot_passed   |   orig_flow |   orig_spot |
|:----------------|:--------------|:--------------|------------:|------------:|
| date=2022-07-19 | True          | True          |       59831 |     3934.27 |
| date=2022-11-18 | True          | True          |        9163 |     3957.57 |
| date=2023-06-09 | True          | True          |      -20016 |     4299.29 |
| date=2023-06-08 | True          | True          |       53486 |     4293.81 |
| date=2024-09-12 | True          | True          |       14992 |     5590.04 |
| date=2024-02-01 | True          | True          |       81692 |     4898.82 |
| date=2025-02-06 | True          | True          |       -8877 |     6081.78 |
| date=2025-07-15 | True          | True          |     -159579 |     6251.7  |
| date=2026-03-19 | True          | True          |       26873 |     6605.49 |
| date=2026-03-24 | True          | True          |      -38663 |     6554.45 |

## T2: Cutoff Monotonicity

**Status**: ✅ PASSED

Expected: trade counts monotone non-decreasing, close_spot varies with cutoff

| cutoff   |   n_trades_total |   n_trades_classified |   close_spot |
|:---------|-----------------:|----------------------:|-------------:|
| 10:00    |            52365 |                 22019 |      5286.51 |
| 12:00    |           194695 |                 92852 |      5269.7  |
| 14:00    |           345157 |                165102 |      5259.18 |
| 15:00    |           406272 |                193675 |      5264.99 |
| 15:55    |           469282 |                227085 |      5274.05 |

## T3: Rolling Z-Score Independence from Future

**Status**: ✅ PASSED

- z at t=50 with real future: 1.066041
- z at t=50 with future scrambled: 1.066041

## T4: v3 As-Of Z-Score Recomputation (Truncation Test)

**Status**: ✅ PASSED

Test: for each sample date, recompute z-score using ONLY rows 0..that_date. Must equal stored value.

- 2024-11-25 (idx=574): stored=-0.971208, as-of-recompute=-0.971208, diff=1.11e-16
- 2025-03-12 (idx=645): stored=0.307771, as-of-recompute=0.307771, diff=0.00e+00
- 2023-01-25 (idx=112): stored=1.505289, as-of-recompute=1.505289, diff=2.22e-16

Max diff: 2.22e-16

## T5: Close-Spot Cutoff Discontinuity

**Status**: ✅ PASSED

Expected: close_spot changes across cutoffs (SPX moves intraday)

- @15:50: $5271.63
- @15:54: $5272.67
- @15:55: $5274.05
- @15:58: $5277.70
- @15:59: $5279.37

## Summary

**Overall**: ✅ ALL TESTS PASSED

- T1 Future-poison × 10 days: ✅
- T2 Cutoff monotonicity: ✅
- T3 Rolling z independence: ✅
- T4 v3 aggregate z audit: ✅
- T5 Cutoff discontinuity: ✅

Per GPT Pro Baseline 1 post-mortem, these tests would have caught the
median-spot leakage bug. The verified pipeline is now available for
M4 Baseline 2 (prior-close GEX anchor) and Baseline 3 (intraday momentum).