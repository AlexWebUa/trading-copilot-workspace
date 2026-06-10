# Re-baseline — 2026-06-10 (P0-7)

All rules, walk-forward 70%/30% split, BTCUSDT 1h, 2000 bars.
Cost model: 4 bps fee + 2 bps slippage per side, charged on entry and exit notional.

These are the first numbers produced after the June 2026 fixes (P0-1 forming bar, P0-2 look-ahead, P0-3 detector rewrap, P0-5 CD rewrite, P0-6 cost model). **All earlier backtest results are invalid and not comparable.**

| Rule | Split | Trades | Winrate | Expectancy (R) | PF | Signals | Note |
|---|---|---|---|---|---|---|---|
| fvg_ob_long | IS | 10 | 30.0% | -0.221 | 0.72 | 15 |  |
| fvg_ob_long | OOS | 3 | 0.0% | -1.095 | 0.00 | 7 |  |
| sweep_bos_long | IS | 6 | 0.0% | -1.127 | 0.00 | 11 |  |
| sweep_bos_long | OOS | 1 | 0.0% | +0.390 | 0.00 | 1 |  |
| ob_fvg_short | IS | 2 | 50.0% | -0.015 | 0.97 | 7 |  |
| ob_fvg_short | OOS | 2 | 50.0% | +0.338 | 1.56 | 6 |  |
| ob_in_hvn_long | IS | 0 | 0.0% | +0.000 | 0.00 | 0 | check_ob_in_hvn untested at scale |
| ob_in_hvn_long | OOS | 0 | 0.0% | +0.000 | 0.00 | 0 | check_ob_in_hvn untested at scale |
| poc_discount_bos_long | IS | 2 | 50.0% | -0.287 | 0.64 | 7 |  |
| poc_discount_bos_long | OOS | 2 | 0.0% | +0.371 | 0.00 | 2 |  |
| lvn_acceleration_long | IS | 6 | 16.7% | -0.726 | 0.30 | 6 |  |
| lvn_acceleration_long | OOS | 0 | 0.0% | +0.000 | 0.00 | 0 |  |
| vah_rejection_short | IS | 5 | 20.0% | -0.553 | 0.40 | 18 |  |
| vah_rejection_short | OOS | 2 | 0.0% | -1.180 | 0.00 | 4 |  |
| sweep_cd_manipulation_long | IS | 0 | 0.0% | +0.000 | 0.00 | 2 |  |
| sweep_cd_manipulation_long | OOS | 0 | 0.0% | +0.000 | 0.00 | 0 |  |
| bos_cd_confluence_long | IS | 7 | 28.6% | -0.391 | 0.52 | 12 |  |
| bos_cd_confluence_long | OOS | 1 | 0.0% | +0.390 | 0.00 | 1 |  |
| cd_divergence_ob_short | IS | 5 | 20.0% | -0.567 | 0.39 | 5 |  |
| cd_divergence_ob_short | OOS | 7 | 42.9% | +0.173 | 1.27 | 7 |  |
| sponsored_cd_ob_hvn_long | IS | 0 | 0.0% | +0.000 | 0.00 | 0 | check_cd_absorption (broken thresholds, P2) |
| sponsored_cd_ob_hvn_long | OOS | 0 | 0.0% | +0.000 | 0.00 | 0 | check_cd_absorption (broken thresholds, P2) |
| compression_vp_break_long | IS | 0 | 0.0% | +0.000 | 0.00 | 0 | detect_compression (noise, P2) |
| compression_vp_break_long | OOS | 0 | 0.0% | +0.000 | 0.00 | 0 | detect_compression (noise, P2) |

Notes:
- `Signals` counts condition hits; trades may be fewer (RR filter < 1.0, entry timeout, session filter).
- 0 trades on a rule means its confluence never lined up in this window — an honest null result, not an error.
- Tainted rules depend on detectors still scheduled for rewrite (P2); their numbers carry no evidential weight.