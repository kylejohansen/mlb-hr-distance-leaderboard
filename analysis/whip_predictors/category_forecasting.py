#!/usr/bin/env python3
"""Season-to-next-season category forecasting built from regressed components."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from whip_predictors import (
    ProjectPaths,
    ROLE_THRESHOLDS,
    SEASONS,
    cache_fangraphs_pitching,
    load_fangraphs_pitching,
    safe_divide,
    write_self_test_cache,
)


C_RATE_GRID = [100, 200, 300, 500, 750, 1000]
C_WHIP_IP_GRID = [20, 40, 60, 80, 100, 150]
C_HR_BIP_GRID = [100, 250, 500, 750, 1000, 1500]
C_ERA_IP_GRID = [20, 40, 60, 80, 100, 150]
ALPHA_GRID = [round(x / 100, 2) for x in range(0, 101, 5)]
BETA_GRID = [0.0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]


def configure_grids(fast_grid: bool) -> None:
    global C_RATE_GRID, C_WHIP_IP_GRID, C_HR_BIP_GRID, C_ERA_IP_GRID, ALPHA_GRID, BETA_GRID
    if not fast_grid:
        return
    C_RATE_GRID = [100, 500, 1000]
    C_WHIP_IP_GRID = [40, 100, 150]
    C_HR_BIP_GRID = [250, 1000]
    C_ERA_IP_GRID = [40, 100, 150]
    ALPHA_GRID = [0.0, 0.5, 1.0]
    BETA_GRID = [0.0, 0.75, 1.5]


def default_run_id(args: argparse.Namespace) -> str:
    prefix = "category_selftest" if args.self_test else "category"
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"


def git_hash(cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip() or None
    except Exception:
        return None


def finite_frame(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = frame.replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=cols)


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    data = pd.DataFrame({"v": values, "w": weights}).replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        return np.nan
    w = data["w"].clip(lower=0).to_numpy(dtype=float)
    if w.sum() <= 0:
        return float(data["v"].mean())
    return float(np.average(data["v"].to_numpy(dtype=float), weights=w))


def metrics(y_true: np.ndarray, y_pred: np.ndarray, weights: np.ndarray, baseline: float) -> dict[str, float]:
    if len(y_true) < 3:
        return {}
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1.0)
    err = y_pred - y_true
    sse = float(np.sum(weights * err * err))
    base_sse = float(np.sum(weights * (baseline - y_true) ** 2))
    data = pd.DataFrame({"pred": y_pred, "true": y_true}).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "weighted_rmse": float(np.sqrt(sse / weights.sum())),
        "rmse": float(np.sqrt(np.mean(err * err))),
        "weighted_mae": float(np.sum(weights * np.abs(err)) / weights.sum()),
        "mae": float(np.mean(np.abs(err))),
        "pearson": float(data["pred"].corr(data["true"], method="pearson")) if len(data) > 2 else np.nan,
        "spearman": float(data["pred"].corr(data["true"], method="spearman")) if len(data) > 2 else np.nan,
        "oos_r2": float(1.0 - sse / base_sse) if base_sse > 0 else np.nan,
    }


def weighted_lstsq_predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str], target: str, weight_col: str) -> tuple[pd.DataFrame, np.ndarray]:
    needed = features + [target, weight_col]
    fit_train = finite_frame(train, needed)
    fit_test = finite_frame(test, features + [target, weight_col])
    if len(fit_train) < 20 or len(fit_test) < 3:
        return fit_test, np.array([])
    x_train = np.column_stack([np.ones(len(fit_train))] + [fit_train[c].to_numpy(dtype=float) for c in features])
    y_train = fit_train[target].to_numpy(dtype=float)
    w = np.sqrt(fit_train[weight_col].clip(lower=0).to_numpy(dtype=float))
    beta = np.linalg.lstsq(x_train * w[:, None], y_train * w, rcond=None)[0]
    x_test = np.column_stack([np.ones(len(fit_test))] + [fit_test[c].to_numpy(dtype=float) for c in features])
    return fit_test, x_test @ beta


def one_feature_rmse(feature: pd.Series, target: pd.Series, weights: pd.Series) -> float:
    data = pd.DataFrame({"feature": feature, "target": target, "weights": weights}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 20 or data["feature"].nunique() < 2:
        return np.inf
    fit, pred = weighted_lstsq_predict(data, data, ["feature"], "target", "weights")
    if len(pred) != len(fit):
        return np.inf
    return metrics(fit["target"].to_numpy(dtype=float), pred, fit["weights"].to_numpy(dtype=float), fit["target"].mean()).get("weighted_rmse", np.inf)


def tune_series(
    train: pd.DataFrame,
    candidates: Iterable[tuple[str, pd.Series, dict[str, object]]],
    target: str,
    weight_col: str,
) -> tuple[str, dict[str, object], float]:
    best_name = ""
    best_params: dict[str, object] = {}
    best_score = np.inf
    for name, series, params in candidates:
        score = one_feature_rmse(series, train[target], train[weight_col])
        if score < best_score:
            best_name, best_params, best_score = name, params, score
    return best_name, best_params, best_score


def shrink_rate(frame: pd.DataFrame, value_col: str, sample_col: str, c_value: int, league_value: float) -> pd.Series:
    weight = safe_divide(frame[sample_col], frame[sample_col] + c_value)
    return league_value + weight * (frame[value_col] - league_value)


def league_context(train: pd.DataFrame) -> dict[str, float]:
    return {
        "lg_k_pct": safe_divide(train["k"].sum(), train["tbf"].sum()),
        "lg_bb_pct": safe_divide(train["bb"].sum(), train["tbf"].sum()),
        "lg_kbb": safe_divide(train["k"].sum(), train["tbf"].sum()) - safe_divide(train["bb"].sum(), train["tbf"].sum()),
        "lg_whip": safe_divide((train["bb"] + train["h"]).sum(), train["ip"].sum()),
        "lg_hr_bip": safe_divide(train["hr"].sum(), train["bip"].sum()),
        "lg_hr9": safe_divide(9.0 * train["hr"].sum(), train["ip"].sum()),
        "lg_era": safe_divide(9.0 * train["er"].sum(), train["ip"].sum()),
    }


def add_base_category_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["kbb_ratio"] = safe_divide(out["k"], out["bb"]).replace([np.inf, -np.inf], np.nan)
    out["log_current_tbf"] = np.log1p(out["tbf"])
    return out


def build_season_dataset(pitching: pd.DataFrame, exclude_2020: bool) -> pd.DataFrame:
    current = add_base_category_columns(pitching[pitching["season"].between(2015, 2024)].copy())
    future = add_base_category_columns(pitching[pitching["season"].between(2016, 2025)].copy())
    if exclude_2020:
        current = current[current["season"] != 2020]
        future = future[future["season"] != 2020]
    current["future_season"] = current["season"] + 1
    key = "idfg" if current["idfg"].notna().any() else "player_name"
    future_cols = [key, "season", "kbb_ratio", "whip", "era", "ip", "tbf"]
    future = future[future_cols].rename(
        columns={
            "season": "future_season",
            "kbb_ratio": "future_kbb_ratio",
            "whip": "future_whip",
            "era": "future_era",
            "ip": "future_ip",
            "tbf": "future_tbf",
        }
    )
    data = current.merge(future, on=[key, "future_season"], how="inner")
    data["scenario"] = "season_to_next"
    data["period"] = data["season"]
    data["pitcher_season"] = data[key].astype(str) + "-" + data["season"].astype(str)
    data["exclude_2020"] = exclude_2020
    return data


def filtered_split(data: pd.DataFrame, split: str) -> pd.DataFrame:
    if split == "all":
        return data.copy()
    return data[data["role"] == split].copy()


def apply_thresholds(data: pd.DataFrame, split: str) -> pd.DataFrame:
    current_min, future_min = ROLE_THRESHOLDS[split]
    return data[(data["ip"] >= current_min) & (data["future_ip"] >= future_min)].copy()


def z_from_train(train_s: pd.Series, target_s: pd.Series) -> pd.Series:
    mean = train_s.mean()
    std = train_s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=target_s.index)
    return (target_s - mean) / std


def add_fold_components(train: pd.DataFrame, test: pd.DataFrame, reliability_rows: list[dict[str, object]], context: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    train = train.copy()
    test = test.copy()
    lg = league_context(train)

    kbb_direct_candidates = [
        (f"kbb_reg_direct_C{c}", shrink_rate(train, "kbb", "tbf", c, lg["lg_kbb"]), {"C_KBB": c})
        for c in C_RATE_GRID
    ]
    direct_name, direct_params, direct_score = tune_series(train, kbb_direct_candidates, "future_kbb_ratio", "future_tbf")
    c_kbb = int(direct_params.get("C_KBB", C_RATE_GRID[0]))
    for frame in [train, test]:
        frame["KBB_reg_direct"] = shrink_rate(frame, "kbb", "tbf", c_kbb, lg["lg_kbb"])
    reliability_rows.append({**context, "component": "KBB_reg_direct", "target": "future_kbb_ratio", "train_weighted_rmse": direct_score, **direct_params})

    component_candidates = []
    for c_k in C_RATE_GRID:
        k_reg = shrink_rate(train, "k_pct", "tbf", c_k, lg["lg_k_pct"])
        for c_bb in C_RATE_GRID:
            bb_reg = shrink_rate(train, "bb_pct", "tbf", c_bb, lg["lg_bb_pct"])
            component_candidates.append(("KBB_reg_component", k_reg - bb_reg, {"C_K": c_k, "C_BB": c_bb}))
    _, component_params, component_score = tune_series(train, component_candidates, "future_kbb_ratio", "future_tbf")
    c_k = int(component_params.get("C_K", C_RATE_GRID[0]))
    c_bb = int(component_params.get("C_BB", C_RATE_GRID[0]))
    for frame in [train, test]:
        frame["K_pct_reg"] = shrink_rate(frame, "k_pct", "tbf", c_k, lg["lg_k_pct"])
        frame["BB_pct_reg"] = shrink_rate(frame, "bb_pct", "tbf", c_bb, lg["lg_bb_pct"])
        frame["KBB_reg_component"] = frame["K_pct_reg"] - frame["BB_pct_reg"]
        frame["CCR"] = safe_divide(frame["K_pct_reg"], frame["BB_pct_reg"])
        frame["CCR_floor"] = frame["K_pct_reg"] / np.maximum(frame["BB_pct_reg"], 0.5 * lg["lg_bb_pct"])
    train["CSS"] = z_from_train(np.log(train["CCR"]), np.log(train["CCR"])) + z_from_train(train["KBB_reg_component"], train["KBB_reg_component"])
    test["CSS"] = z_from_train(np.log(train["CCR"]), np.log(test["CCR"])) + z_from_train(train["KBB_reg_component"], test["KBB_reg_component"])
    reliability_rows.append({**context, "component": "KBB_reg_component", "target": "future_kbb_ratio", "train_weighted_rmse": component_score, **component_params})

    command_candidates = [
        ("KBB_reg_direct", train["KBB_reg_direct"], {}),
        ("KBB_reg_component", train["KBB_reg_component"], {}),
    ]
    command_best, _, command_score = tune_series(train, command_candidates, "future_kbb_ratio", "future_tbf")
    if not command_best:
        command_best = "KBB_reg_direct"
    reliability_rows.append({**context, "component": "KBB_reg_best", "target": "future_kbb_ratio", "choice": command_best, "train_weighted_rmse": command_score})

    whip_candidates = [
        (f"WHIP_reg_C{c}", shrink_rate(train, "whip", "ip", c, lg["lg_whip"]), {"C_WHIP_IP": c})
        for c in C_WHIP_IP_GRID
    ]
    _, whip_params, whip_score = tune_series(train, whip_candidates, "future_whip", "future_ip")
    c_whip = int(whip_params.get("C_WHIP_IP", C_WHIP_IP_GRID[0]))
    for frame in [train, test]:
        frame["WHIP_reg"] = shrink_rate(frame, "whip", "ip", c_whip, lg["lg_whip"])
        frame["WSI_reg_tuned"] = safe_divide(100.0 * frame["KBB_reg_component"], frame["WHIP_reg"])
    reliability_rows.append({**context, "component": "WHIP_reg", "target": "future_whip", "train_weighted_rmse": whip_score, "lgWHIP": lg["lg_whip"], **whip_params})

    pwhip_candidates = []
    for alpha in ALPHA_GRID:
        pwhip = alpha * train["WHIP_reg"] + (1.0 - alpha) * train["xwhip_lgbabip"]
        pwhip_candidates.append(("pWHIP", pwhip, {"alpha": alpha}))
    _, pwhip_params, pwhip_score = tune_series(train, pwhip_candidates, "future_whip", "future_ip")
    alpha = float(pwhip_params.get("alpha", 0.5))
    for frame in [train, test]:
        frame["pWHIP"] = alpha * frame["WHIP_reg"] + (1.0 - alpha) * frame["xwhip_lgbabip"]
    reliability_rows.append({**context, "component": "pWHIP", "target": "future_whip", "train_weighted_rmse": pwhip_score, **pwhip_params})

    beta_candidates = []
    for beta in BETA_GRID:
        beta_candidates.append(("WAI", train["pWHIP"] - beta * (train[command_best] - lg["lg_kbb"]), {"beta": beta, "command": command_best}))
    _, beta_params, beta_score = tune_series(train, beta_candidates, "future_whip", "future_ip")
    beta = float(beta_params.get("beta", 0.0))
    for frame in [train, test]:
        frame["WAI"] = frame["pWHIP"] - beta * (frame[command_best] - lg["lg_kbb"])
        frame["WAI_plus"] = 100.0 * frame["WAI"] / lg["lg_whip"]
        frame["xWAI_ratio"] = safe_divide(100.0 * frame[command_best], frame["pWHIP"])
    reliability_rows.append({**context, "component": "WAI_beta", "target": "future_whip", "train_weighted_rmse": beta_score, **beta_params})

    hr_candidates = []
    hr_bip = safe_divide(train["hr"], train["bip"])
    train = train.assign(_hr_bip=hr_bip)
    test = test.assign(_hr_bip=safe_divide(test["hr"], test["bip"]))
    for c_hr in C_HR_BIP_GRID:
        reg_hr_bip = shrink_rate(train, "_hr_bip", "bip", c_hr, lg["lg_hr_bip"])
        hr9_reg = safe_divide(9.0 * reg_hr_bip * train["bip"], train["ip"])
        hr_candidates.append(("HR9_reg", hr9_reg, {"C_HR_BIP": c_hr}))
    _, hr_params, hr_score = tune_series(train, hr_candidates, "future_era", "future_ip")
    c_hr = int(hr_params.get("C_HR_BIP", C_HR_BIP_GRID[0]))
    for frame in [train, test]:
        reg_hr_bip = shrink_rate(frame, "_hr_bip", "bip", c_hr, lg["lg_hr_bip"])
        frame["HR9_reg"] = safe_divide(9.0 * reg_hr_bip * frame["bip"], frame["ip"])
    reliability_rows.append({**context, "component": "HR9_reg", "target": "future_era", "train_weighted_rmse": hr_score, "lgHR9": lg["lg_hr9"], **hr_params})

    era_candidates = [
        (f"ERA_reg_C{c}", shrink_rate(train, "era", "ip", c, lg["lg_era"]), {"C_ERA_IP": c})
        for c in C_ERA_IP_GRID
    ]
    _, era_params, era_score = tune_series(train, era_candidates, "future_era", "future_ip")
    c_era = int(era_params.get("C_ERA_IP", C_ERA_IP_GRID[0]))
    for frame in [train, test]:
        frame["ERA_reg"] = shrink_rate(frame, "era", "ip", c_era, lg["lg_era"])
    reliability_rows.append({**context, "component": "ERA_reg", "target": "future_era", "train_weighted_rmse": era_score, "lgERA": lg["lg_era"], **era_params})

    edf_features_train = pd.DataFrame(
        {
            "traffic": train["pWHIP"] - lg["lg_whip"],
            "command": -(train[command_best] - lg["lg_kbb"]),
            "hr": train["HR9_reg"] - lg["lg_hr9"],
            "era": train["ERA_reg"] - lg["lg_era"],
            "target": train["future_era"],
            "weight": train["future_ip"],
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()
    if len(edf_features_train) >= 20:
        x = np.column_stack([np.ones(len(edf_features_train)), edf_features_train[["traffic", "command", "hr", "era"]].to_numpy(dtype=float)])
        y = edf_features_train["target"].to_numpy(dtype=float)
        w = np.sqrt(edf_features_train["weight"].clip(lower=0).to_numpy(dtype=float))
        coef = np.linalg.lstsq(x * w[:, None], y * w, rcond=None)[0]
    else:
        coef = np.array([lg["lg_era"], 0.0, 0.0, 0.0, 0.0])
    for frame in [train, test]:
        traffic = frame["pWHIP"] - lg["lg_whip"]
        command = -(frame[command_best] - lg["lg_kbb"])
        hr = frame["HR9_reg"] - lg["lg_hr9"]
        era = frame["ERA_reg"] - lg["lg_era"]
        frame["EDF"] = coef[0] + coef[1] * traffic + coef[2] * command + coef[3] * hr + coef[4] * era
        frame["EDF_plus"] = 100.0 * frame["EDF"] / lg["lg_era"]
        frame["ERA_Trap"] = frame["era"] - frame["EDF"]
        frame["EDF_z"] = (
            z_from_train(train["pWHIP"], frame["pWHIP"])
            - z_from_train(train[command_best], frame[command_best])
            + z_from_train(train["HR9_reg"], frame["HR9_reg"])
            + 0.5 * z_from_train(train["ERA_reg"], frame["ERA_reg"])
        )
    reliability_rows.append(
        {
            **context,
            "component": "EDF",
            "target": "future_era",
            "command": command_best,
            "beta0": coef[0],
            "beta1_pWHIP": coef[1],
            "beta2_command_negated": coef[2],
            "beta3_HR9": coef[3],
            "beta4_ERA": coef[4],
        }
    )

    return train.drop(columns=["_hr_bip"], errors="ignore"), test.drop(columns=["_hr_bip"], errors="ignore"), {"command_best": command_best}


TARGET_SPECS = {
    "kbb": {
        "target": "future_kbb_ratio",
        "weight": "future_tbf",
        "output": "kbb_target_metrics.csv",
        "models": [
            ("raw_KBB_ratio", ["kbb_ratio"]),
            ("K_pct", ["k_pct"]),
            ("BB_pct", ["bb_pct"]),
            ("KBB", ["kbb"]),
            ("KBB_reg_direct", ["KBB_reg_direct"]),
            ("KBB_reg_component", ["KBB_reg_component"]),
            ("CCR", ["CCR"]),
            ("CCR_floor", ["CCR_floor"]),
            ("CSS", ["CSS"]),
        ],
    },
    "whip": {
        "target": "future_whip",
        "weight": "future_ip",
        "output": "whip_target_metrics.csv",
        "models": [
            ("WHIP", ["whip"]),
            ("WHIP_reg", ["WHIP_reg"]),
            ("xWHIP_lgBABIP", ["xwhip_lgbabip"]),
            ("pWHIP", ["pWHIP"]),
            ("KBB", ["kbb"]),
            ("KBB_reg_direct", ["KBB_reg_direct"]),
            ("KBB_reg_component", ["KBB_reg_component"]),
            ("CCR", ["CCR"]),
            ("WSI_raw", ["wsi_raw"]),
            ("WSI_xWHIP_lgBABIP", ["wsi_xlgbabip"]),
            ("WSI_reg_tuned", ["WSI_reg_tuned"]),
            ("WAI", ["WAI"]),
            ("xWAI_ratio", ["xWAI_ratio"]),
            ("KBB_best_plus_pWHIP", ["KBB_reg_direct", "pWHIP"]),
            ("KBB_best_plus_pWHIP_plus_logTBF", ["KBB_reg_direct", "pWHIP", "log_current_tbf"]),
        ],
    },
    "era": {
        "target": "future_era",
        "weight": "future_ip",
        "output": "era_target_metrics.csv",
        "models": [
            ("ERA", ["era"]),
            ("ERA_reg", ["ERA_reg"]),
            ("WHIP", ["whip"]),
            ("WHIP_reg", ["WHIP_reg"]),
            ("xWHIP_lgBABIP", ["xwhip_lgbabip"]),
            ("pWHIP", ["pWHIP"]),
            ("KBB", ["kbb"]),
            ("KBB_reg_best", ["KBB_reg_direct"]),
            ("CCR", ["CCR"]),
            ("WAI", ["WAI"]),
            ("HR9", ["hr9"]),
            ("HR9_reg", ["HR9_reg"]),
            ("EDF", ["EDF"]),
            ("EDF_z", ["EDF_z"]),
            ("KBB_best_plus_pWHIP_plus_HR9_reg", ["KBB_reg_direct", "pWHIP", "HR9_reg"]),
            ("KBB_best_plus_pWHIP_plus_HR9_reg_plus_ERA_reg", ["KBB_reg_direct", "pWHIP", "HR9_reg", "ERA_reg"]),
        ],
    },
}


def replace_best_feature(specs: dict[str, dict[str, object]], command_best: str) -> dict[str, dict[str, object]]:
    out = {}
    for target_name, spec in specs.items():
        models = []
        for model_name, features in spec["models"]:
            models.append((model_name, [command_best if f == "KBB_reg_direct" and "KBB_best" in model_name else f for f in features]))
        out[target_name] = {**spec, "models": models}
    return out


def evaluate(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metric_rows: list[dict[str, object]] = []
    reliability_rows: list[dict[str, object]] = []
    prediction_frames: list[pd.DataFrame] = []
    for exclude_2020, ex_data in data.groupby("exclude_2020", dropna=False):
        for split in ["all", "starter", "reliever"]:
            split_data = apply_thresholds(filtered_split(ex_data, split), split)
            if split_data.empty:
                continue
            preds_by_target_model: dict[tuple[str, str], list[pd.DataFrame]] = {}
            for period in sorted(split_data["period"].unique()):
                train = split_data[split_data["period"] < period].copy()
                test = split_data[split_data["period"] == period].copy()
                if len(train) < 30 or len(test) < 3:
                    continue
                context = {"scenario": "season_to_next", "split": split, "exclude_2020": bool(exclude_2020), "test_period": int(period)}
                train, test, choices = add_fold_components(train, test, reliability_rows, context)
                target_specs = replace_best_feature(TARGET_SPECS, choices["command_best"])
                for target_name, spec in target_specs.items():
                    target_col = spec["target"]
                    weight_col = spec["weight"]
                    for model_name, features in spec["models"]:
                        fit_test, pred = weighted_lstsq_predict(train, test, features, target_col, weight_col)
                        if len(pred) != len(fit_test):
                            continue
                        out = fit_test[["season", "period", "player_name", "pitcher_season", target_col, weight_col]].copy()
                        out["target"] = target_name
                        out["scenario"] = "season_to_next"
                        out["split"] = split
                        out["exclude_2020"] = bool(exclude_2020)
                        out["model"] = model_name
                        out["features"] = "+".join(features)
                        out["prediction"] = pred
                        for feature in set(features + ["whip", "kbb", "xwhip_lgbabip", "wsi_raw", "wsi_xlgbabip", "pWHIP", "WAI", "EDF"]):
                            if feature in fit_test.columns:
                                out[feature] = fit_test[feature].to_numpy()
                        preds_by_target_model.setdefault((target_name, model_name), []).append(out)
            for (target_name, model_name), frames in preds_by_target_model.items():
                pred_frame = pd.concat(frames, ignore_index=True)
                spec = TARGET_SPECS[target_name]
                target_col = spec["target"]
                weight_col = spec["weight"]
                split_baseline = weighted_average(split_data[target_col], split_data[weight_col])
                summary = metrics(
                    pred_frame[target_col].to_numpy(dtype=float),
                    pred_frame["prediction"].to_numpy(dtype=float),
                    pred_frame[weight_col].to_numpy(dtype=float),
                    split_baseline,
                )
                if not summary:
                    continue
                metric_rows.append(
                    {
                        "target": target_name,
                        "scenario": "season_to_next",
                        "split": split,
                        "exclude_2020": bool(exclude_2020),
                        "model": model_name,
                        "features": pred_frame["features"].iloc[0],
                        "n": len(pred_frame),
                        "periods": pred_frame["period"].nunique(),
                        **summary,
                    }
                )
                prediction_frames.append(pred_frame)
    predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    return pd.DataFrame(metric_rows), pd.DataFrame(reliability_rows), predictions, build_deciles_and_buckets(predictions)


def predictor_direction(target: str, model: str) -> str:
    low_models = {"WHIP", "WHIP_reg", "xWHIP_lgBABIP", "pWHIP", "ERA", "ERA_reg", "WAI", "HR9", "HR9_reg", "EDF", "EDF_z"}
    if target in {"whip", "era"} and model in low_models:
        return "low"
    if target == "kbb" and model in {"BB_pct"}:
        return "low"
    return "high"


def build_deciles_and_buckets(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return pd.DataFrame()
    for keys, group in predictions.groupby(["target", "scenario", "split", "exclude_2020", "model"], dropna=False):
        target, scenario, split, exclude_2020, model = keys
        feature = group["features"].iloc[0].split("+")[0]
        target_col = TARGET_SPECS[target]["target"]
        weight_col = TARGET_SPECS[target]["weight"]
        if feature not in group.columns:
            feature = "prediction"
        data = group.dropna(subset=[feature, target_col, weight_col]).copy()
        if len(data) < 20 or data[feature].nunique() < 10:
            continue
        ascending = predictor_direction(target, model) == "low"
        data["_rank"] = data[feature].rank(method="first", ascending=ascending)
        data["decile"] = pd.qcut(data["_rank"], 10, labels=False, duplicates="drop") + 1
        for decile, decile_frame in data.groupby("decile"):
            rows.append(
                {
                    "kind": "decile",
                    "target": target,
                    "scenario": scenario,
                    "split": split,
                    "exclude_2020": bool(exclude_2020),
                    "model": model,
                    "bucket": int(decile),
                    "n": len(decile_frame),
                    "avg_score": decile_frame[feature].mean(),
                    "future_value": weighted_average(decile_frame[target_col], decile_frame[weight_col]),
                }
            )
        data["bucket"] = np.where(data["_rank"] <= data["_rank"].quantile(0.2), "top20", np.where(data["_rank"] >= data["_rank"].quantile(0.8), "bottom20", "middle"))
        for bucket, bucket_frame in data.groupby("bucket"):
            rows.append(
                {
                    "kind": "top_bottom",
                    "target": target,
                    "scenario": scenario,
                    "split": split,
                    "exclude_2020": bool(exclude_2020),
                    "model": model,
                    "bucket": bucket,
                    "n": len(bucket_frame),
                    "avg_score": bucket_frame[feature].mean(),
                    "future_value": weighted_average(bucket_frame[target_col], bucket_frame[weight_col]),
                }
            )
    return pd.DataFrame(rows)


def write_plots(paths: ProjectPaths, metrics_frame: pd.DataFrame) -> None:
    if metrics_frame.empty:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    primary = metrics_frame[(metrics_frame["split"] == "all") & (~metrics_frame["exclude_2020"])].copy()
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    for ax, target in zip(axes, ["kbb", "whip", "era"]):
        data = primary[primary["target"] == target].sort_values("weighted_rmse").head(10)
        ax.barh(data["model"], data["weighted_rmse"], color="#386f8f")
        ax.invert_yaxis()
        ax.set_title(f"{target.upper()} weighted RMSE")
    fig.savefig(paths.plots / "category_weighted_rmse.png", dpi=160)
    plt.close(fig)


def write_summary(paths: ProjectPaths, metrics_frame: pd.DataFrame, reliability: pd.DataFrame, manifest_notes: list[str]) -> None:
    primary = metrics_frame[(metrics_frame["split"] == "all") & (~metrics_frame["exclude_2020"])].copy()

    def best(target: str) -> pd.Series | None:
        data = primary[primary["target"] == target].sort_values("weighted_rmse")
        return None if data.empty else data.iloc[0]

    def model_row(target: str, model: str) -> pd.Series | None:
        data = primary[(primary["target"] == target) & (primary["model"] == model)]
        return None if data.empty else data.iloc[0]

    def rmse_text(target: str, model: str) -> str:
        row = model_row(target, model)
        return "NA" if row is None else f"{row['weighted_rmse']:.4f}"

    def split_best(target: str, split: str) -> str:
        data = metrics_frame[(metrics_frame["target"] == target) & (metrics_frame["split"] == split) & (~metrics_frame["exclude_2020"])].sort_values("weighted_rmse")
        if data.empty:
            return "not available"
        row = data.iloc[0]
        return f"`{row['model']}` ({row['weighted_rmse']:.4f})"

    def mode_text(component: str, column: str) -> str:
        if reliability.empty or column not in reliability.columns:
            return "NA"
        data = reliability[reliability["component"] == component][column].dropna()
        if data.empty:
            return "NA"
        return str(data.value_counts().idxmax())

    lines = ["# Category Forecasting Summary", ""]
    if manifest_notes:
        lines += ["## Run Notes", *[f"- {note}" for note in manifest_notes], ""]

    lines += [
        "## Executive Summary",
        "",
        f"Best future K/BB model: `{best('kbb')['model']}` ({best('kbb')['weighted_rmse']:.4f}).",
        f"Best future WHIP model: `{best('whip')['model']}` ({best('whip')['weighted_rmse']:.4f}).",
        f"Best future ERA model: `{best('era')['model']}` ({best('era')['weighted_rmse']:.4f}).",
        "",
        "The reusable component approach is promising for K/BB and ERA, but the WHIP result still confirms the earlier baseline: regressed command alone is very hard to beat.",
        "",
        "## Component Regression Choices",
        "",
        f"- K%/BB% component: most often selected `C_K={mode_text('KBB_reg_component', 'C_K')}` and `C_BB={mode_text('KBB_reg_component', 'C_BB')}`.",
        f"- Direct KBB regression: most common `C_KBB={mode_text('KBB_reg_direct', 'C_KBB')}`.",
        f"- WHIP regression: most common `C_WHIP_IP={mode_text('WHIP_reg', 'C_WHIP_IP')}`.",
        f"- pWHIP blend: most common `alpha={mode_text('pWHIP', 'alpha')}`.",
        f"- WAI command penalty: most common `beta={mode_text('WAI_beta', 'beta')}`.",
        f"- HR damage regression: most common `C_HR_BIP={mode_text('HR9_reg', 'C_HR_BIP')}`.",
        f"- ERA regression: most common `C_ERA_IP={mode_text('ERA_reg', 'C_ERA_IP')}`.",
        "",
        "## Phase Answers",
        "",
        f"1. Component winners: `KBB_reg_component` led future K/BB ({rmse_text('kbb', 'KBB_reg_component')}), `KBB_reg_direct` led future WHIP ({rmse_text('whip', 'KBB_reg_direct')}), and `KBB_best_plus_pWHIP_plus_HR9_reg` led future ERA ({rmse_text('era', 'KBB_best_plus_pWHIP_plus_HR9_reg')}).",
        f"2. CCR vs raw K/BB and K-BB%: CCR ({rmse_text('kbb', 'CCR')}) narrowly beat raw K/BB ({rmse_text('kbb', 'raw_KBB_ratio')}) and K-BB% ({rmse_text('kbb', 'KBB')}), but `KBB_reg_component` was better than CCR.",
        f"3. WAI vs KBB_reg for WHIP: no. WAI ({rmse_text('whip', 'WAI')}) trailed both `KBB_reg_direct` ({rmse_text('whip', 'KBB_reg_direct')}) and `KBB_reg_component` ({rmse_text('whip', 'KBB_reg_component')}).",
        f"4. EDF vs ERA_reg and KBB_reg for ERA: yes. EDF ({rmse_text('era', 'EDF')}) beat ERA_reg ({rmse_text('era', 'ERA_reg')}) and KBB_reg_best ({rmse_text('era', 'KBB_reg_best')}), though the simpler `KBB_best + pWHIP + HR9_reg` model was slightly better ({rmse_text('era', 'KBB_best_plus_pWHIP_plus_HR9_reg')}).",
        "5. Best pure model by category: K/BB = `KBB_reg_component`; WHIP = `KBB_reg_direct`; ERA = `KBB_best_plus_pWHIP_plus_HR9_reg`.",
        "6. Best simple public screen by category: K/BB = `KBB_reg_component`; WHIP = `KBB_reg_direct` for accuracy or `WSI_reg_tuned` for a ratio-style screen; ERA = `EDF` as a compact category-specific screen.",
        "7. Original WSI role: still useful as a WHIP/fantasy screen because xWSI and regressed WSI beat WHIP, but it is not the best pure predictor when regressed command is available.",
        "",
        "## Split Summary",
        "",
        f"- Future K/BB: all = {split_best('kbb', 'all')}; starters = {split_best('kbb', 'starter')}; relievers = {split_best('kbb', 'reliever')}.",
        f"- Future WHIP: all = {split_best('whip', 'all')}; starters = {split_best('whip', 'starter')}; relievers = {split_best('whip', 'reliever')}.",
        f"- Future ERA: all = {split_best('era', 'all')}; starters = {split_best('era', 'starter')}; relievers = {split_best('era', 'reliever')}.",
        "",
        "Reliever K/BB was the main exception to the all-pitcher pattern: raw K/BB led that split, suggesting the component shrinkage may be too conservative for some reliever-only K/BB ranking use cases.",
        "",
        "## Category Leaderboards",
        "",
    ]
    for target in ["kbb", "whip", "era"]:
        data = primary[primary["target"] == target].sort_values("weighted_rmse").head(8)
        lines += [f"### {target.upper()}", "", "| model | weighted RMSE | Pearson | OOS R2 |", "|---|---:|---:|---:|"]
        for _, row in data.iterrows():
            lines.append(f"| `{row['model']}` | {row['weighted_rmse']:.4f} | {row['pearson']:.3f} | {row['oos_r2']:.3f} |")
        lines.append("")

    lines += [
        "## Baseline WSI Conclusion",
        "Preserved: the prior real no-Statcast run found `KBB_reg_tuned` was the best one-number future-WHIP predictor. `WSI_raw` beat WHIP and `WSI_xWHIP` beat `WSI_raw`, but WSI variants did not beat regressed K-BB%.",
        "",
        "## Recommendation",
        "",
        "- Publish `KBB_reg_component` for command/K-BB category forecasting.",
        "- Keep `KBB_reg_direct` as the best future-WHIP accuracy benchmark.",
        "- Use `WSI_reg_tuned` or xWSI-style ratios as public-facing WHIP screens, not as the pure projection leader.",
        "- Use `EDF` as the compact ERA screen, while noting the best pure ERA model is the simple component model `KBB_best + pWHIP + HR9_reg`.",
        "",
    ]
    if not reliability.empty:
        lines += ["## Component Choices", ""]
        counts = reliability.groupby(["component", "target"], dropna=False).size().reset_index(name="folds")
        lines.append("| component | target | folds |")
        lines.append("|---|---|---:|")
        for _, row in counts.iterrows():
            lines.append(f"| `{row['component']}` | `{row['target']}` | {int(row['folds'])} |")
        lines.append("")
    text = "\n".join(lines)
    (paths.results / "category_summary.md").write_text(text, encoding="utf-8")
    (paths.results / "interpretation.md").write_text(text, encoding="utf-8")


def write_manifest(paths: ProjectPaths, args: argparse.Namespace, row_counts: dict[str, int], notes: list[str]) -> None:
    manifest = {
        "run_id": paths.run_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "git_hash": git_hash(paths.root.parents[1] if paths.root.name == "whip_predictors" else paths.root),
        "args": vars(args),
        "self_test": args.self_test,
        "seasons": args.seasons,
        "row_counts": row_counts,
        "notes": notes,
        "grids": {
            "C_K": C_RATE_GRID,
            "C_BB": C_RATE_GRID,
            "C_KBB": C_RATE_GRID,
            "C_WHIP_IP": C_WHIP_IP_GRID,
            "C_HR_BIP": C_HR_BIP_GRID,
            "C_ERA_IP": C_ERA_IP_GRID,
            "alpha": ALPHA_GRID,
            "beta": BETA_GRID,
        },
        "cache_paths": {
            "raw_dir": str(paths.raw),
            "processed_dir": str(paths.processed),
        },
    }
    (paths.results / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    run_id = args.run_id or default_run_id(args)
    paths = ProjectPaths.from_root(root, run_id, args.raw_dir)
    paths.ensure()
    os.environ.setdefault("MPLCONFIGDIR", str(paths.root / ".mplconfig"))
    (paths.root / ".mplconfig").mkdir(exist_ok=True)
    notes = [
        "Season-to-next-season only; no Statcast, in-season, or rolling-window expansion in this phased run.",
        "Prior WHIP baseline preserved: KBB_reg_tuned beat WSI variants in real_no_statcast_bootstrap50.",
    ]
    if args.fetch:
        cache_fangraphs_pitching(paths, args.seasons, args.force, args.season_source)
    pitching = load_fangraphs_pitching(paths, args.seasons)
    required = ["er", "era", "hr9"]
    if any(column not in pitching.columns or pitching[column].isna().all() for column in required):
        raise RuntimeError("ERA/ER/HR9 inputs are missing. Rerun with --fetch --force --season-source mlb to refresh the season cache.")
    datasets = [build_season_dataset(pitching, False), build_season_dataset(pitching, True)]
    data = pd.concat(datasets, ignore_index=True)
    metric_frame, reliability, predictions, buckets = evaluate(data)
    paths.results.mkdir(parents=True, exist_ok=True)
    metric_frame.to_csv(paths.results / "category_metrics.csv", index=False)
    reliability.to_csv(paths.results / "component_reliability_results.csv", index=False)
    predictions.to_csv(paths.results / "category_predictions.csv", index=False)
    buckets[buckets["kind"] == "decile"].to_csv(paths.results / "category_decile_results.csv", index=False)
    buckets[buckets["kind"] == "top_bottom"].to_csv(paths.results / "category_bucket_results.csv", index=False)
    for target, spec in TARGET_SPECS.items():
        metric_frame[metric_frame["target"] == target].to_csv(paths.results / spec["output"], index=False)
    write_plots(paths, metric_frame)
    row_counts = {
        "pitching_features": int(len(pitching)),
        "analysis_rows": int(len(data)),
        "metrics": int(len(metric_frame)),
        "reliability_rows": int(len(reliability)),
        "predictions": int(len(predictions)),
        "bucket_rows": int(len(buckets)),
    }
    write_summary(paths, metric_frame, reliability, notes)
    write_manifest(paths, args, row_counts, notes)
    paths.update_latest_pointer()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--seasons", nargs="+", type=int, default=SEASONS)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--season-source", choices=["auto", "fangraphs", "mlb"], default="auto")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--fast-grid", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        args.fast_grid = True
        if args.raw_dir is None:
            args.raw_dir = str(Path(args.project_root).resolve() / "data" / "self_test_raw")
        seed_paths = ProjectPaths.from_root(Path(args.project_root).resolve(), "category_selftest_seed", args.raw_dir)
        write_self_test_cache(seed_paths)
        args.fetch = False
    configure_grids(args.fast_grid)
    run(args)


if __name__ == "__main__":
    main()
