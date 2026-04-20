# Day 3 Baselines — MVP Plan (post-Day-2.5 verdict)

Generated: 2026-04-20T11:07:11.145280
Decision time: 15:00 (primary)
Evaluation rows: 892 (2022-09-27 → 2026-04-17)
Rolling z-score warmup: 60 days (trailing, shift-1)
Multiple-testing family: Bonferroni, N = 12

## GPT Pro Day 2.5 verdict applied
- **Direction branch = CONFIRMATORY falsification** (original pre-registration).
- **Volatility branch = EXPLORATORY** (target choice data-contingent after diagnostic peek).
- Full 12-test Bonferroni correction applied across both branches.
- Primary volatility target: `realized_var`.  Robustness: `abs_ret_pct`.
- All V1-V3 must beat **V4 persistence** in incremental R² to be interesting.

## BRANCH A — Direction (CONFIRMATORY)

Target: `signed_ret_pct`.  Metric: sign concordance vs 50% random.
Baselines are run exactly as pre-registered in MVP plan; these are expected to
fail per Day 2.5 diagnostic (max concordance 52.07%).

| baseline       |   concordance_pct |   n |   p_raw |   p_bonf_12 |   sharpe_annual |
|:---------------|------------------:|----:|--------:|------------:|----------------:|
| B1_flow_only   |             50.68 | 882 |  0.3556 |           1 |          -0.026 |
| B2_state_only  |             52.39 | 880 |  0.0835 |           1 |           0.94  |
| B3_interaction |             51.82 | 880 |  0.148  |           1 |           0.412 |
| B4_inverse_B3  |             48.18 | 880 |  0.867  |           1 |          -0.412 |

### By-year concordance

- **B1_flow_only**: {2022: np.float64(42.42), 2023: np.float64(50.0), 2024: np.float64(49.8), 2025: np.float64(54.07), 2026: np.float64(52.05)}
- **B2_state_only**: {2022: np.float64(52.31), 2023: np.float64(56.05), 2024: np.float64(50.2), 2025: np.float64(51.02), 2026: np.float64(52.05)}
- **B3_interaction**: {2022: np.float64(53.85), 2023: np.float64(50.4), 2024: np.float64(51.81), 2025: np.float64(53.06), 2026: np.float64(50.68)}
- **B4_inverse_B3**: {2022: np.float64(46.15), 2023: np.float64(49.6), 2024: np.float64(48.19), 2025: np.float64(46.94), 2026: np.float64(49.32)}

## BRANCH B — Volatility (EXPLORATORY)

Targets: `realized_var` (primary), `abs_ret_pct` (robustness).
Reporting as exploratory per GPT Pro verdict. V4 persistence is the
sanity floor: V1-V3 must add incremental R² > 0 over persistence alone.

| baseline          | target               |   n |   pearson_r |   spearman_r |   p_raw |   p_bonf_12 |   q1_mean |   q5_mean |   q5_q1_spread | monotonic   |   delta_r2_vs_persistence |
|:------------------|:---------------------|----:|------------:|-------------:|--------:|------------:|----------:|----------:|---------------:|:------------|--------------------------:|
| V4_persistence    | realized_var_primary | 892 |      0.706  |       0.8052 |  0      |      0      |  2e-06    |  1.9e-05  |       1.7e-05  | True        |                   0       |
| V4_persistence    | abs_ret_pct_robust   | 892 |      0.329  |       0.3881 |  0      |      0      |  0.093293 |  0.33078  |       0.237487 | True        |                   0       |
| V1_state_only     | realized_var_primary | 890 |     -0.1323 |      -0.3453 |  0.0001 |      0.0009 |  7e-06    |  3e-06    |      -4e-06    | False       |                   0.00781 |
| V1_state_only     | abs_ret_pct_robust   | 890 |     -0.1265 |      -0.1743 |  0.0002 |      0.0019 |  0.194362 |  0.126645 |      -0.067717 | False       |                   0.01359 |
| V2_flow_magnitude | realized_var_primary | 883 |     -0.1365 |      -0.1522 |  0      |      0.0006 |  1.2e-05  |  5e-06    |      -7e-06    | True        |                   0.00265 |
| V2_flow_magnitude | abs_ret_pct_robust   | 883 |     -0.1025 |      -0.0865 |  0.0023 |      0.0275 |  0.238349 |  0.159371 |      -0.078978 | False       |                   0.00401 |
| V3_interaction    | realized_var_primary | 883 |      0.0033 |      -0.1097 |  0.923  |      1      |  4e-06    |  3e-06    |      -1e-06    | False       |                   0       |
| V3_interaction    | abs_ret_pct_robust   | 883 |      0.0018 |      -0.0273 |  0.9581 |      1      |  0.127977 |  0.108535 |      -0.019443 | False       |                   0       |

## Verdict

**Direction branch:**
- Max concordance: 52.39% (50% = random)
- Max |Sharpe|: 0.94
- Verdict: **DEAD** (no baseline > 55% concordance or |Sharpe| > 0.5 after Bonferroni)

**Volatility branch (EXPLORATORY):**
- Best feature: V1_state_only vs realized_var_primary
- Incremental R² over persistence: 0.00781
- Pearson r: -0.1323  | p_bonf_12: 0.0009
- Q5–Q1 spread: -4e-06  | monotonic: False

- Verdict: **WORTH DAY 4 PLUMBING CHECK** (adds R² over persistence, exploratory flag)
