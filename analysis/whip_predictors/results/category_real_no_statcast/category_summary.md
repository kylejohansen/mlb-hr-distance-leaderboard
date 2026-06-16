# Category Forecasting Post-Run Audit

Source run: `analysis/whip_predictors/results/category_real_no_statcast/`.

This audit parses the completed no-Statcast phased run only. It does not add TC+ work, does not revive the closed Traffic Control branch, and does not run new Statcast, in-season, or rolling-window tests.

## Winner Table

| Category | Best pure model | Best one-number stat | Best public-facing screen | Baseline beaten? | Notes |
|---|---|---|---|---|---|
| Future K/BB | `KBB_reg_component` (1.1940) | `KBB_reg_component` (1.1940) | `KBB_reg_component` (1.1940) | YES vs `raw_KBB_ratio` by 0.0201 | Stable enough as next research direction; component shrinkage narrowly beats CCR/raw K/BB overall. |
| Future WHIP | `KBB_reg_direct` (0.1779) | `KBB_reg_direct` (0.1779) | `KBB_reg_direct` (0.1779) | YES vs `xWHIP_lgBABIP` by 0.0090 | Accuracy winner is regressed command; public screen remains a presentation choice, not a distinct new stat. |
| Future ERA | `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617) | `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617) | `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617) | YES vs `ERA_reg` by 0.0486 | Best pure model and EDF are close; EDF is cleaner as compact public screen. |

## Top Five By Category

### Future K/BB
| Model/stat | wRMSE | RMSE | wMAE | MAE | Pearson | Spearman | OOS R2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `KBB_reg_component` | 1.1940 | 1.3030 | 0.8474 | 0.8973 | 0.462 | 0.487 | 0.256 |
| `CSS` | 1.1948 | 1.3004 | 0.8481 | 0.8899 | 0.465 | 0.486 | 0.255 |
| `KBB_reg_direct` | 1.2111 | 1.3263 | 0.8613 | 0.9222 | 0.435 | 0.455 | 0.234 |
| `CCR_floor` | 1.2131 | 1.3138 | 0.8556 | 0.8924 | 0.448 | 0.454 | 0.232 |
| `CCR` | 1.2134 | 1.3139 | 0.8564 | 0.8928 | 0.448 | 0.454 | 0.231 |

### Future WHIP
| Model/stat | wRMSE | RMSE | wMAE | MAE | Pearson | Spearman | OOS R2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `KBB_reg_direct` | 0.1779 | 0.2002 | 0.1383 | 0.1556 | 0.394 | 0.379 | 0.193 |
| `KBB` | 0.1795 | 0.2020 | 0.1396 | 0.1570 | 0.380 | 0.367 | 0.178 |
| `KBB_reg_component` | 0.1796 | 0.2013 | 0.1390 | 0.1558 | 0.380 | 0.371 | 0.177 |
| `KBB_best_plus_pWHIP_plus_logTBF` | 0.1797 | 0.2013 | 0.1393 | 0.1561 | 0.381 | 0.371 | 0.177 |
| `KBB_best_plus_pWHIP` | 0.1798 | 0.2014 | 0.1392 | 0.1560 | 0.379 | 0.370 | 0.175 |

### Future ERA
| Model/stat | wRMSE | RMSE | wMAE | MAE | Pearson | Spearman | OOS R2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `KBB_best_plus_pWHIP_plus_HR9_reg` | 1.0617 | 1.2151 | 0.8192 | 0.9365 | 0.332 | 0.330 | 0.130 |
| `KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg` | 1.0631 | 1.2168 | 0.8197 | 0.9370 | 0.328 | 0.328 | 0.128 |
| `EDF` | 1.0631 | 1.2168 | 0.8197 | 0.9370 | 0.328 | 0.328 | 0.128 |
| `KBB_reg_best` | 1.0709 | 1.2253 | 0.8207 | 0.9394 | 0.309 | 0.306 | 0.115 |
| `KBB` | 1.0742 | 1.2299 | 0.8232 | 0.9428 | 0.302 | 0.298 | 0.109 |

## Fold-By-Fold Stability

### Future K/BB
- Overall all-pitcher winner: `KBB_reg_component`.
- Held-out-season wins for overall winner: 5/9.
- Excluding 2020 winner: `KBB_reg_component` (unchanged).
- Overall first-to-second wRMSE gap: 0.0008 (mostly technical/narrow).

| Held-out season | Winning model/stat | wRMSE |
|---:|---|---:|
| 2016 | `KBB_reg_component` | 1.2606 |
| 2017 | `KBB_reg_component` | 1.0838 |
| 2018 | `KBB_reg_component` | 1.1706 |
| 2019 | `CCR` | 1.6709 |
| 2020 | `KBB` | 1.2854 |
| 2021 | `KBB_reg_component` | 1.2037 |
| 2022 | `CSS` | 1.2181 |
| 2023 | `raw_KBB_ratio` | 1.1739 |
| 2024 | `KBB_reg_component` | 0.9405 |

### Future WHIP
- Overall all-pitcher winner: `KBB_reg_direct`.
- Held-out-season wins for overall winner: 4/9.
- Excluding 2020 winner: `KBB_reg_direct` (unchanged).
- Overall first-to-second wRMSE gap: 0.0016 (mostly technical/narrow).

| Held-out season | Winning model/stat | wRMSE |
|---:|---|---:|
| 2016 | `KBB_reg_direct` | 0.1717 |
| 2017 | `KBB_reg_direct` | 0.1807 |
| 2018 | `WSI_reg_tuned` | 0.1783 |
| 2019 | `WHIP_reg` | 0.2310 |
| 2020 | `KBB` | 0.1752 |
| 2021 | `KBB_reg_direct` | 0.1823 |
| 2022 | `KBB_best_plus_pWHIP_plus_logTBF` | 0.1765 |
| 2023 | `KBB_reg_direct` | 0.1728 |
| 2024 | `WSI_reg_tuned` | 0.1652 |

### Future ERA
- Overall all-pitcher winner: `KBB_best_plus_pWHIP_plus_HR9_reg`.
- Held-out-season wins for overall winner: 1/9.
- Excluding 2020 winner: `KBB_best_plus_pWHIP_plus_HR9_reg` (unchanged).
- Overall first-to-second wRMSE gap: 0.0014 (mostly technical/narrow).

| Held-out season | Winning model/stat | wRMSE |
|---:|---|---:|
| 2016 | `EDF` | 1.0284 |
| 2017 | `KBB_reg_best` | 1.0631 |
| 2018 | `EDF` | 1.1105 |
| 2019 | `HR9_reg` | 1.4835 |
| 2020 | `EDF` | 0.9782 |
| 2021 | `EDF` | 1.0640 |
| 2022 | `KBB_best_plus_pWHIP_plus_HR9_reg` | 1.0230 |
| 2023 | `KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg` | 1.0046 |
| 2024 | `EDF` | 1.0410 |

## Split Stability

### Future K/BB
| Split | Winner | wRMSE | Top 3 | First-to-second gap |
|---|---|---:|---|---:|
| all | `KBB_reg_component` | 1.1940 | `KBB_reg_component` (1.1940), `CSS` (1.1948), `KBB_reg_direct` (1.2111) | 0.0008 |
| starter | `KBB_reg_component` | 1.0642 | `KBB_reg_component` (1.0642), `CSS` (1.0737), `raw_KBB_ratio` (1.0746) | 0.0095 |
| reliever | `raw_KBB_ratio` | 1.4335 | `raw_KBB_ratio` (1.4335), `CSS` (1.4368), `CCR` (1.4416) | 0.0034 |

### Future WHIP
| Split | Winner | wRMSE | Top 3 | First-to-second gap |
|---|---|---:|---|---:|
| all | `KBB_reg_direct` | 0.1779 | `KBB_reg_direct` (0.1779), `KBB` (0.1795), `KBB_reg_component` (0.1796) | 0.0016 |
| starter | `KBB` | 0.1527 | `KBB` (0.1527), `KBB_reg_direct` (0.1532), `WSI_xWHIP_lgBABIP` (0.1532) | 0.0006 |
| reliever | `KBB_reg_direct` | 0.2189 | `KBB_reg_direct` (0.2189), `KBB` (0.2190), `WSI_xWHIP_lgBABIP` (0.2194) | 0.0001 |

### Future ERA
| Split | Winner | wRMSE | Top 3 | First-to-second gap |
|---|---|---:|---|---:|
| all | `KBB_best_plus_pWHIP_plus_HR9_reg` | 1.0617 | `KBB_best_plus_pWHIP_plus_HR9_reg` (1.0617), `KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg` (1.0631), `EDF` (1.0631) | 0.0014 |
| starter | `KBB_best_plus_pWHIP_plus_HR9_reg` | 0.9357 | `KBB_best_plus_pWHIP_plus_HR9_reg` (0.9357), `KBB` (0.9362), `KBB_reg_best` (0.9370) | 0.0005 |
| reliever | `KBB_best_plus_pWHIP_plus_HR9_reg` | 1.2907 | `KBB_best_plus_pWHIP_plus_HR9_reg` (1.2907), `KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg` (1.2924), `EDF` (1.2924) | 0.0018 |

## Decile / Ranking Checks

Bucket 1 is the best-ranked bucket in this run; bucket 10 is the weakest-ranked bucket. Clean deciles should therefore move from better future outcomes in bucket 1 toward worse future outcomes in bucket 10.

### Future K/BB
- `KBB_reg_component`: monotonic; decile Spearman(bucket, future value) = -1.000; bucket 1 -> 10 future value 4.6247 -> 2.2917; expected pattern: lower future K/BB as rank bucket worsens.

### Future WHIP
- `KBB_reg_direct`: not monotonic (1 reversal(s)); decile Spearman(bucket, future value) = 0.988; bucket 1 -> 10 future value 1.1035 -> 1.3999; expected pattern: higher future WHIP as rank bucket worsens.
- WHIP note: the RMSE winner is an accuracy benchmark, but public-facing ranking is not especially differentiated from K-BB/command screens.

### Future ERA
- `KBB_best_plus_pWHIP_plus_HR9_reg`: not monotonic (1 reversal(s)); decile Spearman(bucket, future value) = 0.988; bucket 1 -> 10 future value 3.3450 -> 4.5464; expected pattern: higher future ERA as rank bucket worsens.
- ERA note: `EDF` is marginally behind the best RMSE model but is cleaner as a named category screen; the gap is only technical.

## Audit Verdict

- Preserve `KBB_reg_component` as the next live research direction for command/K-BB category forecasting.
- Preserve `KBB_reg_direct` as the future-WHIP accuracy benchmark, but do not turn it into a new branded public stat by itself.
- Preserve `EDF` as the most promising compact ERA-facing screen, with the component ERA model kept as the pure accuracy benchmark.
- Do not add TC+ work here. The closed Traffic Control branch stays closed: no quotient TC+, no gamma TC+, no Command+ x Traffic+ quadrant, no Escape Split, and no men-on K-BB production badge.
- This run is stable enough to preserve as the next research direction, but the practical gaps are often narrow. The next step should be product/readability framing around the category winners, not more hidden formula complexity.

## Inputs Audited

- `component_reliability_results.csv`
- `kbb_target_metrics.csv`
- `whip_target_metrics.csv`
- `era_target_metrics.csv`
- `category_metrics.csv`
- `category_predictions.csv`
- `category_decile_results.csv`
- `interpretation.md`

## Verification

- `PYTHONPYCACHEPREFIX=data/cache/pycache .venv/bin/python -m py_compile analysis/whip_predictors/category_forecasting.py analysis/whip_predictors/whip_predictors.py`