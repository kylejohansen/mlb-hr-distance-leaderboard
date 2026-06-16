# Category Forecasting Summary

## Run Notes
- Season-to-next-season only; no Statcast, in-season, or rolling-window expansion in this phased run.
- Prior WHIP baseline preserved: KBB_reg_tuned beat WSI variants in real_no_statcast_bootstrap50.

## Executive Summary

Best future K/BB model: `KBB_reg_component` (1.1940).
Best future WHIP model: `KBB_reg_direct` (0.1779).
Best future ERA model: `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617).

The reusable component approach is promising for K/BB and ERA, but the WHIP result still confirms the earlier baseline: regressed command alone is very hard to beat.

## Component Regression Choices

- K%/BB% component: most often selected `C_K=1000.0` and `C_BB=300.0`.
- Direct KBB regression: most common `C_KBB=1000.0`.
- WHIP regression: most common `C_WHIP_IP=150.0`.
- pWHIP blend: most common `alpha=0.4`.
- WAI command penalty: most common `beta=2.0`.
- HR damage regression: most common `C_HR_BIP=1500.0`.
- ERA regression: most common `C_ERA_IP=150.0`.

## Phase Answers

1. Component winners: `KBB_reg_component` led future K/BB (1.1940), `KBB_reg_direct` led future WHIP (0.1779), and `KBB_best_plus_pWHIP_plus_HR9_reg` led future ERA (1.0617).
2. CCR vs raw K/BB and K-BB%: CCR (1.2134) narrowly beat raw K/BB (1.2141) and K-BB% (1.2278), but `KBB_reg_component` was better than CCR.
3. WAI vs KBB_reg for WHIP: no. WAI (0.1838) trailed both `KBB_reg_direct` (0.1779) and `KBB_reg_component` (0.1796).
4. EDF vs ERA_reg and KBB_reg for ERA: yes. EDF (1.0631) beat ERA_reg (1.1103) and KBB_reg_best (1.0709), though the simpler `KBB_best + pWHIP + HR9_reg` model was slightly better (1.0617).
5. Best pure model by category: K/BB = `KBB_reg_component`; WHIP = `KBB_reg_direct`; ERA = `KBB_best_plus_pWHIP_plus_HR9_reg`.
6. Best simple public screen by category: K/BB = `KBB_reg_component`; WHIP = `KBB_reg_direct` for accuracy or `WSI_reg_tuned` for a ratio-style screen; ERA = `EDF` as a compact category-specific screen.
7. Original WSI role: still useful as a WHIP/fantasy screen because xWSI and regressed WSI beat WHIP, but it is not the best pure predictor when regressed command is available.

## Split Summary

- Future K/BB: all = `KBB_reg_component` (1.1940); starters = `KBB_reg_component` (1.0642); relievers = `raw_KBB_ratio` (1.4335).
- Future WHIP: all = `KBB_reg_direct` (0.1779); starters = `KBB` (0.1527); relievers = `KBB_reg_direct` (0.2189).
- Future ERA: all = `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617); starters = `KBB_best_plus_pWHIP_plus_HR9_reg` (0.9357); relievers = `KBB_best_plus_pWHIP_plus_HR9_reg` (1.2907).

Reliever K/BB was the main exception to the all-pitcher pattern: raw K/BB led that split, suggesting the component shrinkage may be too conservative for some reliever-only K/BB ranking use cases.

## Category Leaderboards

### KBB

| model | weighted RMSE | Pearson | OOS R2 |
|---|---:|---:|---:|
| `KBB_reg_component` | 1.1940 | 0.462 | 0.256 |
| `CSS` | 1.1948 | 0.465 | 0.255 |
| `KBB_reg_direct` | 1.2111 | 0.435 | 0.234 |
| `CCR_floor` | 1.2131 | 0.448 | 0.232 |
| `CCR` | 1.2134 | 0.448 | 0.231 |
| `raw_KBB_ratio` | 1.2141 | 0.455 | 0.231 |
| `KBB` | 1.2278 | 0.418 | 0.213 |
| `K_pct` | 1.2954 | 0.309 | 0.124 |

### WHIP

| model | weighted RMSE | Pearson | OOS R2 |
|---|---:|---:|---:|
| `KBB_reg_direct` | 0.1779 | 0.394 | 0.193 |
| `KBB` | 0.1795 | 0.380 | 0.178 |
| `KBB_reg_component` | 0.1796 | 0.380 | 0.177 |
| `KBB_best_plus_pWHIP_plus_logTBF` | 0.1797 | 0.381 | 0.177 |
| `KBB_best_plus_pWHIP` | 0.1798 | 0.379 | 0.175 |
| `WSI_reg_tuned` | 0.1799 | 0.377 | 0.175 |
| `WSI_xWHIP_lgBABIP` | 0.1801 | 0.377 | 0.173 |
| `xWAI_ratio` | 0.1803 | 0.375 | 0.171 |

### ERA

| model | weighted RMSE | Pearson | OOS R2 |
|---|---:|---:|---:|
| `KBB_best_plus_pWHIP_plus_HR9_reg` | 1.0617 | 0.332 | 0.130 |
| `KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg` | 1.0631 | 0.328 | 0.128 |
| `EDF` | 1.0631 | 0.328 | 0.128 |
| `KBB_reg_best` | 1.0709 | 0.309 | 0.115 |
| `KBB` | 1.0742 | 0.302 | 0.109 |
| `HR9_reg` | 1.0769 | 0.304 | 0.105 |
| `EDF_z` | 1.0787 | 0.298 | 0.102 |
| `WAI` | 1.0972 | 0.251 | 0.071 |

## Baseline WSI Conclusion
Preserved: the prior real no-Statcast run found `KBB_reg_tuned` was the best one-number future-WHIP predictor. `WSI_raw` beat WHIP and `WSI_xWHIP` beat `WSI_raw`, but WSI variants did not beat regressed K-BB%.

## Recommendation

- Publish `KBB_reg_component` for command/K-BB category forecasting.
- Keep `KBB_reg_direct` as the best future-WHIP accuracy benchmark.
- Use `WSI_reg_tuned` or xWSI-style ratios as public-facing WHIP screens, not as the pure projection leader.
- Use `EDF` as the compact ERA screen, while noting the best pure ERA model is the simple component model `KBB_best + pWHIP + HR9_reg`.

## Component Choices

| component | target | folds |
|---|---|---:|
| `EDF` | `future_era` | 48 |
| `ERA_reg` | `future_era` | 48 |
| `HR9_reg` | `future_era` | 48 |
| `KBB_reg_best` | `future_kbb_ratio` | 48 |
| `KBB_reg_component` | `future_kbb_ratio` | 48 |
| `KBB_reg_direct` | `future_kbb_ratio` | 48 |
| `WAI_beta` | `future_whip` | 48 |
| `WHIP_reg` | `future_whip` | 48 |
| `pWHIP` | `future_whip` | 48 |
