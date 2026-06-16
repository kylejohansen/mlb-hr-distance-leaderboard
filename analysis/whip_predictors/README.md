# K-BB Dominance Over WHIP

This project tests which current pitching metrics best predict future WHIP
across complete MLB seasons 2015-2025.

The runner is cache-first:

1. Raw FanGraphs season pitching tables are cached in `data/raw`.
2. Optional pitch-level Statcast pulls are cached by season/date chunk in `data/raw`.
3. Normalized features are written to `data/processed`.
4. Evaluation tables are written to `results`.
5. Plots are written to `plots`.

## Setup

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Quick Validation

Run a synthetic season-level self-test without network access:

```bash
.venv/bin/python analysis/whip_predictors/whip_predictors.py --self-test --bootstrap-reps 0
```

`--self-test` automatically uses a reduced hyperparameter grid so the smoke
test stays quick. It writes synthetic raw inputs to `data/self_test_raw` so it
does not contaminate the real-data cache in `data/raw`. The full run uses the
complete grid from the project spec.

## Full Run

Fetch FanGraphs season data only:

```bash
.venv/bin/python analysis/whip_predictors/whip_predictors.py --fetch --bootstrap-reps 0
```

If FanGraphs blocks the legacy leaderboard endpoint, use MLB Stats API season
pitching totals:

```bash
.venv/bin/python analysis/whip_predictors/whip_predictors.py --fetch --season-source mlb --bootstrap-reps 0
```

Fetch FanGraphs plus Statcast, enabling xWHIP_Statcast, cutoff tests, and
rolling-window tests:

```bash
.venv/bin/python analysis/whip_predictors/whip_predictors.py --fetch --include-statcast --bootstrap-reps 200
```

Rerun from cache only:

```bash
.venv/bin/python analysis/whip_predictors/whip_predictors.py --include-statcast --bootstrap-reps 200
```

Use `--force` to refresh existing cache files.

## Outputs

Each run writes to run-specific directories:

- `results/<run_id>/overall_metrics.csv`
- `results/<run_id>/split_metrics.csv`
- `results/<run_id>/decile_results.csv`
- `results/<run_id>/luck_bucket_results.csv`
- `results/<run_id>/buy_low_sell_high_results.csv`
- `results/<run_id>/hyperparameter_results.csv`
- `results/<run_id>/oos_predictions.csv`
- `results/<run_id>/data_checks.csv`
- `results/<run_id>/statcast_reconciliation.csv`
- `results/<run_id>/sanity_checks.csv`
- `results/<run_id>/rolling_bootstrap_ci.csv`
- `results/<run_id>/run_manifest.json`
- `results/<run_id>/summary_answers.md`
- `plots/<run_id>/scatter_predictor_vs_future_whip.png`
- `plots/<run_id>/decile_future_whip.png`
- `plots/<run_id>/raw_vs_xwsi_rank_change.png`
- `plots/<run_id>/hyperparameter_heatmaps.png`

`results/latest_run.txt` and `plots/latest_run.txt` point to the newest run.
When the platform allows symlinks, `results/latest` and `plots/latest` also
point to the newest run directory.

`results/<run_id>/run_manifest.json` includes the run id, timestamp, git hash
when available, CLI args, self-test flag, seasons, row counts, cache paths,
sanity-check summary, and Statcast reconciliation summary.

`results/<run_id>/summary_answers.md` is generated from the actual run and answers:

- Which single stat best predicts future WHIP?
- Does xWHIP beat WHIP?
- Does WSI_raw beat WHIP?
- Does WSI_xWHIP beat WSI_raw?
- Does WSI_xWHIP beat xWHIP alone?
- Does the simple two-variable model beat the quotient?
- Is the xWHIP adjustment most helpful for BABIP-luck outliers?

## Methodology Notes

Season-to-next-season tests use season `t` to predict WHIP in season `t+1`.
The script reports runs with and without any pair involving 2020.

In-season tests use April 30, May 31, June 30, and July 31 cutoffs. League BABIP
and xWHIP normalization are calculated from data available through the cutoff
only.

Rolling-window tests use:

- first 50 TBF predicts next 100 TBF
- first 100 TBF predicts next 100 TBF
- first 150 TBF predicts next 150 TBF
- first 200 TBF predicts rest of season

Hyperparameters are selected only from prior periods inside each scenario/split:

- `C` for regressed BABIP xWHIP
- `alpha` for blended WHIP/xWHIP denominators
- `lambda`, `alpha`, and `gamma` for tuned WSI

The first available periods may not produce out-of-sample linear-model
predictions because there is no prior training history. They still contribute to
raw feature construction and later rolling validation.

## Data Checks

`results/data_checks.csv` flags meaningful differences between recalculated and
source WHIP, BABIP, K%, and BB%.

`results/<run_id>/statcast_reconciliation.csv` compares Statcast final-PA
pitcher-season aggregates to the season source for K, BB, H, HR, and BBE when
available. Large discrepancies are summarized in the run manifest.

`results/<run_id>/sanity_checks.csv` verifies finite WSI values, plausible
metric ranges, decimal-scale KBB, WSI formula consistency, and player-season
deduplication after trade aggregation.

The runner avoids train/test leakage by:

- selecting hyperparameters from prior periods only
- computing cutoff league averages from current-window data only
- enforcing non-overlap between feature and future windows
- using future IP as the default evaluation weight only after outcomes are set

## Interpreting a Win

A predictor "wins" when it improves out-of-sample future-WHIP prediction on
held-out periods, especially by weighted RMSE and out-of-sample R² versus the
league-average future-WHIP baseline. Correlations are useful, but RMSE answers
the more practical question: how close were the predictions?

Key comparisons:

- `WSI_raw` vs `WHIP`: tests whether strikeout-minus-walk dominance divided by
  current run-prevention traffic beats current WHIP alone.
- `WSI_xWHIP` vs `WSI_raw`: tests whether replacing actual hit traffic with an
  expected-hit denominator improves the quotient.
- `WSI_xWHIP` vs `xWHIP`: tests whether the quotient adds predictive signal
  beyond the xWHIP denominator by itself.
- `WSI_xWHIP` vs `KBB`: tests whether adding the traffic denominator improves
  over strikeout-minus-walk dominance alone.
- `WSI_xWHIP` vs `KBB + xWHIP` model: tests whether the quotient is better than
  a simple two-variable linear model that can weight KBB and xWHIP separately.
- `WSI_reg` variants vs non-regressed variants: tests whether shrinking noisy
  small-sample WHIP and KBB toward training-fold league averages improves
  future-WHIP prediction.

## Category Forecasting Phases

`category_forecasting.py` expands the season-to-next framework into focused
category targets without adding Statcast, in-season, or rolling-window tests.
It preserves the completed baseline conclusion: for future WHIP,
`KBB_reg_tuned` beat WSI variants, while `WSI_raw` beat WHIP and
`WSI_xWHIP` beat `WSI_raw`.

Run a quick self-test:

```bash
.venv/bin/python analysis/whip_predictors/category_forecasting.py --self-test --run-id category_selftest
```

Run the real non-Statcast category framework:

```bash
.venv/bin/python analysis/whip_predictors/category_forecasting.py --fetch --force --season-source mlb --run-id category_real_no_statcast
```

Outputs include:

- `results/<run_id>/component_reliability_results.csv`
- `results/<run_id>/kbb_target_metrics.csv`
- `results/<run_id>/whip_target_metrics.csv`
- `results/<run_id>/era_target_metrics.csv`
- `results/<run_id>/category_decile_results.csv`
- `results/<run_id>/category_bucket_results.csv`
- `results/<run_id>/category_summary.md`
- `results/<run_id>/interpretation.md`
- `plots/<run_id>/category_weighted_rmse.png`
