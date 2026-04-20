# Day 2 Intraday Features — MVP Plan

Generated: 2026-04-20T10:36:38.937482
Days × decision times: 1904
Features extracted: 30

## Feature columns
| Family | Columns |
|--------|---------|
| F1 flow (×15m,30m) | flow_delta_call, flow_delta_put, flow_delta_net, flow_gamma_call, flow_gamma_put, flow_gamma_net, n_trades |
| F2 concentration | hhi, top1_share, top3_share, n_strikes |
| F3 slow state | atm_call_gex, atm_put_gex, atm_gex_skew, atm_gex_total, spot_t |
| F4 interaction | interaction_sign, interaction_weighted |

## Primary (t=15:00) feature distribution
- **flow_delta_net_30m**: mean=326, std=4245, min=-2.131e+04, max=1.812e+04
- **flow_gamma_net_30m**: mean=25.68, std=319.7, min=-2034, max=1337
- **hhi_30m**: mean=0.1013, std=0.04183, min=0.02606, max=0.2672
- **top1_share_30m**: mean=0.1697, std=0.06173, min=0.05108, max=0.4954
- **top3_share_30m**: mean=0.4298, std=0.1396, min=0.1476, max=0.8044
- **atm_gex_skew**: mean=3.626e+11, std=1.777e+12, min=-1.132e+13, max=2.433e+13
- **interaction_sign**: mean=0.1418, std=0.9846, min=-1, max=1
- **interaction_weighted**: mean=0.4921, std=3.378, min=-6.047, max=6.831

## Coverage
- Days processed: 952
- Rows for t=15:00: 952
- Rows for t=14:30: 952
- Missing F1 flow_delta_net_30m: 9
- Missing F2 hhi_30m: 9
- Missing F3 atm_gex_skew: 2

## Sample (first 3 days, t=15:00)
| date                |   spot_t |   flow_delta_net_30m |   top3_share_30m |   atm_gex_skew |   interaction_sign |
|:--------------------|---------:|---------------------:|-----------------:|---------------:|-------------------:|
| 2022-07-01 00:00:00 |  3812.3  |              1064.6  |         0.291245 |   -1.35523e+10 |                 -1 |
| 2022-07-05 00:00:00 |  3812.01 |              1034.54 |         0.319635 |   -8.80749e+09 |                 -1 |
| 2022-07-06 00:00:00 |  3857.67 |              1904.87 |         0.287609 |    3.36843e+11 |                  1 |
