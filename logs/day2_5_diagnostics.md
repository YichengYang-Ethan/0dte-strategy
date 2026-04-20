# Day 2.5 Diagnostics — Feature × Label Analysis

Generated: 2026-04-20T10:38:46.849511
Clean rows: 1882

**Purpose**: Before running Day 3 pre-registered baselines, inspect whether
any feature has a non-trivial relationship with the intraday targets.
If zero correlation anywhere → baselines are predicted to fail.

## 1. Feature × Label Correlations (ALL rows, both decision times)

Pearson correlation coefficients. |r| > 0.10 is economically interesting at N ~1900.

| feature              |   signed_ret_pct_r |   signed_ret_pct_p |   abs_ret_pct_r |   abs_ret_pct_p |   realized_var_r |   realized_var_p |
|:---------------------|-------------------:|-------------------:|----------------:|----------------:|-----------------:|-----------------:|
| flow_delta_net_15m   |             0.0017 |             0.9416 |         -0.0617 |          0.0074 |          -0.0297 |           0.1979 |
| flow_delta_net_30m   |             0.0029 |             0.899  |         -0.0578 |          0.0121 |          -0.0402 |           0.0813 |
| flow_gamma_net_15m   |             0.0185 |             0.4218 |         -0.061  |          0.0081 |          -0.037  |           0.1081 |
| flow_gamma_net_30m   |             0.0174 |             0.4494 |         -0.0631 |          0.0062 |          -0.0455 |           0.0486 |
| hhi_30m              |             0.0243 |             0.2927 |         -0.3419 |          0      |          -0.3981 |           0      |
| top1_share_30m       |             0.0207 |             0.3696 |         -0.3025 |          0      |          -0.3323 |           0      |
| top3_share_30m       |             0.0221 |             0.3382 |         -0.3475 |          0      |          -0.3923 |           0      |
| atm_gex_skew         |             0.0278 |             0.2277 |         -0.1613 |          0      |          -0.1355 |           0      |
| atm_gex_total        |             0.0154 |             0.5051 |         -0.2056 |          0      |          -0.2549 |           0      |
| interaction_sign     |            -0.009  |             0.6969 |         -0.0057 |          0.8039 |           0.0039 |           0.8657 |
| interaction_weighted |             0.0027 |             0.9072 |         -0.0324 |          0.1604 |          -0.02   |           0.3859 |

## 2. Spearman Rank Correlations (robust to outliers)

| feature              |   signed_ret_pct_r |   abs_ret_pct_r |   realized_var_r |
|:---------------------|-------------------:|----------------:|-----------------:|
| flow_delta_net_15m   |            -0.0023 |         -0.0698 |          -0.0908 |
| flow_delta_net_30m   |            -0.0037 |         -0.0586 |          -0.0895 |
| flow_gamma_net_15m   |             0.0083 |         -0.0805 |          -0.1134 |
| flow_gamma_net_30m   |             0.0053 |         -0.0716 |          -0.1109 |
| hhi_30m              |            -0.007  |         -0.3715 |          -0.7843 |
| top1_share_30m       |            -0.0036 |         -0.3382 |          -0.7199 |
| top3_share_30m       |            -0.01   |         -0.3714 |          -0.7832 |
| atm_gex_skew         |             0.0413 |         -0.2342 |          -0.4553 |
| atm_gex_total        |            -0.0275 |         -0.2397 |          -0.5716 |
| interaction_sign     |            -0.0012 |         -0.0109 |          -0.0113 |
| interaction_weighted |             0.0124 |         -0.0661 |          -0.1344 |

## 3. Sign Concordance: P(sign(feature) == sign(signed_ret_pct))

50% = random. >52.5% is mild signal on this N.

| feature              |    n |   concordance_pct |
|:---------------------|-----:|------------------:|
| atm_gex_skew         | 1880 |             52.07 |
| flow_delta_net_30m   | 1880 |             51.44 |
| flow_gamma_net_15m   | 1880 |             51.44 |
| flow_delta_net_15m   | 1880 |             51.12 |
| hhi_30m              | 1880 |             51.06 |
| top1_share_30m       | 1880 |             51.06 |
| top3_share_30m       | 1880 |             51.06 |
| atm_gex_total        | 1880 |             51.06 |
| flow_gamma_net_30m   | 1880 |             50.9  |
| interaction_sign     | 1880 |             50.32 |
| interaction_weighted | 1880 |             50.32 |

## 4. Does t=15:00 show stronger signal than t=14:30?

| feature              |   r_at_15:00 |   r_at_14:30 |   delta |
|:---------------------|-------------:|-------------:|--------:|
| flow_delta_net_15m   |       0.0129 |      -0.008  |  0.0049 |
| flow_delta_net_30m   |      -0.0116 |       0.0146 | -0.0031 |
| flow_gamma_net_15m   |       0.0256 |       0.0122 |  0.0134 |
| flow_gamma_net_30m   |       0.0121 |       0.0231 | -0.0111 |
| hhi_30m              |       0.0357 |       0.0199 |  0.0158 |
| top1_share_30m       |       0.0292 |       0.0185 |  0.0106 |
| top3_share_30m       |       0.032  |       0.019  |  0.013  |
| atm_gex_skew         |       0.0297 |       0.027  |  0.0027 |
| atm_gex_total        |       0.0206 |       0.0117 |  0.009  |
| interaction_sign     |       0.0079 |      -0.0233 | -0.0153 |
| interaction_weighted |       0.0198 |      -0.0132 |  0.0066 |

## 5. By-Year Correlation (top 3 features by |r| with signed_ret_pct)


### atm_gex_skew
| Year | n | Pearson r | Sign concordance % |
|------|---|-----------|--------------------|
| 2022 | 250 | +0.0446 | 52.4% |
| 2023 | 496 | +0.0951 | 53.2% |
| 2024 | 498 | +0.0476 | 52.4% |
| 2025 | 492 | +0.0108 | 50.8% |
| 2026 | 146 | +0.0566 | 50.0% |

### flow_delta_net_30m
| Year | n | Pearson r | Sign concordance % |
|------|---|-----------|--------------------|
| 2022 | 250 | -0.0548 | 50.4% |
| 2023 | 496 | +0.0851 | 53.2% |
| 2024 | 498 | +0.0587 | 50.2% |
| 2025 | 492 | -0.0385 | 50.8% |
| 2026 | 146 | -0.0762 | 52.7% |

### flow_gamma_net_15m
| Year | n | Pearson r | Sign concordance % |
|------|---|-----------|--------------------|
| 2022 | 250 | +0.0173 | 53.2% |
| 2023 | 496 | +0.0659 | 53.2% |
| 2024 | 498 | +0.0285 | 49.0% |
| 2025 | 492 | +0.0016 | 50.2% |
| 2026 | 146 | -0.0205 | 54.1% |

## 6. Quintile Analysis — Best Feature by |Pearson r|

Best feature: **atm_gex_skew** (Pearson r = +0.0278)

| Quintile (of best feature) | n | mean signed_ret | mean abs_ret | mean realized_var |
|---|---|---|---|---|
| Q1 (lowest → highest) | 377 | -0.01977 | 0.23231 | 0.000010 |
| Q2 (lowest → highest) | 376 | -0.01516 | 0.25015 | 0.000010 |
| Q3 (lowest → highest) | 376 | +0.00434 | 0.23804 | 0.000010 |
| Q4 (lowest → highest) | 376 | +0.02756 | 0.17496 | 0.000010 |
| Q5 (lowest → highest) | 377 | +0.00465 | 0.11074 | 0.000000 |

## 7. Verdict

- Max |Pearson r| across all (feature, target): **0.0278**
- Best pair: atm_gex_skew vs signed_ret_pct (r=+0.0278)
- Max sign concordance: 52.07% (atm_gex_skew)

**SIGNAL STRENGTH: NONE.** Max correlation below 0.05. Day 3 baselines are predicted to fail at signal identification. The 0DTE intraday thesis as tested is dead at this horizon/feature set.