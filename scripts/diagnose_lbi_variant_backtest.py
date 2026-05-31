#!/usr/bin/env python3
"""Backtest candidate Longball Index component mixes.

This is an internal diagnostic only. It reads local historical Statcast BBE
caches plus Home Run Tracker detail caches and does not modify public JSON or
the live LBI formula.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd
from data_integrity import (
    is_missing_hrt_statcast_contradiction,
    print_integrity_quarantine,
    scope_to_regular_season,
    validate_hrt_detail_completeness,
)

try:
    from sklearn.linear_model import ElasticNetCV, LassoCV, RidgeCV
except ImportError:  # pragma: no cover - diagnostic dependency is optional
    ElasticNetCV = LassoCV = RidgeCV = None


NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]
DEFAULT_NEXT_WEEKS = 6
DEFAULT_MIN_FIRST_BBE = 50
DEFAULT_MIN_FUTURE_BBE = 25
CHECKPOINT_MONTH_DAYS = [(5, 1), (6, 1), (7, 1), (8, 1)]

SPLITS = {
    2021: ("2021-03-31", "2021-07-11", "2021-07-15", "2021-10-03"),
    2022: ("2022-04-07", "2022-07-17", "2022-07-21", "2022-10-05"),
    2023: ("2023-03-30", "2023-07-09", "2023-07-14", "2023-10-01"),
    2024: ("2024-03-28", "2024-07-14", "2024-07-19", "2024-09-30"),
    2025: ("2025-03-27", "2025-07-13", "2025-07-18", "2025-09-28"),
}

CURRENT_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "avgDistanceOnBarrels": 0.125,
    "hardHitRate": 0.075,
}

REQUESTED_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "la25_40_100Rate": 0.125,
    "hardHitRate": 0.075,
}

SPLIT_EV_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "la25_40_100Rate": 0.05,
    "la25_40_105Rate": 0.075,
    "hardHitRate": 0.075,
}

PURE_105_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.125,
    "hardHitRate": 0.075,
}

PURE_105_15_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.15,
    "hardHitRate": 0.05,
}

FLIPPED_BARREL_105_LBI_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.15,
    "la25_40_105Rate": 0.20,
    "hardHitRate": 0.05,
}

XHR_55_105_25_LBI_WEIGHTS = {
    "xhrPerBbe": 0.55,
    "barrelRate": 0.15,
    "la25_40_105Rate": 0.25,
    "hardHitRate": 0.05,
}

XHR_50_SPLIT_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.175,
    "la25_40_105Rate": 0.275,
    "hardHitRate": 0.05,
}

XHR_50_BARREL_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.25,
    "hardHitRate": 0.05,
}

LBI_V13_WEIGHTS = XHR_50_BARREL_LBI_WEIGHTS

LBI_V13_COMPONENTS = {
    "xhrPerBbe": "Adjusted xHR/BBE",
    "barrelRate": "Barrel%",
    "la25_40_105Rate": "HR-Window Thunder Rate",
    "hardHitRate": "Hard Hit%",
}

NO_DOUBTER_SHRINKAGE_GRID = [5, 10, 20, 40]

EV90_CANDIDATE_COLUMNS = ["lbi_ev90_A", "lbi_ev90_B", "lbi_ev90_C", "lbi_ev90_D"]

DESCRIPTIVE_FEATURES = [
    "xhrPerBbe",
    "la25_40_105Rate",
    "barrelRate",
    "hardHitRate",
    "ev90",
    "avgLaunchAngle",
    "sweetSpotRate",
]

DESCRIPTIVE_FEATURE_LABELS = {
    "xhrPerBbe": "Adjusted xHR/BBE",
    "la25_40_105Rate": "HR-Window Thunder",
    "barrelRate": "Barrel%",
    "hardHitRate": "Hard Hit%",
    "ev90": "EV90",
    "avgLaunchAngle": "Avg Launch Angle",
    "sweetSpotRate": "Sweet-Spot Rate",
}

XHR_50_105_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.15,
    "la25_40_105Rate": 0.30,
    "hardHitRate": 0.05,
}

NO_HH_BARREL_25_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.25,
    "la25_40_105Rate": 0.25,
}

NO_HH_105_30_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.30,
}

CONSERVATIVE_MIDDLE_LBI_WEIGHTS = {
    "xhrPerBbe": 0.55,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.20,
    "hardHitRate": 0.05,
}

HEAVY_THUNDER_LBI_WEIGHTS = {
    "xhrPerBbe": 0.40,
    "barrelRate": 0.10,
    "la25_40_105Rate": 0.40,
    "hardHitRate": 0.10,
}

EV90_FORMULAS = {
    "lbi_v13": ("v1.3 50 xHR / 20 Barrel / 25 Thunder / 5 HardHit", LBI_V13_WEIGHTS),
    "lbi_two_factor_xhr75_thunder25": (
        "two_factor 75 xHR / 25 Thunder",
        {"xhrPerBbe": 0.75, "la25_40_105Rate": 0.25},
    ),
    "lbi_two_factor_xhr70_thunder30": (
        "two_factor 70 xHR / 30 Thunder",
        {"xhrPerBbe": 0.70, "la25_40_105Rate": 0.30},
    ),
    "lbi_two_factor_xhr65_thunder35": (
        "two_factor 65 xHR / 35 Thunder",
        {"xhrPerBbe": 0.65, "la25_40_105Rate": 0.35},
    ),
    "lbi_two_factor_xhr60_thunder40": (
        "two_factor 60 xHR / 40 Thunder",
        {"xhrPerBbe": 0.60, "la25_40_105Rate": 0.40},
    ),
    "lbi_ev90_A": (
        "cand_A 55 xHR / 25 EV90 / 20 Thunder",
        {"xhrPerBbe": 0.55, "ev90": 0.25, "la25_40_105Rate": 0.20},
    ),
    "lbi_ev90_B": (
        "cand_B 60 xHR / 20 EV90 / 20 Thunder",
        {"xhrPerBbe": 0.60, "ev90": 0.20, "la25_40_105Rate": 0.20},
    ),
    "lbi_ev90_C": (
        "cand_C 50 xHR / 30 EV90 / 20 Thunder",
        {"xhrPerBbe": 0.50, "ev90": 0.30, "la25_40_105Rate": 0.20},
    ),
    "lbi_ev90_D": (
        "cand_D 55 xHR / 20 EV90 / 25 Thunder",
        {"xhrPerBbe": 0.55, "ev90": 0.20, "la25_40_105Rate": 0.25},
    ),
    "candidate_lbi_v14_heavy_thunder": (
        "heavy_thunder 40 xHR / 10 Barrel / 40 Thunder / 10 HardHit",
        HEAVY_THUNDER_LBI_WEIGHTS,
    ),
}

STORM_WATCH_FORMULAS = {
    "storm_base_T_xhr60_thunder40": (
        "base_T 60 xHR / 40 Thunder",
        {"xhrPerBbe": 0.60, "la25_40_105Rate": 0.40},
    ),
    "storm_base_E_xhr60_ev90_40": (
        "base_E 60 xHR / 40 EV90",
        {"xhrPerBbe": 0.60, "ev90": 0.40},
    ),
    "storm_combo_xhr50_thunder30_ev90_20": (
        "combo 50 xHR / 30 Thunder / 20 EV90",
        {"xhrPerBbe": 0.50, "la25_40_105Rate": 0.30, "ev90": 0.20},
    ),
    "storm_combo_xhr50_thunder25_ev90_25": (
        "combo 50 xHR / 25 Thunder / 25 EV90",
        {"xhrPerBbe": 0.50, "la25_40_105Rate": 0.25, "ev90": 0.25},
    ),
    "storm_combo_xhr55_thunder25_ev90_20": (
        "combo 55 xHR / 25 Thunder / 20 EV90",
        {"xhrPerBbe": 0.55, "la25_40_105Rate": 0.25, "ev90": 0.20},
    ),
}
STORM_SHRINKAGE_GRID = [25, 50, 75, 100]
STORM_PHASE2_FORMULAS = {
    "storm_phase2_raw_combo": (
        "raw combo 50 xHR / 25 Thunder / 25 EV90",
        {"xhrPerBbe": 0.50, "la25_40_105Rate": 0.25, "ev90": 0.25},
    ),
    "storm_phase2_l1_m25": (
        "L1 league shrink M25",
        {"xhrPerBbeShrunkM25": 0.50, "la25_40_105RateShrunkM25": 0.25, "ev90ShrunkM25": 0.25},
    ),
    "storm_phase2_l1_m50": (
        "L1 league shrink M50",
        {"xhrPerBbeShrunkM50": 0.50, "la25_40_105RateShrunkM50": 0.25, "ev90ShrunkM50": 0.25},
    ),
    "storm_phase2_l1_m100": (
        "L1 league shrink M100",
        {"xhrPerBbeShrunkM100": 0.50, "la25_40_105RateShrunkM100": 0.25, "ev90ShrunkM100": 0.25},
    ),
    "storm_phase2_thunder_only_m25": (
        "Thunder-only shrink M25",
        {"xhrPerBbe": 0.50, "la25_40_105RateShrunkM25": 0.25, "ev90": 0.25},
    ),
    "storm_phase2_xhr_thunder_m25_ev90_raw": (
        "xHR+Thunder shrink M25, EV90 raw",
        {"xhrPerBbeShrunkM25": 0.50, "la25_40_105RateShrunkM25": 0.25, "ev90": 0.25},
    ),
    "storm_phase2_light_xhr55_m25_ev90_raw": (
        "55 xHR / 22.5 Thunder M25 / 22.5 EV90",
        {"xhrPerBbe": 0.55, "la25_40_105RateShrunkM25": 0.225, "ev90": 0.225},
    ),
}
STORM_PHASE2_L2_GRID = [(150, 100), (150, 200), (250, 100), (250, 200), (350, 100), (350, 200)]
STORM_L2_XHR_M = 150
STORM_L2_THUNDER_M = 100
STORM_L2_CURRENT_COLUMN = f"storm_phase2_l2_x{STORM_L2_XHR_M}_t{STORM_L2_THUNDER_M}_evraw"
STORM_L2_CURRENT_LABEL = "Current L2: league-average no-prior fallback"
STORM_NO_PRIOR_VARIANTS = {
    "storm_l2_no_prior_raw": ("V_raw: no-prior current-only", 0),
    "storm_l2_no_prior_m40": ("V_m40: no-prior M40", 40),
    "storm_l2_no_prior_m75": ("V_m75: no-prior M75", 75),
}
STORM_WATCH_V1_COLUMN = "storm_watch_v1"
STORM_WATCH_V1_LABEL = "Storm Watch v1: stabilization-anchored no-prior fallback"
STORM_NO_PRIOR_STAB_COLUMN = STORM_WATCH_V1_COLUMN
STORM_NO_PRIOR_STAB_LABEL = STORM_WATCH_V1_LABEL
STORM_NO_PRIOR_FIX_MODELS = {
    STORM_L2_CURRENT_COLUMN: STORM_L2_CURRENT_LABEL,
    **{column: label for column, (label, _) in STORM_NO_PRIOR_VARIANTS.items()},
}
STORM_WATCH_DEFINITION = (
    "Storm Watch blends EV90 with current xHR/BBE and HR-Window Thunder Rate, "
    "stabilized toward prior-season power shape (or, for players without prior MLB data, "
    "toward league average at each component's stabilization rate), to flag near-term HR surge."
)
# Internal Storm Watch v1 design:
# - Real-prior players: existing L2 behavior, xHR M150 / Thunder M100, EV90 raw.
# - No-prior players: shrink xHR/BBE and Thunder toward league average at M317,
#   their measured ~0.5 self-correlation sample for no-prior players; EV90 at M62
#   because it stabilizes quickly. This intentionally keeps elite-looking
#   small-sample rookies (e.g. Murakami, 132 BBE -> rank 12 not 4) appropriately
#   regressed. Defensibility: best real-vs-fluke separation of tested variants.
# TODO Phase 3 UX: no-prior players should carry a "limited MLB sample" display
# flag so intentional regression reads clearly in private/public report surfaces.
STORM_NO_PRIOR_STAB_M = {"xhr": 317, "thunder": 317, "ev90": 62}
NO_PRIOR_SMALL_BBE_THRESHOLD = 75

THUNDER_30_LBI_WEIGHTS = {
    "xhrPerBbe": 0.475,
    "barrelRate": 0.175,
    "la25_40_105Rate": 0.30,
    "hardHitRate": 0.05,
}

THUNDER_35_LBI_WEIGHTS = {
    "xhrPerBbe": 0.45,
    "barrelRate": 0.15,
    "la25_40_105Rate": 0.35,
    "hardHitRate": 0.05,
}

THUNDER_375_LBI_WEIGHTS = {
    "xhrPerBbe": 0.425,
    "barrelRate": 0.125,
    "la25_40_105Rate": 0.375,
    "hardHitRate": 0.075,
}

SCALED_WINDOW_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.20,
    "scaledThunderRate": 0.25,
    "hardHitRate": 0.05,
}

NEAR_MISS_FLOOR_LBI_WEIGHTS = {
    "xhrPerBbe": 0.50,
    "barrelRate": 0.20,
    "la25_40_105Rate": 0.20,
    "nearMissThunderRate": 0.05,
    "hardHitRate": 0.05,
}

CORE_FORMULAS = {
    "current_lbi_v12_proxy": "A. Current production LBI v1.2",
    "candidate_lbi_xhr50_barrel": "B. 50% xHR / 20% Barrel / 25% Thunder / 5% HH",
    "candidate_lbi_xhr55_105_25": "C. 55% xHR / 15% Barrel / 25% Thunder / 5% HH",
    "candidate_lbi_no_hh_barrel25": "D. 50% xHR / 25% Barrel / 25% Thunder",
    "candidate_lbi_no_hh_105_30": "E. 50% xHR / 20% Barrel / 30% Thunder",
    "candidate_lbi_conservative_middle": "F. 55% xHR / 20% Barrel / 20% Thunder / 5% HH",
    "candidate_lbi_v14_thunder_30": "G. 47.5/17.5/30/5 thunder ladder",
    "candidate_lbi_v14_thunder_35": "H. 45/15/35/5 thunder ladder",
    "candidate_lbi_v14_thunder_375": "I. 42.5/12.5/37.5/7.5 thunder ladder",
    "candidate_lbi_v14_heavy_thunder": "G. v1.4 heavy thunder 40/10/40/10",
    "candidate_lbi_v14_scaled_window": "H. v1.4 scaled-window thunder",
    "candidate_lbi_v14_near_miss_floor": "I. v1.4 near-miss thunder floor",
}


@dataclass(frozen=True)
class Window:
    season: int
    label: str
    first_start: date
    first_end: date
    future_start: date
    future_end: date


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def cache_path_for_season(season: int) -> Path:
    return Path(f"data/raw/statcast-bbe-events-{season}.csv")


def hrt_detail_path_for_season(season: int) -> Path:
    return Path(f"data/cache/longball-threat-backtest/hrt-details-{season}-adj_xhr.csv")


def display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def load_name_map(season: int, details: pd.DataFrame) -> dict[int, str]:
    names: dict[int, str] = {}
    archive_path = Path(f"public/data/longball-index-{season}.json")
    if archive_path.exists():
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
        for player in payload.get("players", []):
            try:
                names[int(player["batter"])] = str(player["player"])
            except (KeyError, TypeError, ValueError):
                continue

    if "batter_id" in details.columns and "batter_name" in details.columns:
        for _, row in details[["batter_id", "batter_name"]].dropna().iterrows():
            try:
                names.setdefault(int(row["batter_id"]), display_name(row["batter_name"]))
            except (TypeError, ValueError):
                continue
    return names


def load_pitch_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"Missing local Statcast BBE cache: {path}")
    frame = pd.read_csv(path)
    required = [
        "game_date",
        "batter",
        "events",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "hit_distance_sc",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} is missing required columns: {', '.join(missing)}")
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce").dt.date
    for column in ["batter", "launch_speed", "launch_angle", "launch_speed_angle", "hit_distance_sc"]:
        frame[column] = to_numeric(frame[column])
    season = int(path.stem.rsplit("-", 1)[-1])
    return scope_to_regular_season(frame.dropna(subset=["game_date", "batter"]).copy(), season)


def load_hrt_details(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"Missing Home Run Tracker detail cache: {path}")
    details = pd.read_csv(path)
    required = ["game_date", "batter_id", "ct"]
    missing = [column for column in required if column not in details.columns]
    if missing:
        raise RuntimeError(f"{path} is missing required columns: {', '.join(missing)}")
    details["game_date"] = pd.to_datetime(details["game_date"], errors="coerce").dt.date
    details["batter_id"] = to_numeric(details["batter_id"])
    details["ct"] = to_numeric(details["ct"]).clip(0, 30)
    season = int(path.stem.split("-")[2])
    validate_hrt_detail_completeness(details, season, label=str(path))
    return scope_to_regular_season(details.dropna(subset=["game_date", "batter_id"]).copy(), season)


def load_prior_storm_components(season: int) -> pd.DataFrame:
    pitch_path = cache_path_for_season(season - 1)
    detail_path = hrt_detail_path_for_season(season - 1)
    if not pitch_path.exists() or not detail_path.exists():
        return pd.DataFrame(
            columns=["batter", "priorXhrPerBbe", "priorThunderRate", "priorEv90", "priorBbe"]
        )
    pitches = load_pitch_cache(pitch_path)
    details = load_hrt_details(detail_path)
    season_start = min(pitches["game_date"])
    season_end = max(pitches["game_date"])
    stats = bbe_stats(pitches, season_start, season_end, "prior")
    xhr = hrt_stats(details, season_start, season_end, "prior")
    prior = stats.merge(xhr, on="batter", how="left")
    for column in ["priorBbe", "priorLa25_40_105Bbe", "priorAdjustedXhr"]:
        if column not in prior.columns:
            prior[column] = 0
        prior[column] = to_numeric(prior[column]).fillna(0)
    prior["priorXhrPerBbe"] = prior["priorAdjustedXhr"] / prior["priorBbe"].where(prior["priorBbe"].gt(0))
    prior["priorThunderRate"] = prior["priorLa25_40_105Bbe"] / prior["priorBbe"].where(prior["priorBbe"].gt(0))
    prior["priorEv90"] = to_numeric(prior.get("priorEv90", pd.Series(index=prior.index)))
    return prior[["batter", "priorXhrPerBbe", "priorThunderRate", "priorEv90", "priorBbe"]]


def percentile_scores(values: pd.Series) -> pd.Series:
    ranks = values.rank(method="average", pct=True)

    def score(percentile: Any) -> float | None:
        if pd.isna(percentile):
            return None
        clipped = min(max(float(percentile), 0.01), 0.99)
        return 100 + NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped)

    return ranks.map(score)


def weighted_scores(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    component_scores = {key: percentile_scores(frame[key]) for key in weights}
    values: list[float | None] = []
    for index, _ in frame.iterrows():
        total = 0.0
        weighted = 0.0
        for key, weight in weights.items():
            value = component_scores[key].get(index)
            if value is None or pd.isna(value):
                continue
            total += weight
            weighted += weight * float(value)
        values.append(max(weighted / total, 0) if total else None)
    return pd.Series(values, index=frame.index)


def renormalized_without(weights: dict[str, float], removed: str) -> dict[str, float]:
    kept = {key: value for key, value in weights.items() if key != removed}
    total = sum(kept.values())
    return {key: value / total for key, value in kept.items()}


def current_lbi_v12_scores(frame: pd.DataFrame) -> pd.Series:
    component_scores = {key: percentile_scores(frame[key]) for key in CURRENT_LBI_WEIGHTS}
    values: list[float | None] = []
    for index, row in frame.iterrows():
        barrels = int(row.get("firstBarrels", 0) or 0)
        if barrels >= 10:
            weights = CURRENT_LBI_WEIGHTS
        elif barrels >= 5:
            weights = {
                "xhrPerBbe": 0.675,
                "barrelRate": 0.175,
                "avgDistanceOnBarrels": 0.075,
                "hardHitRate": 0.075,
            }
        else:
            weights = {
                "xhrPerBbe": 0.75,
                "barrelRate": 0.175,
                "hardHitRate": 0.075,
            }

        total = 0.0
        weighted = 0.0
        for key, weight in weights.items():
            value = component_scores[key].get(index)
            if value is None or pd.isna(value):
                continue
            total += weight
            weighted += weight * float(value)
        values.append(max(weighted / total, 0) if total else None)
    return pd.Series(values, index=frame.index)


def bbe_stats(frame: pd.DataFrame, start: date, end: date, prefix: str) -> pd.DataFrame:
    window = frame[(frame["game_date"] >= start) & (frame["game_date"] <= end)].copy()
    bbe = window[window["launch_speed"].notna() & window["launch_angle"].notna()].copy()
    if bbe.empty:
        return pd.DataFrame(columns=["batter"])

    bbe["isHr"] = bbe["events"].astype("string").str.lower().eq("home_run")
    bbe["isBarrel"] = bbe["launch_speed_angle"].eq(6)
    bbe["isHardHit"] = bbe["launch_speed"].ge(95)
    bbe["isSweetSpot"] = bbe["launch_angle"].between(8, 32, inclusive="both")
    bbe["isLaunchAngle25_40At100"] = bbe["launch_angle"].between(25, 40, inclusive="both") & bbe[
        "launch_speed"
    ].ge(100)
    bbe["isLaunchAngle25_40At105"] = bbe["launch_angle"].between(25, 40, inclusive="both") & bbe[
        "launch_speed"
    ].ge(105)
    bbe["isScaledThunder"] = (
        (bbe["launch_speed"].between(105, 107.999, inclusive="both") & bbe["launch_angle"].between(25, 35, inclusive="both"))
        | (bbe["launch_speed"].ge(108) & bbe["launch_angle"].between(24, 42, inclusive="both"))
    )
    bbe["isNearMissThunder"] = (
        bbe["launch_speed"].between(100, 104.999, inclusive="both")
        & bbe["launch_angle"].between(25, 40, inclusive="both")
    )
    bbe["barrelDistance"] = bbe["hit_distance_sc"].where(bbe["isBarrel"])
    grouped = (
        bbe.groupby("batter", as_index=False)
        .agg(
            bbe=("batter", "size"),
            hr=("isHr", "sum"),
            barrels=("isBarrel", "sum"),
            hardHitBbe=("isHardHit", "sum"),
            sweetSpotBbe=("isSweetSpot", "sum"),
            la25_40_100Bbe=("isLaunchAngle25_40At100", "sum"),
            la25_40_105Bbe=("isLaunchAngle25_40At105", "sum"),
            scaledThunderBbe=("isScaledThunder", "sum"),
            nearMissThunderBbe=("isNearMissThunder", "sum"),
            ev90=("launch_speed", lambda values: values.quantile(0.90)),
            avgLaunchAngle=("launch_angle", "mean"),
            avgDistanceOnBarrels=("barrelDistance", "mean"),
        )
        .rename(
            columns={
                "bbe": f"{prefix}Bbe",
                "hr": f"{prefix}Hr",
                "barrels": f"{prefix}Barrels",
                "hardHitBbe": f"{prefix}HardHitBbe",
                "sweetSpotBbe": f"{prefix}SweetSpotBbe",
                "la25_40_100Bbe": f"{prefix}La25_40_100Bbe",
                "la25_40_105Bbe": f"{prefix}La25_40_105Bbe",
                "scaledThunderBbe": f"{prefix}ScaledThunderBbe",
                "nearMissThunderBbe": f"{prefix}NearMissThunderBbe",
                "ev90": f"{prefix}Ev90",
                "avgLaunchAngle": f"{prefix}AvgLaunchAngle",
                "avgDistanceOnBarrels": f"{prefix}AvgDistanceOnBarrels",
            }
        )
    )
    return grouped


def hrt_stats(details: pd.DataFrame, start: date, end: date, prefix: str) -> pd.DataFrame:
    window = details[(details["game_date"] >= start) & (details["game_date"] <= end)].copy()
    if window.empty:
        return pd.DataFrame(columns=["batter"])
    window["detailXhr"] = window["ct"].fillna(0) / 30
    window["isNoDoubter"] = window.get("is_no_doubter_detail", pd.Series(index=window.index, dtype=bool)).astype("string").str.lower().eq("true")
    window["isMostlyGone"] = window.get("is_mostly_gone_detail", pd.Series(index=window.index, dtype=bool)).astype("string").str.lower().eq("true")
    window["isDoubter"] = window.get("is_doubter_detail", pd.Series(index=window.index, dtype=bool)).astype("string").str.lower().eq("true")
    return (
        window.groupby("batter_id", as_index=False)
        .agg(
            **{
                f"{prefix}AdjustedXhr": ("detailXhr", "sum"),
                f"{prefix}HrCapableEvents": ("detailXhr", "size"),
                f"{prefix}NoDoubterEvents": ("isNoDoubter", "sum"),
                f"{prefix}MostlyGoneEvents": ("isMostlyGone", "sum"),
                f"{prefix}DoubterEvents": ("isDoubter", "sum"),
            }
        )
        .rename(columns={"batter_id": "batter"})
    )


def prepare_window(
    pitches: pd.DataFrame,
    details: pd.DataFrame,
    names: dict[int, str],
    window: Window,
    min_first_bbe: int,
    min_future_bbe: int,
) -> pd.DataFrame:
    first = bbe_stats(pitches, window.first_start, window.first_end, "first")
    future = bbe_stats(pitches, window.future_start, window.future_end, "future")
    xhr = hrt_stats(details, window.first_start, window.first_end, "first")
    future_hrt = hrt_stats(details, window.future_start, window.future_end, "future")
    rows = first.merge(xhr, on="batter", how="left").merge(
        future[
            [
                "batter",
                "futureBbe",
                "futureHr",
                "futureLa25_40_105Bbe",
                "futureEv90",
            ]
        ],
        on="batter",
        how="left",
    )
    rows = rows.merge(future_hrt, on="batter", how="left")
    if "firstAdjustedXhr" not in rows.columns:
        rows["firstAdjustedXhr"] = pd.NA
    if "firstHrCapableEvents" not in rows.columns:
        rows["firstHrCapableEvents"] = pd.NA
    rows["firstHrtMissing"] = rows["firstAdjustedXhr"].isna() & rows["firstHrCapableEvents"].isna()
    quarantine_rows: list[dict[str, Any]] = []
    quarantine_mask = []
    for _, row in rows.iterrows():
        should_quarantine, reason = is_missing_hrt_statcast_contradiction(
            hrt_missing=bool(row.get("firstHrtMissing")),
            bbe=row.get("firstBbe"),
            ev90=row.get("firstEv90"),
            thunder_bbe=row.get("firstLa25_40_105Bbe"),
            barrels=row.get("firstBarrels"),
            hr=row.get("firstHr"),
            min_bbe=min_first_bbe,
        )
        quarantine_mask.append(should_quarantine)
        if should_quarantine:
            batter_id = int(row["batter"]) if pd.notna(row.get("batter")) else None
            quarantine_rows.append(
                {
                    "batter": batter_id,
                    "player": names.get(batter_id, f"MLBAM {batter_id}") if batter_id else "unknown",
                    "firstBbe": int(row["firstBbe"]) if pd.notna(row.get("firstBbe")) else None,
                    "firstEv90": round(float(row["firstEv90"]), 1) if pd.notna(row.get("firstEv90")) else None,
                    "firstLa25_40_105Bbe": int(row["firstLa25_40_105Bbe"])
                    if pd.notna(row.get("firstLa25_40_105Bbe"))
                    else None,
                    "integrityReason": reason,
                }
            )
    if quarantine_rows:
        label = f"LBI diagnostic {window.label} {window.first_start:%Y-%m-%d}..{window.first_end:%Y-%m-%d}"
        print_integrity_quarantine(label, quarantine_rows)
        rows = rows.loc[[not flag for flag in quarantine_mask]].copy()
    for column in [
        "firstAdjustedXhr",
        "firstHrCapableEvents",
        "firstNoDoubterEvents",
        "firstMostlyGoneEvents",
        "firstDoubterEvents",
        "futureAdjustedXhr",
        "futureHrCapableEvents",
        "futureNoDoubterEvents",
        "futureMostlyGoneEvents",
        "futureDoubterEvents",
    ]:
        if column not in rows.columns:
            rows[column] = 0
        rows[column] = rows[column].fillna(0)
    rows["futureBbe"] = rows["futureBbe"].fillna(0)
    rows["futureHr"] = rows["futureHr"].fillna(0)
    rows = rows[rows["firstBbe"].ge(min_first_bbe) & rows["futureBbe"].ge(min_future_bbe)].copy()
    if rows.empty:
        return rows

    rows["xhrPerBbe"] = rows["firstAdjustedXhr"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["barrelRate"] = rows["firstBarrels"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["hardHitRate"] = rows["firstHardHitBbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["sweetSpotRate"] = rows["firstSweetSpotBbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["la25_40_100Rate"] = rows["firstLa25_40_100Bbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["la25_40_105Rate"] = rows["firstLa25_40_105Bbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["scaledThunderRate"] = rows["firstScaledThunderBbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["nearMissThunderRate"] = rows["firstNearMissThunderBbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["avgDistanceOnBarrels"] = rows["firstAvgDistanceOnBarrels"]
    rows["ev90"] = rows["firstEv90"]
    league_xhr_rate = rows["firstAdjustedXhr"].sum() / rows["firstBbe"].sum()
    league_thunder_rate = rows["firstLa25_40_105Bbe"].sum() / rows["firstBbe"].sum()
    league_ev90 = rows["ev90"].dropna().mean()
    rows["leagueXhrPerBbe"] = league_xhr_rate
    rows["leagueThunderRate"] = league_thunder_rate
    rows["leagueEv90"] = league_ev90
    for shrinkage in STORM_SHRINKAGE_GRID:
        rows[f"xhrPerBbeShrunkM{shrinkage}"] = (
            rows["firstAdjustedXhr"] + shrinkage * league_xhr_rate
        ) / (rows["firstBbe"] + shrinkage)
        rows[f"la25_40_105RateShrunkM{shrinkage}"] = (
            rows["firstLa25_40_105Bbe"] + shrinkage * league_thunder_rate
        ) / (rows["firstBbe"] + shrinkage)
        ev90_weight = rows["firstBbe"] / (rows["firstBbe"] + shrinkage)
        rows[f"ev90ShrunkM{shrinkage}"] = ev90_weight * rows["ev90"] + (1 - ev90_weight) * league_ev90
    rows["avgLaunchAngle"] = rows["firstAvgLaunchAngle"]
    rows["actualHrPerBbe"] = rows["firstHr"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["futureHrPerBbe"] = rows["futureHr"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["futureAdjustedXhrPerBbe"] = rows["futureAdjustedXhr"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["futureThunderRate"] = rows["futureLa25_40_105Bbe"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["futureHrCapableRate"] = rows["futureHrCapableEvents"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["futureNoDoubterRate"] = rows["futureNoDoubterEvents"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["firstHrCapableBucketEvents"] = (
        rows["firstNoDoubterEvents"] + rows["firstMostlyGoneEvents"] + rows["firstDoubterEvents"]
    )
    valid_no_doubter = rows["firstHrCapableBucketEvents"].gt(0)
    league_no_doubter_share = (
        rows.loc[valid_no_doubter, "firstNoDoubterEvents"].sum()
        / rows.loc[valid_no_doubter, "firstHrCapableBucketEvents"].sum()
        if valid_no_doubter.any()
        else 0.0
    )
    rows["noDoubterShareFallback"] = ~valid_no_doubter
    rows["leagueNoDoubterShare"] = league_no_doubter_share
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        rows[f"noDoubterShare_M{shrinkage}"] = (
            rows["firstNoDoubterEvents"] + shrinkage * league_no_doubter_share
        ) / (rows["firstHrCapableBucketEvents"] + shrinkage)
        rows.loc[~valid_no_doubter, f"noDoubterShare_M{shrinkage}"] = league_no_doubter_share
    rows["current_lbi_v12_proxy"] = current_lbi_v12_scores(rows)
    rows["candidate_lbi_la25_40_100"] = weighted_scores(rows, REQUESTED_LBI_WEIGHTS)
    rows["candidate_lbi_split_100_105"] = weighted_scores(rows, SPLIT_EV_LBI_WEIGHTS)
    rows["candidate_lbi_la25_40_105"] = weighted_scores(rows, PURE_105_LBI_WEIGHTS)
    rows["candidate_lbi_la25_40_105_15"] = weighted_scores(rows, PURE_105_15_LBI_WEIGHTS)
    rows["candidate_lbi_flipped_barrel_105"] = weighted_scores(rows, FLIPPED_BARREL_105_LBI_WEIGHTS)
    rows["candidate_lbi_xhr55_105_25"] = weighted_scores(rows, XHR_55_105_25_LBI_WEIGHTS)
    rows["candidate_lbi_xhr50_split"] = weighted_scores(rows, XHR_50_SPLIT_LBI_WEIGHTS)
    rows["candidate_lbi_xhr50_barrel"] = weighted_scores(rows, XHR_50_BARREL_LBI_WEIGHTS)
    rows["lbi_v13"] = rows["candidate_lbi_xhr50_barrel"]
    for component in LBI_V13_WEIGHTS:
        rows[f"lbi_v13_without_{component}"] = weighted_scores(rows, renormalized_without(LBI_V13_WEIGHTS, component))
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        rows[f"lbi_v2_clean_M{shrinkage}"] = weighted_scores(
            rows,
            {"xhrPerBbe": 0.70, f"noDoubterShare_M{shrinkage}": 0.30},
        )
        rows[f"lbi_v2_fingerprint_M{shrinkage}"] = weighted_scores(
            rows,
            {"xhrPerBbe": 0.60, f"noDoubterShare_M{shrinkage}": 0.30, "la25_40_105Rate": 0.10},
        )
    rows["candidate_lbi_xhr50_105"] = weighted_scores(rows, XHR_50_105_LBI_WEIGHTS)
    rows["candidate_lbi_no_hh_barrel25"] = weighted_scores(rows, NO_HH_BARREL_25_LBI_WEIGHTS)
    rows["candidate_lbi_no_hh_105_30"] = weighted_scores(rows, NO_HH_105_30_LBI_WEIGHTS)
    rows["candidate_lbi_conservative_middle"] = weighted_scores(rows, CONSERVATIVE_MIDDLE_LBI_WEIGHTS)
    rows["candidate_lbi_v14_thunder_30"] = weighted_scores(rows, THUNDER_30_LBI_WEIGHTS)
    rows["candidate_lbi_v14_thunder_35"] = weighted_scores(rows, THUNDER_35_LBI_WEIGHTS)
    rows["candidate_lbi_v14_thunder_375"] = weighted_scores(rows, THUNDER_375_LBI_WEIGHTS)
    rows["candidate_lbi_v14_heavy_thunder"] = weighted_scores(rows, HEAVY_THUNDER_LBI_WEIGHTS)
    rows["candidate_lbi_v14_scaled_window"] = weighted_scores(rows, SCALED_WINDOW_LBI_WEIGHTS)
    rows["candidate_lbi_v14_near_miss_floor"] = weighted_scores(rows, NEAR_MISS_FLOOR_LBI_WEIGHTS)
    for column, (_, weights) in EV90_FORMULAS.items():
        if column in rows.columns:
            continue
        rows[column] = weighted_scores(rows, weights)
    for column, (_, weights) in STORM_WATCH_FORMULAS.items():
        rows[column] = weighted_scores(rows, weights)
    for column, (_, weights) in STORM_PHASE2_FORMULAS.items():
        rows[column] = weighted_scores(rows, weights)
    rows["season"] = window.season
    rows["window"] = window.label
    rows["player"] = rows["batter"].map(lambda value: names.get(int(value), f"MLBAM {int(value)}"))
    return rows


def monthly_windows(season: int, pitches: pd.DataFrame, next_weeks: int) -> list[Window]:
    season_start = max(parse_date(f"{season}-03-01"), min(pitches["game_date"]))
    windows = []
    for month, day in CHECKPOINT_MONTH_DAYS:
        checkpoint = date(season, month, day)
        windows.append(
            Window(
                season=season,
                label=f"{checkpoint}_plus_{next_weeks}w",
                first_start=season_start,
                first_end=checkpoint,
                future_start=checkpoint + timedelta(days=1),
                future_end=checkpoint + timedelta(weeks=next_weeks),
            )
        )
    return windows


def rest_of_season_windows(season: int, pitches: pd.DataFrame) -> list[Window]:
    season_start = max(parse_date(f"{season}-03-01"), min(pitches["game_date"]))
    season_end = min(parse_date(SPLITS[season][3]), max(pitches["game_date"]))
    windows = []
    for month, day in CHECKPOINT_MONTH_DAYS:
        checkpoint = date(season, month, day)
        if checkpoint >= season_end:
            continue
        windows.append(
            Window(
                season=season,
                label=f"{checkpoint}_rest_of_season",
                first_start=season_start,
                first_end=checkpoint,
                future_start=checkpoint + timedelta(days=1),
                future_end=season_end,
            )
        )
    return windows


def all_star_window(season: int) -> Window:
    first_start, first_end, future_start, future_end = [parse_date(value) for value in SPLITS[season]]
    return Window(
        season=season,
        label="all_star_first_to_second_half",
        first_start=first_start,
        first_end=first_end,
        future_start=future_start,
        future_end=future_end,
    )


def rmse(predicted: pd.Series, actual: pd.Series) -> float:
    diff = (predicted - actual).dropna()
    return math.sqrt(float((diff**2).mean())) if len(diff) else float("nan")


def top_decile_lift(rows: pd.DataFrame, metric: str, target: str) -> float | None:
    data = rows[[metric, target]].dropna()
    if data.empty:
        return None
    cutoff = data[metric].quantile(0.90)
    top = data[data[metric].ge(cutoff)]
    if top.empty:
        return None
    baseline = data[target].mean()
    if not baseline:
        return None
    return float((top[target].mean() / baseline) - 1)


def metric_report(rows: pd.DataFrame, target: str) -> pd.DataFrame:
    metrics = {
        "current_lbi_v12_proxy": "Current LBI v1.2 proxy",
        "candidate_lbi_la25_40_100": "Requested LA 25-40 / 100+ LBI",
        "candidate_lbi_split_100_105": "Split LA 25-40 / 100+ and 105+ LBI",
        "candidate_lbi_la25_40_105": "Pure LA 25-40 / 105+ LBI",
        "candidate_lbi_la25_40_105_15": "Pure LA 25-40 / 105+ LBI at 15%",
        "candidate_lbi_flipped_barrel_105": "Flipped Barrel and 105+ LBI",
        "candidate_lbi_xhr55_105_25": "55% xHR / 25% 105+ LBI",
        "candidate_lbi_xhr50_split": "50% xHR / split 5 points LBI",
        "candidate_lbi_xhr50_barrel": "50% xHR / 5 points to Barrel LBI",
        "candidate_lbi_xhr50_105": "50% xHR / 5 points to 105+ LBI",
        "candidate_lbi_no_hh_barrel25": "No Hard Hit / 25% Barrel LBI",
        "candidate_lbi_no_hh_105_30": "No Hard Hit / 30% 105+ LBI",
        "candidate_lbi_conservative_middle": "Conservative Middle 55/20/20/5 LBI",
        "candidate_lbi_v14_thunder_30": "v1.4 Thunder Ladder 47.5/17.5/30/5",
        "candidate_lbi_v14_thunder_35": "v1.4 Thunder Ladder 45/15/35/5",
        "candidate_lbi_v14_thunder_375": "v1.4 Thunder Ladder 42.5/12.5/37.5/7.5",
        "candidate_lbi_v14_heavy_thunder": "v1.4 Heavy Thunder 40/10/40/10",
        "candidate_lbi_v14_scaled_window": "v1.4 Scaled-Window Thunder",
        "candidate_lbi_v14_near_miss_floor": "v1.4 Near-Miss Thunder Floor",
        "xhrPerBbe": "Adjusted xHR/BBE",
        "barrelRate": "Barrel%",
        "la25_40_100Rate": "LA 25-40 at 100+ / BBE",
        "la25_40_105Rate": "LA 25-40 at 105+ / BBE",
        "scaledThunderRate": "Scaled-window Thunder / BBE",
        "nearMissThunderRate": "Near-Miss Thunder / BBE",
        "hardHitRate": "Hard Hit%",
        "actualHrPerBbe": "Actual HR/BBE to date",
    }
    report = []
    for column, label in metrics.items():
        data = rows[[column, target]].dropna()
        if len(data) < 3:
            continue
        report.append(
            {
                "metric": label,
                "column": column,
                "n": int(len(data)),
                "pearson": data[column].corr(data[target], method="pearson"),
                "spearman": data[column].corr(data[target], method="spearman"),
                "rmse": rmse(data[column], data[target]) if column.endswith("Rate") or column == "xhrPerBbe" else None,
                "topDecileLift": top_decile_lift(rows, column, target),
                "top25Target": rows.nlargest(25, column)[target].mean() if len(rows[[column, target]].dropna()) >= 25 else None,
            }
        )
    return pd.DataFrame(report)


def print_core_report(title: str, rows: pd.DataFrame, target: str) -> None:
    print(f"\n=== {title}: Requested A-F Formulas ===")
    report = metric_report(rows, target).set_index("column")
    for column, label in CORE_FORMULAS.items():
        if column not in report.index:
            continue
        row = report.loc[column]
        lift = "n/a" if pd.isna(row["topDecileLift"]) else f"{row['topDecileLift'] * 100:+.1f}%"
        top25 = "n/a" if pd.isna(row["top25Target"]) else f"{row['top25Target'] * 100:.2f}%"
        print(
            f"{label:<58} n={int(row['n']):4d} | pearson {row['pearson']:.3f} | "
            f"spearman {row['spearman']:.3f} | top-decile lift {lift} | top-25 {top25}"
        )


def print_report(title: str, report: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    for _, row in report.sort_values("pearson", ascending=False).iterrows():
        lift = "n/a" if pd.isna(row["topDecileLift"]) else f"{row['topDecileLift'] * 100:+.1f}%"
        top25 = "n/a" if pd.isna(row["top25Target"]) else f"{row['top25Target'] * 100:.2f}%"
        print(
            f"{row['metric']:<32} n={int(row['n']):4d} | pearson {row['pearson']:.3f} | "
            f"spearman {row['spearman']:.3f} | top-decile lift {lift} | top-25 future {top25}"
        )


def checkpoint_correlations(rows: pd.DataFrame, left: str, right: str) -> pd.DataFrame:
    records = []
    for (season, window), frame in rows.groupby(["season", "window"]):
        data = frame[[left, right]].dropna()
        if len(data) < 3:
            continue
        records.append(
            {
                "season": int(season),
                "window": str(window),
                "n": int(len(data)),
                "pearson": data[left].corr(data[right], method="pearson"),
                "spearman": data[left].corr(data[right], method="spearman"),
            }
        )
    return pd.DataFrame(records)


def add_checkpoint_zscores(rows: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    output = rows.copy()
    for feature in features:
        z_column = f"z_{feature}"
        output[z_column] = pd.NA
        for _, index in output.groupby(["season", "window"]).groups.items():
            values = pd.to_numeric(output.loc[index, feature], errors="coerce")
            mean = values.mean()
            std = values.std(ddof=0)
            if not std or pd.isna(std):
                output.loc[index, z_column] = 0.0
            else:
                output.loc[index, z_column] = (values - mean) / std
        output[z_column] = pd.to_numeric(output[z_column], errors="coerce")
    return output


def print_feature_correlation_matrix(rows: pd.DataFrame) -> None:
    z_features = [f"z_{feature}" for feature in DESCRIPTIVE_FEATURES]
    labels = [DESCRIPTIVE_FEATURE_LABELS[feature] for feature in DESCRIPTIVE_FEATURES]
    matrix = rows[z_features].corr(method="pearson")
    matrix.index = labels
    matrix.columns = labels
    print("\n=== Feature-to-Feature Pearson Correlation Matrix (checkpoint z-scores, pooled) ===")
    print(matrix.round(3).to_string())


def print_collinearity_audit(monthly: pd.DataFrame) -> dict[str, Any]:
    print("\n=== PART 1A: v1.3 LBI vs Raw Adjusted xHR/BBE ===")
    print("Component normalization: plus-style percentile scoring within each eligible checkpoint pool, not z-score.")
    corr = checkpoint_correlations(monthly, "lbi_v13", "xhrPerBbe")
    for season, frame in corr.groupby("season"):
        print(
            f"{season}: Pearson {frame['pearson'].mean():.3f} | "
            f"Spearman {frame['spearman'].mean():.3f} | checkpoints {len(frame)}"
        )
    avg_pearson = corr["pearson"].mean()
    avg_spearman = corr["spearman"].mean()
    print(f"Average: Pearson {avg_pearson:.3f} | Spearman {avg_spearman:.3f}")

    print("\n=== PART 1B: Drop-One-Out Rank Audit vs Full v1.3 LBI ===")
    records = []
    final_2025 = monthly[
        monthly["season"].eq(2025)
        & monthly["window"].astype("string").str.contains("2025-08-01", regex=False, na=False)
    ].copy()
    for component, label in LBI_V13_COMPONENTS.items():
        column = f"lbi_v13_without_{component}"
        component_corr = checkpoint_correlations(monthly, "lbi_v13", column)
        final_data = final_2025[["lbi_v13", column]].dropna()
        final_spearman = (
            final_data["lbi_v13"].corr(final_data[column], method="spearman")
            if len(final_data) >= 3
            else float("nan")
        )
        avg = component_corr["spearman"].mean()
        movement = 1 - avg
        records.append(
            {
                "component": component,
                "label": label,
                "avgSpearman": avg,
                "movement": movement,
                "final2025Spearman": final_spearman,
            }
        )
    for row in sorted(records, key=lambda item: item["movement"], reverse=True):
        print(
            f"Remove {row['label']:<24} avg Spearman {row['avgSpearman']:.3f} | "
            f"movement {row['movement']:.3f} | final 2025 Spearman {row['final2025Spearman']:.3f}"
        )
    cosmetic = [row for row in records if row["avgSpearman"] >= 0.98]
    if avg_spearman >= 0.95 or len(cosmetic) >= 2:
        print(
            "\nPart 1 stop condition triggered: "
            f"v1.3/xHR Spearman >= 0.95 is {avg_spearman >= 0.95}; "
            f"cosmetic components >=2 is {len(cosmetic) >= 2} ({len(cosmetic)} components)."
        )
    return {
        "avgPearson": avg_pearson,
        "avgSpearman": avg_spearman,
        "dropOne": records,
        "cosmeticCount": len(cosmetic),
    }


def model_metrics(rows: pd.DataFrame, model: str, target: str) -> dict[str, Any]:
    data = rows[[model, target]].dropna()
    return {
        "n": int(len(data)),
        "pearson": data[model].corr(data[target], method="pearson") if len(data) >= 3 else float("nan"),
        "spearman": data[model].corr(data[target], method="spearman") if len(data) >= 3 else float("nan"),
        "rmse": rmse(data[model], data[target]) if len(data) else float("nan"),
        "topDecileLift": top_decile_lift(rows, model, target),
        "top25Target": rows.nlargest(25, model)[target].mean() if len(data) >= 25 else float("nan"),
    }


def print_metric_line(label: str, metrics: dict[str, Any], as_rate: bool = True) -> None:
    lift = "n/a" if pd.isna(metrics["topDecileLift"]) else f"{metrics['topDecileLift'] * 100:+.1f}%"
    top25 = "n/a" if pd.isna(metrics["top25Target"]) else (
        f"{metrics['top25Target'] * 100:.2f}%" if as_rate else f"{metrics['top25Target']:.3f}"
    )
    print(
        f"{label:<34} n={metrics['n']:4d} | Pearson {metrics['pearson']:.3f} | "
        f"Spearman {metrics['spearman']:.3f} | top-decile {lift} | top-25 {top25}"
    )


def score_volatility(rows: pd.DataFrame, model: str, start_token: str = "-05-01", end_token: str = "-06-01") -> dict[str, float]:
    pieces = []
    for season, frame in rows.groupby("season"):
        start = frame[frame["window"].astype("string").str.contains(start_token, regex=False, na=False)].copy()
        end = frame[frame["window"].astype("string").str.contains(end_token, regex=False, na=False)].copy()
        if start.empty or end.empty:
            continue
        start["rank"] = start[model].rank(method="average", ascending=False)
        end["rank"] = end[model].rank(method="average", ascending=False)
        merged = start[["batter", model, "rank"]].merge(
            end[["batter", model, "rank"]],
            on="batter",
            suffixes=("_start", "_end"),
        )
        if merged.empty:
            continue
        merged["absScoreDelta"] = (merged[f"{model}_end"] - merged[f"{model}_start"]).abs()
        merged["absRankDelta"] = (merged["rank_end"] - merged["rank_start"]).abs()
        pieces.append(merged)
    if not pieces:
        return {"n": 0, "avgScoreDelta": float("nan"), "avgRankDelta": float("nan"), "p90RankDelta": float("nan")}
    combined = pd.concat(pieces, ignore_index=True)
    return {
        "n": int(len(combined)),
        "avgScoreDelta": combined["absScoreDelta"].mean(),
        "avgRankDelta": combined["absRankDelta"].mean(),
        "p90RankDelta": combined["absRankDelta"].quantile(0.90),
    }


def print_v2_diagnostics(monthly: pd.DataFrame, all_star: pd.DataFrame) -> None:
    print("\n=== PART 2: No-Doubter Share Data Integrity ===")
    total_rows = len(monthly)
    fallback_rows = int(monthly["noDoubterShareFallback"].sum())
    print(
        f"Monthly rows: {total_rows}; no HR-capable bucket rows using league-average no-doubter fallback: "
        f"{fallback_rows} ({fallback_rows / total_rows * 100:.1f}%)."
    )
    print(
        "Rows with hr_capable_bbe == 0 do not receive a false no-doubter share; "
        "they fall back to the checkpoint league-average share and are flagged."
    )

    models = {
        "v1.3": "lbi_v13",
        "raw xHR/BBE": "xhrPerBbe",
    }
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        models[f"v2_clean M={shrinkage}"] = f"lbi_v2_clean_M{shrinkage}"
        models[f"v2_fingerprint M={shrinkage}"] = f"lbi_v2_fingerprint_M{shrinkage}"

    print("\n=== PART 3A: Independence from Raw Adjusted xHR/BBE ===")
    for label, column in models.items():
        if column == "xhrPerBbe":
            continue
        corr = checkpoint_correlations(monthly, column, "xhrPerBbe")
        print(
            f"{label:<24} Pearson {corr['pearson'].mean():.3f} | "
            f"Spearman {corr['spearman'].mean():.3f}"
        )

    may = monthly[monthly["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    print("\n=== PART 3B: May 1 Early-Season Stability vs Future HR/BBE ===")
    may_models = {"v1.3": "lbi_v13"}
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        may_models[f"v2_clean M={shrinkage}"] = f"lbi_v2_clean_M{shrinkage}"
        may_models[f"v2_fingerprint M={shrinkage}"] = f"lbi_v2_fingerprint_M{shrinkage}"
    for label, column in may_models.items():
        metrics = model_metrics(may, column, "futureHrPerBbe")
        volatility = score_volatility(monthly, column)
        print_metric_line(label, metrics)
        print(
            f"  May->June volatility: n={volatility['n']} | avg score delta {volatility['avgScoreDelta']:.1f} | "
            f"avg rank delta {volatility['avgRankDelta']:.1f} | p90 rank delta {volatility['p90RankDelta']:.1f}"
        )

    print("\n=== PART 3C: Descriptive Fidelity - Monthly Contact-Quality Continuity ===")
    targets = [
        ("futureAdjustedXhrPerBbe", "Future adjusted xHR/BBE"),
        ("futureHrCapableRate", "Future HR-capable rate"),
        ("futureNoDoubterRate", "Future no-doubter rate"),
    ]
    focus_models = {"v1.3": "lbi_v13"}
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        focus_models[f"v2_clean M={shrinkage}"] = f"lbi_v2_clean_M{shrinkage}"
        focus_models[f"v2_fingerprint M={shrinkage}"] = f"lbi_v2_fingerprint_M{shrinkage}"
    for target, target_label in targets:
        print(f"\n-- {target_label} --")
        for label, column in focus_models.items():
            print_metric_line(label, model_metrics(monthly, column, target))

    print("\n=== PART 3D: Secondary Future HR/BBE Reference ===")
    for label, column in focus_models.items():
        print_metric_line(label, model_metrics(monthly, column, "futureHrPerBbe"))

    print("\n=== All-Star Split Contact-Quality Reference ===")
    for target, target_label in targets:
        print(f"\n-- {target_label} --")
        for label, column in focus_models.items():
            print_metric_line(label, model_metrics(all_star, column, target))


def print_side_by_side_boards(rows: pd.DataFrame, season: int, model: str, title: str) -> None:
    final = rows[
        rows["season"].eq(season)
        & rows["window"].astype("string").str.contains(f"{season}-08-01", regex=False, na=False)
    ].copy()
    if final.empty:
        final = rows[rows["season"].eq(season)].copy()
    if final.empty:
        return
    final["rank_v13"] = final["lbi_v13"].rank(method="average", ascending=False)
    final["rank_v2"] = final[model].rank(method="average", ascending=False)
    final["rank_change"] = final["rank_v13"] - final["rank_v2"]
    print(f"\n=== PART 3E: {title} Top 30 Side by Side ({season}) ===")
    v13 = final.sort_values("lbi_v13", ascending=False).head(30).reset_index(drop=True)
    v2 = final.sort_values(model, ascending=False).head(30).reset_index(drop=True)
    for index in range(30):
        left = v13.iloc[index]
        right = v2.iloc[index]
        print(
            f"{index + 1:2}. v1.3 {left['player']:<24} {left['lbi_v13']:6.1f} | "
            f"v2 {right['player']:<24} {right[model]:6.1f} | "
            f"xHR {right['xhrPerBbe'] * 100:.2f}% | ND share {right.get('noDoubterShare_M10', 0) * 100:.1f}%"
        )
    print(f"\nBiggest risers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=False).head(15).iterrows():
        print(
            f"+{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"v2 rank {row['rank_v2']:.0f} | v1.3 {row['lbi_v13']:.1f} | v2 {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | ND {row['firstNoDoubterEvents']:.0f}/{row['firstHrCapableBucketEvents']:.0f}"
        )
    print(f"\nBiggest fallers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=True).head(15).iterrows():
        print(
            f"{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"v2 rank {row['rank_v2']:.0f} | v1.3 {row['lbi_v13']:.1f} | v2 {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | ND {row['firstNoDoubterEvents']:.0f}/{row['firstHrCapableBucketEvents']:.0f}"
        )


def best_clean_shrinkage_by_stability(rows: pd.DataFrame) -> int:
    scored = []
    for shrinkage in NO_DOUBTER_SHRINKAGE_GRID:
        model = f"lbi_v2_clean_M{shrinkage}"
        volatility = score_volatility(rows, model)
        scored.append((volatility["avgRankDelta"], volatility["avgScoreDelta"], shrinkage))
    scored = [item for item in scored if not pd.isna(item[0])]
    if not scored:
        return 10
    return int(sorted(scored)[0][2])


def fit_regularized_model(model_name: str, train: pd.DataFrame, x_columns: list[str], target: str):
    if LassoCV is None or RidgeCV is None or ElasticNetCV is None:
        raise RuntimeError("scikit-learn is required for the LBI descriptive-factor closure test.")
    x = train[x_columns].astype(float)
    y = train[target].astype(float)
    cv = min(5, max(2, train["season"].nunique()))
    if model_name == "lasso":
        return LassoCV(cv=cv, random_state=42, max_iter=50000).fit(x, y)
    if model_name == "ridge":
        return RidgeCV(alphas=[0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100], cv=cv).fit(x, y)
    if model_name == "elastic_net":
        return ElasticNetCV(
            l1_ratio=[0.1, 0.25, 0.5, 0.75, 0.9],
            cv=cv,
            random_state=42,
            max_iter=50000,
        ).fit(x, y)
    raise ValueError(model_name)


def correlation_pair(predicted: pd.Series, actual: pd.Series) -> tuple[float, float]:
    data = pd.DataFrame({"predicted": predicted, "actual": actual}).dropna()
    if len(data) < 3:
        return float("nan"), float("nan")
    return (
        data["predicted"].corr(data["actual"], method="pearson"),
        data["predicted"].corr(data["actual"], method="spearman"),
    )


def print_regularized_closure_test(monthly: pd.DataFrame) -> None:
    if LassoCV is None:
        print("\nscikit-learn unavailable; skipping regularized closure test.")
        return
    z_features = [f"z_{feature}" for feature in DESCRIPTIVE_FEATURES]
    labels = [DESCRIPTIVE_FEATURE_LABELS[feature] for feature in DESCRIPTIVE_FEATURES]
    targets = [
        ("futureAdjustedXhrPerBbe", "future adjusted xHR/BBE"),
        ("futureHrCapableRate", "future HR-capable rate"),
    ]
    tertiary = ("futureNoDoubterRate", "future no-doubter rate")
    print("\n=== Leakage Discipline ===")
    print(
        "All model inputs are to-date checkpoint features. Targets are disjoint forward windows "
        "after the checkpoint. No feature shares its window with its target."
    )
    print("Excluded features: no-doubter share (sparse denominator), pull/spray (redundant and park-biased), bat tracking (2024+ only).")
    print_feature_correlation_matrix(monthly)

    model_names = ["lasso", "ridge", "elastic_net"]
    for target, target_label in [*targets, tertiary]:
        print(f"\n=== Regularized Leave-One-Season-Out: {target_label} ===")
        oos_predictions: dict[str, pd.Series] = {name: pd.Series(index=monthly.index, dtype=float) for name in model_names}
        coefficient_records: dict[str, list[dict[str, Any]]] = {name: [] for name in model_names}
        survival: dict[str, dict[str, int]] = {
            "lasso": {feature: 0 for feature in DESCRIPTIVE_FEATURES},
            "elastic_net": {feature: 0 for feature in DESCRIPTIVE_FEATURES},
        }
        for holdout in sorted(monthly["season"].unique()):
            train = monthly[monthly["season"].ne(holdout)].dropna(subset=[*z_features, target]).copy()
            test = monthly[monthly["season"].eq(holdout)].dropna(subset=[*z_features, target]).copy()
            if train.empty or test.empty:
                continue
            print(f"\nHoldout {int(holdout)}")
            for model_name in model_names:
                model = fit_regularized_model(model_name, train, z_features, target)
                coef = pd.Series(model.coef_, index=DESCRIPTIVE_FEATURES)
                for feature, value in coef.items():
                    coefficient_records[model_name].append(
                        {"holdout": int(holdout), "feature": feature, "coefficient": float(value)}
                    )
                    if model_name in survival and abs(float(value)) > 1e-8:
                        survival[model_name][feature] += 1
                oos_predictions[model_name].loc[test.index] = model.predict(test[z_features].astype(float))
                coef_text = ", ".join(
                    f"{DESCRIPTIVE_FEATURE_LABELS[feature]} {coef[feature]:+.4f}" for feature in DESCRIPTIVE_FEATURES
                )
                print(f"  {model_name}: {coef_text}")

        print("\nPooled coefficient means")
        for model_name in model_names:
            coef_frame = pd.DataFrame(coefficient_records[model_name])
            means = coef_frame.groupby("feature")["coefficient"].mean()
            text = ", ".join(
                f"{DESCRIPTIVE_FEATURE_LABELS[feature]} {means.get(feature, float('nan')):+.4f}"
                for feature in DESCRIPTIVE_FEATURES
            )
            print(f"  {model_name}: {text}")

        if target in {"futureAdjustedXhrPerBbe", "futureHrCapableRate"}:
            print("\nSelection stability")
            for model_name in ["lasso", "elastic_net"]:
                text = ", ".join(
                    f"{DESCRIPTIVE_FEATURE_LABELS[feature]} {survival[model_name][feature]}/5"
                    for feature in DESCRIPTIVE_FEATURES
                )
                print(f"  {model_name}: {text}")

            print("\nOut-of-sample performance")
            for model_name in model_names:
                pearson, spearman = correlation_pair(oos_predictions[model_name], monthly[target])
                print(f"  {model_name:<12} Pearson {pearson:.3f} | Spearman {spearman:.3f}")
            for label, prediction in [
                ("v1.3", monthly["lbi_v13"]),
                ("xHR+Thunder 70/30", 0.70 * monthly["z_xhrPerBbe"] + 0.30 * monthly["z_la25_40_105Rate"]),
                ("xHR+Thunder 65/35", 0.65 * monthly["z_xhrPerBbe"] + 0.35 * monthly["z_la25_40_105Rate"]),
                ("xHR+Thunder 60/40", 0.60 * monthly["z_xhrPerBbe"] + 0.40 * monthly["z_la25_40_105Rate"]),
            ]:
                pearson, spearman = correlation_pair(prediction, monthly[target])
                print(f"  {label:<18} Pearson {pearson:.3f} | Spearman {spearman:.3f}")


def print_may_drop_one_stability(monthly: pd.DataFrame) -> None:
    print("\n=== May 1 Drop-One-Out Stability Side-Check ===")
    print("Volatility is May 1 to June 1 rank movement among players present in both checkpoints.")
    models = {"Full v1.3": "lbi_v13"}
    for component, label in LBI_V13_COMPONENTS.items():
        models[f"Without {label}"] = f"lbi_v13_without_{component}"
    for label, column in models.items():
        volatility = score_volatility(monthly, column)
        may = monthly[monthly["window"].astype("string").str.contains("-05-01", regex=False, na=False)]
        metrics = model_metrics(may, column, "futureAdjustedXhrPerBbe")
        print(
            f"{label:<32} avg rank delta {volatility['avgRankDelta']:.1f} | "
            f"p90 rank delta {volatility['p90RankDelta']:.1f} | "
            f"May future xHR/BBE Pearson {metrics['pearson']:.3f} | Spearman {metrics['spearman']:.3f}"
        )


def per_season_and_pooled(rows: pd.DataFrame, model: str, target: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_season = []
    for season, frame in rows.groupby("season"):
        per_season.append({"season": int(season), **model_metrics(frame, model, target)})
    return per_season, model_metrics(rows, model, target)


def print_ev90_metric_table(
    title: str,
    rows: pd.DataFrame,
    target: str,
    models: list[str],
    include_top_stats: bool = False,
) -> dict[str, dict[str, Any]]:
    print(f"\n=== {title} ===")
    pooled: dict[str, dict[str, Any]] = {}
    for model in models:
        label = EV90_FORMULAS[model][0]
        per_season, overall = per_season_and_pooled(rows, model, target)
        pooled[model] = overall
        season_text = " | ".join(
            f"{row['season']} P {row['pearson']:.3f} S {row['spearman']:.3f}"
            for row in per_season
        )
        print(f"{label}")
        if include_top_stats:
            print_metric_line("  pooled", overall)
        else:
            print(f"  pooled n={overall['n']} | Pearson {overall['pearson']:.3f} | Spearman {overall['spearman']:.3f}")
        print(f"  by season: {season_text}")
    return pooled


def best_ev90_candidate_by_descriptive(monthly: pd.DataFrame) -> str:
    scores = []
    for model in EV90_CANDIDATE_COLUMNS:
        x = model_metrics(monthly, model, "futureAdjustedXhrPerBbe")
        h = model_metrics(monthly, model, "futureHrCapableRate")
        scores.append((x["pearson"] + x["spearman"] + h["pearson"] + h["spearman"], model))
    return sorted(scores, reverse=True)[0][1]


def print_ev90_stability(monthly: pd.DataFrame, models: list[str]) -> None:
    may = monthly[monthly["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    print("\n=== PART 3: May 1 Stability / Descriptive Targets ===")
    for model in models:
        label = EV90_FORMULAS[model][0]
        x = model_metrics(may, model, "futureAdjustedXhrPerBbe")
        h = model_metrics(may, model, "futureHrCapableRate")
        volatility = score_volatility(monthly, model)
        print(
            f"{label:<52} xHR P/S {x['pearson']:.3f}/{x['spearman']:.3f} | "
            f"HR-cap P/S {h['pearson']:.3f}/{h['spearman']:.3f} | "
            f"avg rank delta {volatility['avgRankDelta']:.1f} | p90 {volatility['p90RankDelta']:.1f}"
        )


def print_ev90_side_by_side(rows: pd.DataFrame, season: int, model: str) -> None:
    final = rows[
        rows["season"].eq(season)
        & rows["window"].astype("string").str.contains(f"{season}-08-01", regex=False, na=False)
    ].copy()
    if final.empty:
        return
    final["rank_v13"] = final["lbi_v13"].rank(method="average", ascending=False)
    final["rank_ev90"] = final[model].rank(method="average", ascending=False)
    final["rank_change"] = final["rank_v13"] - final["rank_ev90"]
    print(f"\n=== PART 4: v1.3 vs {EV90_FORMULAS[model][0]} Top 30 ({season} final checkpoint) ===")
    v13 = final.sort_values("lbi_v13", ascending=False).head(30).reset_index(drop=True)
    ev90 = final.sort_values(model, ascending=False).head(30).reset_index(drop=True)
    for index in range(30):
        left = v13.iloc[index]
        right = ev90.iloc[index]
        print(
            f"{index + 1:2}. v1.3 {left['player']:<24} {left['lbi_v13']:6.1f} | "
            f"EV90 {right['player']:<24} {right[model]:6.1f} | "
            f"xHR {right['xhrPerBbe'] * 100:.2f}% | EV90 {right['ev90']:.1f} | "
            f"Thunder {right['la25_40_105Rate'] * 100:.1f}%"
        )
    print(f"\nBiggest risers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=False).head(15).iterrows():
        print(
            f"+{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"EV90 rank {row['rank_ev90']:.0f} | v1.3 {row['lbi_v13']:.1f} | EV90 {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | EV90 {row['ev90']:.1f} | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )
    print(f"\nBiggest fallers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=True).head(15).iterrows():
        print(
            f"{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"EV90 rank {row['rank_ev90']:.0f} | v1.3 {row['lbi_v13']:.1f} | EV90 {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | EV90 {row['ev90']:.1f} | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )


def print_ev90_diagnostic(monthly: pd.DataFrame, rest_monthly: pd.DataFrame) -> None:
    print("\n=== EV90-Focused LBI Diagnostic ===")
    print("Scoring: plus-style percentile component scoring within each checkpoint pool, same as v1.3/public LBI.")
    print("Leakage: all inputs are checkpoint-to-date only; future targets are disjoint forward windows.")
    print("EV90 is the to-date 90th-percentile launch_speed within each checkpoint.")
    models = ["lbi_v13", "lbi_two_factor_xhr70_thunder30", *EV90_CANDIDATE_COLUMNS]

    print("\n--- PART 1: Marginal Descriptive Lift over xHR+Thunder ---")
    desc_x = print_ev90_metric_table(
        "Future adjusted xHR/BBE, 6-week forward", monthly, "futureAdjustedXhrPerBbe", models
    )
    desc_h = print_ev90_metric_table(
        "Future HR-capable rate, 6-week forward", monthly, "futureHrCapableRate", models
    )

    print("\n--- PART 2: Predictive Actual HR/BBE Arm ---")
    pred_models = [*models, "candidate_lbi_v14_heavy_thunder"]
    pred_6w = print_ev90_metric_table(
        "Future actual HR/BBE, 6-week forward", monthly, "futureHrPerBbe", pred_models, include_top_stats=True
    )
    pred_ros = print_ev90_metric_table(
        "Future actual HR/BBE, rest of season", rest_monthly, "futureHrPerBbe", pred_models, include_top_stats=True
    )

    best = best_ev90_candidate_by_descriptive(monthly)
    print_ev90_stability(monthly, ["lbi_v13", "lbi_two_factor_xhr70_thunder30", best])
    print_ev90_side_by_side(monthly, 2024, best)
    print_ev90_side_by_side(monthly, 2025, best)

    base_desc = desc_x["lbi_two_factor_xhr70_thunder30"]["pearson"] + desc_h["lbi_two_factor_xhr70_thunder30"]["pearson"]
    best_desc = desc_x[best]["pearson"] + desc_h[best]["pearson"]
    base_pred = pred_6w["lbi_two_factor_xhr70_thunder30"]["pearson"] + pred_ros["lbi_two_factor_xhr70_thunder30"]["pearson"]
    best_pred = pred_6w[best]["pearson"] + pred_ros[best]["pearson"]
    print("\n=== PART 5: Recommendation Inputs ===")
    print(
        f"Best EV90 candidate by descriptive targets: {EV90_FORMULAS[best][0]}."
    )
    print(
        f"Descriptive Pearson lift over two_factor: {(best_desc - base_desc):+.3f} "
        f"(combined future xHR + HR-capable Pearson)."
    )
    print(
        f"Predictive Pearson lift over two_factor: {(best_pred - base_pred):+.3f} "
        f"(combined 6-week + rest-of-season future HR/BBE Pearson)."
    )


IDENTITY_MODELS = [
    "lbi_v13",
    "lbi_two_factor_xhr75_thunder25",
    "lbi_two_factor_xhr70_thunder30",
    "lbi_two_factor_xhr65_thunder35",
    "lbi_two_factor_xhr60_thunder40",
    "lbi_ev90_B",
    "candidate_lbi_v14_heavy_thunder",
]


def print_identity_metric_table(
    title: str,
    rows: pd.DataFrame,
    target: str,
    include_top_stats: bool = False,
) -> dict[str, dict[str, Any]]:
    print(f"\n=== {title} ===")
    results: dict[str, dict[str, Any]] = {}
    for model in IDENTITY_MODELS:
        label = EV90_FORMULAS[model][0]
        per_season, overall = per_season_and_pooled(rows, model, target)
        results[model] = overall
        if include_top_stats:
            print_metric_line(label, overall)
        else:
            print(f"{label:<62} n={overall['n']} | Pearson {overall['pearson']:.3f} | Spearman {overall['spearman']:.3f}")
        print(
            "  by season: "
            + " | ".join(f"{row['season']} P {row['pearson']:.3f} S {row['spearman']:.3f}" for row in per_season)
        )
    return results


def print_identity_correlations(rows: pd.DataFrame) -> None:
    print("\n=== Candidate Similarity / Identity Check ===")
    print("Pooled correlation with raw checkpoint adjusted xHR/BBE and production v1.3.")
    for model in IDENTITY_MODELS:
        label = EV90_FORMULAS[model][0]
        px, sx = correlation_pair(rows[model], rows["xhrPerBbe"])
        pv, sv = correlation_pair(rows[model], rows["lbi_v13"])
        print(
            f"{label:<62} vs raw xHR P/S {px:.3f}/{sx:.3f} | "
            f"vs v1.3 P/S {pv:.3f}/{sv:.3f}"
        )

    final_2025 = rows[
        rows["season"].eq(2025)
        & rows["window"].astype("string").str.contains("2025-08-01", regex=False, na=False)
    ]
    if not final_2025.empty:
        print("\n2025 final checkpoint only:")
        for model in IDENTITY_MODELS:
            label = EV90_FORMULAS[model][0]
            px, sx = correlation_pair(final_2025[model], final_2025["xhrPerBbe"])
            pv, sv = correlation_pair(final_2025[model], final_2025["lbi_v13"])
            print(
                f"{label:<62} vs raw xHR P/S {px:.3f}/{sx:.3f} | "
                f"vs v1.3 P/S {pv:.3f}/{sv:.3f}"
            )


def best_two_factor_by_descriptive(monthly: pd.DataFrame) -> str:
    candidates = [
        "lbi_two_factor_xhr75_thunder25",
        "lbi_two_factor_xhr70_thunder30",
        "lbi_two_factor_xhr65_thunder35",
        "lbi_two_factor_xhr60_thunder40",
    ]
    scored = []
    for model in candidates:
        x = model_metrics(monthly, model, "futureAdjustedXhrPerBbe")
        h = model_metrics(monthly, model, "futureHrCapableRate")
        scored.append((x["pearson"] + x["spearman"] + h["pearson"] + h["spearman"], model))
    return sorted(scored, reverse=True)[0][1]


def print_identity_stability(monthly: pd.DataFrame, models: list[str]) -> None:
    may = monthly[monthly["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    print("\n=== May 1 Descriptive Stability ===")
    for model in models:
        label = EV90_FORMULAS[model][0]
        x = model_metrics(may, model, "futureAdjustedXhrPerBbe")
        h = model_metrics(may, model, "futureHrCapableRate")
        n = model_metrics(may, model, "futureNoDoubterRate")
        volatility = score_volatility(monthly, model)
        print(
            f"{label:<62} xHR {x['pearson']:.3f}/{x['spearman']:.3f} | "
            f"HR-cap {h['pearson']:.3f}/{h['spearman']:.3f} | "
            f"ND {n['pearson']:.3f}/{n['spearman']:.3f} | "
            f"avg rank delta {volatility['avgRankDelta']:.1f} | p90 {volatility['p90RankDelta']:.1f}"
        )


def print_identity_side_by_side(rows: pd.DataFrame, season: int, model: str) -> None:
    final = rows[
        rows["season"].eq(season)
        & rows["window"].astype("string").str.contains(f"{season}-08-01", regex=False, na=False)
    ].copy()
    if final.empty:
        return
    final["rank_v13"] = final["lbi_v13"].rank(method="average", ascending=False)
    final["rank_model"] = final[model].rank(method="average", ascending=False)
    final["rank_change"] = final["rank_v13"] - final["rank_model"]
    label = EV90_FORMULAS[model][0]
    print(f"\n=== Final {season}: v1.3 vs {label} Top 30 ===")
    v13 = final.sort_values("lbi_v13", ascending=False).head(30).reset_index(drop=True)
    candidate = final.sort_values(model, ascending=False).head(30).reset_index(drop=True)
    for index in range(30):
        left = v13.iloc[index]
        right = candidate.iloc[index]
        print(
            f"{index + 1:2}. v1.3 {left['player']:<24} {left['lbi_v13']:6.1f} | "
            f"candidate {right['player']:<24} {right[model]:6.1f} | "
            f"xHR {right['xhrPerBbe'] * 100:.2f}% | Thunder {right['la25_40_105Rate'] * 100:.1f}% | "
            f"Brl {right['barrelRate'] * 100:.1f}% | HH {right['hardHitRate'] * 100:.1f}%"
        )
    print(f"\nBiggest risers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=False).head(15).iterrows():
        print(
            f"+{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"candidate rank {row['rank_model']:.0f} | v1.3 {row['lbi_v13']:.1f} | candidate {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )
    print(f"\nBiggest fallers vs v1.3 ({season})")
    for _, row in final.sort_values("rank_change", ascending=True).head(15).iterrows():
        print(
            f"{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"candidate rank {row['rank_model']:.0f} | v1.3 {row['lbi_v13']:.1f} | candidate {row[model]:.1f} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )


def print_current_2026_identity_board(model: str) -> None:
    path = Path("public/data/longball-index-2026.json")
    if not path.exists():
        print("\n=== Current 2026 Board ===")
        print("public/data/longball-index-2026.json not found; skipping current board.")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = pd.DataFrame(payload.get("players", []))
    if players.empty:
        return
    players["la25_40_105Rate"] = to_numeric(players.get("hrWindowThunderRate", pd.Series(index=players.index)))
    for column in ["xhrPerBbe", "barrelRate", "hardHitRate", "la25_40_105Rate", "longballIndex"]:
        players[column] = to_numeric(players.get(column, pd.Series(index=players.index)))
    weights = EV90_FORMULAS[model][1]
    players["candidate"] = weighted_scores(players, weights)
    players["rank_v13"] = players["longballIndex"].rank(method="average", ascending=False)
    players["rank_candidate"] = players["candidate"].rank(method="average", ascending=False)
    players["rank_change"] = players["rank_v13"] - players["rank_candidate"]
    print(f"\n=== Current 2026 Top 30: v1.3 vs {EV90_FORMULAS[model][0]} ===")
    v13 = players.sort_values("longballIndex", ascending=False).head(30).reset_index(drop=True)
    candidate = players.sort_values("candidate", ascending=False).head(30).reset_index(drop=True)
    for index in range(30):
        left = v13.iloc[index]
        right = candidate.iloc[index]
        print(
            f"{index + 1:2}. v1.3 {left['player']:<24} {left['longballIndex']:6.1f} | "
            f"candidate {right['player']:<24} {right['candidate']:6.1f} | "
            f"xHR {right['xhrPerBbe'] * 100:.2f}% | Thunder {right['la25_40_105Rate'] * 100:.1f}%"
        )
    print("\nCurrent 2026 biggest candidate risers")
    for _, row in players.sort_values("rank_change", ascending=False).head(12).iterrows():
        print(
            f"+{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"candidate rank {row['rank_candidate']:.0f} | v1.3 {row['longballIndex']:.1f} | "
            f"candidate {row['candidate']:.1f} | xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )
    print("\nCurrent 2026 biggest candidate fallers")
    for _, row in players.sort_values("rank_change", ascending=True).head(12).iterrows():
        print(
            f"{row['rank_change']:.0f} {row['player']:<24} v1.3 rank {row['rank_v13']:.0f} -> "
            f"candidate rank {row['rank_candidate']:.0f} | v1.3 {row['longballIndex']:.1f} | "
            f"candidate {row['candidate']:.1f} | xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}%"
        )


def print_identity_sanity(rows: pd.DataFrame, model: str) -> None:
    names = [
        "Aaron Judge",
        "Shohei Ohtani",
        "Kyle Schwarber",
        "Cal Raleigh",
        "Yordan Alvarez",
        "James Wood",
        "Juan Soto",
        "Byron Buxton",
        "Nick Kurtz",
        "Matt Olson",
        "Ronald Acuña Jr.",
        "Ronald Acuña",
        "Corey Seager",
        "Mickey Moniak",
        "Alex Bregman",
        "Isaac Paredes",
        "Ke'Bryan Hayes",
        "Nico Hoerner",
        "Yandy Díaz",
        "Yandy Diaz",
        "Giancarlo Stanton",
        "Oneil Cruz",
    ]
    final = rows[
        rows["season"].eq(2025)
        & rows["window"].astype("string").str.contains("2025-08-01", regex=False, na=False)
    ].copy()
    if final.empty:
        return
    final["rank_v13"] = final["lbi_v13"].rank(method="average", ascending=False)
    final["rank_model"] = final[model].rank(method="average", ascending=False)
    print(f"\n=== Sanity Players: 2025 Final v1.3 vs {EV90_FORMULAS[model][0]} ===")
    seen = set()
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        sample = final[final["player"].astype("string").str.casefold().eq(key)]
        if sample.empty:
            continue
        row = sample.iloc[0]
        print(
            f"{row['player']:<24} v1.3 {row['lbi_v13']:.1f} (r{row['rank_v13']:.0f}) | "
            f"candidate {row[model]:.1f} (r{row['rank_model']:.0f}) | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}% | "
            f"future HR/BBE {row['futureHrPerBbe'] * 100:.2f}%"
        )


def print_lbi_identity_diagnostic(monthly: pd.DataFrame, rest_monthly: pd.DataFrame, all_star: pd.DataFrame) -> None:
    print("\n=== Public LBI Identity Diagnostic: xHR + Thunder Simplification ===")
    print("Production LBI v1.3 is unchanged. This is a diagnostic-only shadow comparison.")
    print("Scoring: plus-style percentile component scoring within each checkpoint pool, same as v1.3/public LBI.")
    print("Leakage: all inputs are checkpoint-to-date only; future targets are disjoint forward windows.")

    print("\n--- Primary descriptive continuity targets, six-week windows ---")
    desc_x = print_identity_metric_table("Future adjusted xHR/BBE", monthly, "futureAdjustedXhrPerBbe")
    desc_h = print_identity_metric_table("Future HR-capable rate", monthly, "futureHrCapableRate")
    print_identity_metric_table("Future no-doubter rate (tertiary)", monthly, "futureNoDoubterRate")

    print("\n--- Secondary future actual HR/BBE reference ---")
    print_identity_metric_table("Future actual HR/BBE, six-week", monthly, "futureHrPerBbe", include_top_stats=True)
    print_identity_metric_table("Future actual HR/BBE, rest of season", rest_monthly, "futureHrPerBbe", include_top_stats=True)

    if not all_star.empty:
        print("\n--- All-Star first-half to second-half reference ---")
        print_identity_metric_table("All-Star future adjusted xHR/BBE", all_star, "futureAdjustedXhrPerBbe")
        print_identity_metric_table("All-Star future HR-capable rate", all_star, "futureHrCapableRate")
        print_identity_metric_table("All-Star future actual HR/BBE", all_star, "futureHrPerBbe", include_top_stats=True)

    print_identity_correlations(monthly)
    best = best_two_factor_by_descriptive(monthly)
    print_identity_stability(monthly, ["lbi_v13", best, "lbi_ev90_B", "candidate_lbi_v14_heavy_thunder"])
    print_current_2026_identity_board(best)
    print_identity_side_by_side(monthly, 2025, best)
    print_identity_sanity(monthly, best)

    v13_desc = (
        desc_x["lbi_v13"]["pearson"]
        + desc_x["lbi_v13"]["spearman"]
        + desc_h["lbi_v13"]["pearson"]
        + desc_h["lbi_v13"]["spearman"]
    )
    best_desc = (
        desc_x[best]["pearson"]
        + desc_x[best]["spearman"]
        + desc_h[best]["pearson"]
        + desc_h[best]["spearman"]
    )
    px, sx = correlation_pair(monthly[best], monthly["xhrPerBbe"])
    print("\n=== Recommendation Inputs ===")
    print(f"Best two-factor candidate by primary descriptive targets: {EV90_FORMULAS[best][0]}.")
    print(f"Combined descriptive P/S lift vs v1.3: {(best_desc - v13_desc):+.3f}.")
    print(f"{EV90_FORMULAS[best][0]} correlation with raw xHR/BBE: Pearson {px:.3f}, Spearman {sx:.3f}.")


PHASE0_STORM_MODELS = {
    "barrelRate": "raw Barrel/BBE",
    "lbi_v13": "production LBI v1.3",
    "candidate_lbi_v14_heavy_thunder": "Heavy Thunder reference",
}

PHASE1_STORM_MODELS = {
    **{column: label for column, (label, _) in STORM_WATCH_FORMULAS.items()},
}


def storm_metrics_table(rows: pd.DataFrame, models: dict[str, str], target: str) -> pd.DataFrame:
    records = []
    for column, label in models.items():
        metrics = model_metrics(rows, column, target)
        records.append({"column": column, "label": label, **metrics})
    return pd.DataFrame(records)


def print_storm_table(title: str, rows: pd.DataFrame, models: dict[str, str], target: str) -> pd.DataFrame:
    print(f"\n=== {title} ===")
    table = storm_metrics_table(rows, models, target)
    for _, row in table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())
    return table


def print_storm_per_season(title: str, rows: pd.DataFrame, models: dict[str, str], target: str) -> None:
    print(f"\n=== {title}: per-season primary target ===")
    for column, label in models.items():
        parts = []
        for season, frame in rows.groupby("season"):
            metrics = model_metrics(frame, column, target)
            lift = metrics["topDecileLift"]
            lift_text = "n/a" if pd.isna(lift) else f"{lift * 100:+.1f}%"
            parts.append(
                f"{int(season)} P {metrics['pearson']:.3f} S {metrics['spearman']:.3f} lift {lift_text}"
            )
        print(f"{label:<42} " + " | ".join(parts))


def print_storm_may1(rows: pd.DataFrame, models: dict[str, str]) -> pd.DataFrame:
    may = rows[rows["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    print("\n=== Phase 1 Side-Check: May 1 Only, future HR/BBE ===")
    table = storm_metrics_table(may, models, "futureHrPerBbe")
    for _, row in table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())
    return table


def print_storm_additivity(rows: pd.DataFrame, combos: list[str]) -> None:
    print("\n=== Phase 1: Additivity / Marginal Lift by Season ===")
    base_t = "storm_base_T_xhr60_thunder40"
    base_e = "storm_base_E_xhr60_ev90_40"
    for combo in combos:
        label = PHASE1_STORM_MODELS[combo]
        better_t = 0
        better_e = 0
        better_both = 0
        print(f"\n{label}")
        for season, frame in rows.groupby("season"):
            combo_metrics = model_metrics(frame, combo, "futureHrPerBbe")
            t_metrics = model_metrics(frame, base_t, "futureHrPerBbe")
            e_metrics = model_metrics(frame, base_e, "futureHrPerBbe")
            beats_t = combo_metrics["topDecileLift"] > t_metrics["topDecileLift"]
            beats_e = combo_metrics["topDecileLift"] > e_metrics["topDecileLift"]
            better_t += int(beats_t)
            better_e += int(beats_e)
            better_both += int(beats_t and beats_e)
            print(
                f"  {int(season)} combo lift {combo_metrics['topDecileLift'] * 100:+.1f}% | "
                f"base_T {t_metrics['topDecileLift'] * 100:+.1f}% | "
                f"base_E {e_metrics['topDecileLift'] * 100:+.1f}% | "
                f"combo P/S {combo_metrics['pearson']:.3f}/{combo_metrics['spearman']:.3f}"
            )
        print(
            f"  lift survival: beats base_T {better_t}/5 seasons, beats base_E {better_e}/5, "
            f"beats both {better_both}/5."
        )


def print_storm_watch_diagnostic(monthly: pd.DataFrame, rest_monthly: pd.DataFrame) -> None:
    print("\n=== Predictive Sibling Diagnostic: Storm Watch Phase 0/1 ===")
    print("Working name only. This is a new six-week HR-surge signal, not an LBI variant.")
    print("Harness used: LBI variant checkpoint harness, because this target is future HR/BBE.")
    print("Barrel reference is raw Barrel/BBE; this harness does not carry PA, so Barrel/PA was not used.")
    print("Scoring: candidate formulas use plus-style percentile component scoring within each checkpoint pool.")
    print("Leakage: all inputs are checkpoint-to-date only; EV90 is to-date 90th-pctile EV; targets are disjoint future windows.")

    print("\n--- Phase 0: Empirical Bar ---")
    phase0_6w = print_storm_table("Phase 0 references, six-week future HR/BBE", monthly, PHASE0_STORM_MODELS, "futureHrPerBbe")
    phase0_ros = print_storm_table("Phase 0 references, rest-of-season future HR/BBE", rest_monthly, PHASE0_STORM_MODELS, "futureHrPerBbe")
    print_storm_per_season("Phase 0 references", monthly, PHASE0_STORM_MODELS, "futureHrPerBbe")
    bar_row = phase0_6w.sort_values(["topDecileLift", "pearson"], ascending=False).iloc[0]
    print(
        f"\nNumber to beat on the primary six-week surge read: {bar_row['label']} "
        f"with top-decile lift {bar_row['topDecileLift'] * 100:+.1f}% "
        f"(Pearson {bar_row['pearson']:.3f}, Spearman {bar_row['spearman']:.3f})."
    )

    px, sx = correlation_pair(monthly["la25_40_105Rate"], monthly["ev90"])
    print("\n--- Phase 1: Ingredient Overlap ---")
    print(f"THUNDER_SIG vs EV90_SIG pooled correlation: Pearson {px:.3f}, Spearman {sx:.3f}.")

    print("\n--- Phase 1: Marginal Lift ---")
    phase1_6w = print_storm_table("Phase 1 candidates, six-week future HR/BBE", monthly, PHASE1_STORM_MODELS, "futureHrPerBbe")
    phase1_ros = print_storm_table("Phase 1 candidates, rest-of-season future HR/BBE", rest_monthly, PHASE1_STORM_MODELS, "futureHrPerBbe")
    print_storm_per_season("Phase 1 candidates", monthly, PHASE1_STORM_MODELS, "futureHrPerBbe")
    combos = [
        "storm_combo_xhr50_thunder30_ev90_20",
        "storm_combo_xhr50_thunder25_ev90_25",
        "storm_combo_xhr55_thunder25_ev90_20",
    ]
    print_storm_additivity(monthly, combos)

    may_models = {
        "candidate_lbi_v14_heavy_thunder": "Phase-0 bar: Heavy Thunder",
        "storm_base_T_xhr60_thunder40": PHASE1_STORM_MODELS["storm_base_T_xhr60_thunder40"],
        "storm_base_E_xhr60_ev90_40": PHASE1_STORM_MODELS["storm_base_E_xhr60_ev90_40"],
        **{combo: PHASE1_STORM_MODELS[combo] for combo in combos},
    }
    may_table = print_storm_may1(monthly, may_models)

    best_phase1 = phase1_6w.sort_values(["topDecileLift", "pearson"], ascending=False).iloc[0]
    best_ros = phase1_ros[phase1_ros["column"].eq(best_phase1["column"])].iloc[0]
    best_may = may_table[may_table["column"].eq(best_phase1["column"])].iloc[0]
    print("\n=== Recommendation Inputs ===")
    print(
        f"Phase 0 bar: {bar_row['label']} at {bar_row['topDecileLift'] * 100:+.1f}% six-week top-decile lift."
    )
    print(
        f"Best Phase 1 candidate: {best_phase1['label']} | six-week lift {best_phase1['topDecileLift'] * 100:+.1f}% "
        f"| Pearson {best_phase1['pearson']:.3f} | Spearman {best_phase1['spearman']:.3f}."
    )
    print(
        f"Same candidate ROS: lift {best_ros['topDecileLift'] * 100:+.1f}% | "
        f"Pearson {best_ros['pearson']:.3f} | Spearman {best_ros['spearman']:.3f}."
    )
    print(
        f"Same candidate May 1: lift {best_may['topDecileLift'] * 100:+.1f}% | "
        f"Pearson {best_may['pearson']:.3f} | Spearman {best_may['spearman']:.3f}."
    )


PHASE2_STORM_MODELS = {
    "candidate_lbi_v14_heavy_thunder": "Phase-0 Heavy Thunder bar",
    "storm_phase2_raw_combo": STORM_PHASE2_FORMULAS["storm_phase2_raw_combo"][0],
    **{column: label for column, (label, _) in STORM_PHASE2_FORMULAS.items() if column != "storm_phase2_raw_combo"},
}


def print_storm_phase2_shrinkage_summary(rows: pd.DataFrame) -> None:
    print("\n=== Shrinkage Context ===")
    may = rows[rows["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    for label, frame in [("All checkpoints", rows), ("May 1 only", may)]:
        if frame.empty:
            continue
        print(
            f"{label}: Thunder avg {frame['la25_40_105Rate'].mean() * 100:.2f}% | "
            f"median {frame['la25_40_105Rate'].median() * 100:.2f}% | "
            f"zero-rate {frame['la25_40_105Rate'].eq(0).mean() * 100:.1f}% | "
            f"EV90 avg {frame['ev90'].mean():.1f}"
        )


def estimate_storm_component_stabilization(rows: pd.DataFrame) -> dict[str, int]:
    print("\n=== PART 1: Component Stabilization Estimate (No-Prior Players) ===")
    no_prior = rows[rows["priorStormContextMissing"]].copy()
    if no_prior.empty:
        print("No no-prior rows available; falling back to prior flat-M references.")
        return {"xhr": 75, "thunder": 75, "ev90": 50}

    buckets = [(50, 74), (75, 99), (100, 124), (125, 149), (150, 199), (200, 9999)]
    components = {
        "xhr": ("xHR/BBE", "xhrPerBbe", "futureAdjustedXhrPerBbe"),
        "thunder": ("HR-Window Thunder Rate", "la25_40_105Rate", "futureThunderRate"),
        "ev90": ("EV90", "ev90", "futureEv90"),
    }
    selected: dict[str, int] = {}
    for key, (label, current_col, future_col) in components.items():
        records = []
        for low, high in buckets:
            frame = no_prior[no_prior["firstBbe"].between(low, high, inclusive="both")].copy()
            frame = frame[[current_col, future_col, "firstBbe"]].dropna()
            if len(frame) < 30:
                continue
            pearson, spearman = correlation_pair(frame[current_col], frame[future_col])
            midpoint = int(round(frame["firstBbe"].median()))
            strength = max(value for value in [pearson, spearman] if not math.isnan(value))
            records.append(
                {
                    "range": f"{low}-{high if high < 9999 else '+'}",
                    "n": len(frame),
                    "medianBbe": midpoint,
                    "pearson": pearson,
                    "spearman": spearman,
                    "strength": strength,
                }
            )
        crossing = next((record for record in records if record["strength"] >= 0.50), None)
        if crossing is None and records:
            crossing = max(records, key=lambda record: record["strength"])
            note = "no bucket reached 0.50; using strongest observed bucket"
        elif crossing is None:
            crossing = {"medianBbe": 75, "strength": float("nan")}
            note = "insufficient no-prior sample; using 75 fallback"
        else:
            note = "first bucket at/above ~0.50 self-correlation"
        selected[key] = int(crossing["medianBbe"])
        print(f"{label}: selected M_stab {selected[key]} ({note}).")
        for record in records:
            print(
                f"  BBE {record['range']:<7} n={record['n']:4d} median={record['medianBbe']:3d} | "
                f"Pearson {record['pearson']:.3f} | Spearman {record['spearman']:.3f}"
            )
    return selected


def add_storm_phase2_l2_scores(rows: pd.DataFrame) -> pd.DataFrame:
    output = rows.copy()
    prior_frames = []
    for season in sorted(output["season"].dropna().unique()):
        prior = load_prior_storm_components(int(season))
        if prior.empty:
            continue
        prior["season"] = int(season)
        prior_frames.append(prior)
    if prior_frames:
        prior_all = pd.concat(prior_frames, ignore_index=True)
        output = output.merge(prior_all, on=["season", "batter"], how="left")
    else:
        for column in ["priorXhrPerBbe", "priorThunderRate", "priorEv90", "priorBbe"]:
            output[column] = pd.NA

    output["priorStormContextMissing"] = output["priorXhrPerBbe"].isna() | output["priorThunderRate"].isna()
    for _, index in output.groupby(["season", "window"]).groups.items():
        league_xhr = output.loc[index, "xhrPerBbe"].mean()
        league_thunder = output.loc[index, "la25_40_105Rate"].mean()
        for mx, mt in STORM_PHASE2_L2_GRID:
            prior_xhr = output.loc[index, "priorXhrPerBbe"].fillna(league_xhr)
            prior_thunder = output.loc[index, "priorThunderRate"].fillna(league_thunder)
            wx = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + mx)
            wt = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + mt)
            output.loc[index, f"stormPriorXhrBlendM{mx}"] = wx * output.loc[index, "xhrPerBbe"] + (1 - wx) * prior_xhr
            output.loc[index, f"stormPriorThunderBlendM{mt}"] = (
                wt * output.loc[index, "la25_40_105Rate"] + (1 - wt) * prior_thunder
            )

        for mx, mt in STORM_PHASE2_L2_GRID:
            for ev_label, ev_column in [("evraw", "ev90"), ("evm50", "ev90ShrunkM50")]:
                score_column = f"storm_phase2_l2_x{mx}_t{mt}_{ev_label}"
                output.loc[index, score_column] = weighted_scores(
                    output.loc[index],
                    {
                        f"stormPriorXhrBlendM{mx}": 0.50,
                        f"stormPriorThunderBlendM{mt}": 0.25,
                        ev_column: 0.25,
                    },
                )

        missing_prior = output.loc[index, "priorStormContextMissing"].fillna(True)
        prior_xhr = output.loc[index, "priorXhrPerBbe"].fillna(league_xhr)
        prior_thunder = output.loc[index, "priorThunderRate"].fillna(league_thunder)
        standard_xhr_weight = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + STORM_L2_XHR_M)
        standard_thunder_weight = output.loc[index, "firstBbe"] / (
            output.loc[index, "firstBbe"] + STORM_L2_THUNDER_M
        )
        for column, (_, no_prior_m) in STORM_NO_PRIOR_VARIANTS.items():
            if no_prior_m == 0:
                no_prior_weight = pd.Series(1.0, index=index)
            else:
                no_prior_weight = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + no_prior_m)
            xhr_weight = standard_xhr_weight.where(~missing_prior, no_prior_weight)
            thunder_weight = standard_thunder_weight.where(~missing_prior, no_prior_weight)
            xhr_blend = f"{column}_xhrBlend"
            thunder_blend = f"{column}_thunderBlend"
            output.loc[index, xhr_blend] = (
                xhr_weight * output.loc[index, "xhrPerBbe"] + (1 - xhr_weight) * prior_xhr
            )
            output.loc[index, thunder_blend] = (
                thunder_weight * output.loc[index, "la25_40_105Rate"] + (1 - thunder_weight) * prior_thunder
            )
            output.loc[index, f"{column}_xhrCurrentWeight"] = xhr_weight
            output.loc[index, f"{column}_thunderCurrentWeight"] = thunder_weight
            output.loc[index, column] = weighted_scores(
                output.loc[index],
                {
                    xhr_blend: 0.50,
                    thunder_blend: 0.25,
                    "ev90": 0.25,
                },
            )
    return output


def add_storm_no_prior_stab_scores(rows: pd.DataFrame, stab_m: dict[str, int]) -> pd.DataFrame:
    expected = STORM_NO_PRIOR_STAB_M
    if stab_m != expected:
        print(
            "Storm Watch v1 uses locked stabilization constants "
            f"xHR {expected['xhr']} / Thunder {expected['thunder']} / EV90 {expected['ev90']}; "
            f"diagnostic estimate was xHR {stab_m['xhr']} / Thunder {stab_m['thunder']} / EV90 {stab_m['ev90']}."
        )
    stab_m = expected
    output = rows.copy()
    for _, index in output.groupby(["season", "window"]).groups.items():
        league_xhr = output.loc[index, "xhrPerBbe"].mean()
        league_thunder = output.loc[index, "la25_40_105Rate"].mean()
        league_ev90 = output.loc[index, "ev90"].mean()
        missing_prior = output.loc[index, "priorStormContextMissing"].fillna(True)
        prior_xhr = output.loc[index, "priorXhrPerBbe"].fillna(league_xhr)
        prior_thunder = output.loc[index, "priorThunderRate"].fillna(league_thunder)

        standard_xhr_weight = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + STORM_L2_XHR_M)
        standard_thunder_weight = output.loc[index, "firstBbe"] / (
            output.loc[index, "firstBbe"] + STORM_L2_THUNDER_M
        )
        no_prior_xhr_weight = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + stab_m["xhr"])
        no_prior_thunder_weight = output.loc[index, "firstBbe"] / (
            output.loc[index, "firstBbe"] + stab_m["thunder"]
        )
        no_prior_ev90_weight = output.loc[index, "firstBbe"] / (output.loc[index, "firstBbe"] + stab_m["ev90"])
        xhr_weight = standard_xhr_weight.where(~missing_prior, no_prior_xhr_weight)
        thunder_weight = standard_thunder_weight.where(~missing_prior, no_prior_thunder_weight)
        ev90_weight = pd.Series(1.0, index=index).where(~missing_prior, no_prior_ev90_weight)

        xhr_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_xhrBlend"
        thunder_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_thunderBlend"
        ev90_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_ev90Blend"
        output.loc[index, xhr_blend] = (
            xhr_weight * output.loc[index, "xhrPerBbe"] + (1 - xhr_weight) * prior_xhr
        )
        output.loc[index, thunder_blend] = (
            thunder_weight * output.loc[index, "la25_40_105Rate"] + (1 - thunder_weight) * prior_thunder
        )
        output.loc[index, ev90_blend] = ev90_weight * output.loc[index, "ev90"] + (1 - ev90_weight) * league_ev90
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_xhrCurrentWeight"] = xhr_weight
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_thunderCurrentWeight"] = thunder_weight
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_ev90CurrentWeight"] = ev90_weight
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorXhr"] = prior_xhr
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorThunder"] = prior_thunder
        output.loc[index, f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorEv90"] = league_ev90
        output.loc[index, STORM_NO_PRIOR_STAB_COLUMN] = weighted_scores(
            output.loc[index],
            {
                xhr_blend: 0.50,
                thunder_blend: 0.25,
                ev90_blend: 0.25,
            },
        )
    return output


def phase2_models(include_l2: bool = True) -> dict[str, str]:
    models = dict(PHASE2_STORM_MODELS)
    if include_l2:
        for mx, mt in STORM_PHASE2_L2_GRID:
            models[f"storm_phase2_l2_x{mx}_t{mt}_evraw"] = f"L2 prior xHR M{mx} / Thunder M{mt} / EV90 raw"
            models[f"storm_phase2_l2_x{mx}_t{mt}_evm50"] = f"L2 prior xHR M{mx} / Thunder M{mt} / EV90 M50"
        models.update(STORM_NO_PRIOR_FIX_MODELS)
    return models


def print_storm_phase2_table(title: str, rows: pd.DataFrame, target: str) -> pd.DataFrame:
    print(f"\n=== {title} ===")
    table = storm_metrics_table(rows, phase2_models(), target)
    for _, row in table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())
    return table


def print_storm_phase2_per_season(rows: pd.DataFrame, models: dict[str, str]) -> None:
    print("\n=== May 1 Top-Decile Lift by Season ===")
    may = rows[rows["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    for column, label in models.items():
        parts = []
        for season, frame in may.groupby("season"):
            metrics = model_metrics(frame, column, "futureHrPerBbe")
            parts.append(
                f"{int(season)} P {metrics['pearson']:.3f} S {metrics['spearman']:.3f} lift {metrics['topDecileLift'] * 100:+.1f}%"
            )
        print(f"{label:<44} " + " | ".join(parts))


def print_storm_phase2_volatility(rows: pd.DataFrame, models: dict[str, str]) -> None:
    print("\n=== Month-to-Month Volatility Guardrail ===")
    records = []
    for column, label in models.items():
        volatility = score_volatility(rows, column)
        records.append((volatility["avgRankDelta"], volatility["p90RankDelta"], label))
    for avg_delta, p90_delta, label in sorted(records):
        print(f"{label:<48} avg rank delta {avg_delta:.1f} | p90 {p90_delta:.1f}")


def print_storm_phase2_may_survival(rows: pd.DataFrame, models: dict[str, str]) -> None:
    print("\n=== May 1 Edge vs Heavy Thunder by Season ===")
    may = rows[rows["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    for column, label in models.items():
        if column == "candidate_lbi_v14_heavy_thunder":
            continue
        wins = 0
        parts = []
        for season, frame in may.groupby("season"):
            model_lift = model_metrics(frame, column, "futureHrPerBbe")["topDecileLift"]
            bar_lift = model_metrics(frame, "candidate_lbi_v14_heavy_thunder", "futureHrPerBbe")["topDecileLift"]
            wins += int(model_lift >= bar_lift)
            parts.append(f"{int(season)} {model_lift * 100:+.1f}% vs {bar_lift * 100:+.1f}%")
        print(f"{label:<48} beats/holds bar {wins}/5 | " + " | ".join(parts))


def print_storm_phase2_final_2025(rows: pd.DataFrame, model: str, label: str) -> None:
    final = rows[
        rows["season"].eq(2025)
        & rows["window"].astype("string").str.contains("2025-08-01", regex=False, na=False)
    ].copy()
    if final.empty:
        return
    final["rank"] = final[model].rank(method="average", ascending=False)
    print(f"\n=== Final 2025 Top 30: {label} ===")
    for rank, (_, row) in enumerate(final.sort_values(model, ascending=False).head(30).iterrows(), start=1):
        print(
            f"{rank:2}. {row['player']:<24} score {row[model]:6.1f} | BBE {int(row['firstBbe'])} | "
            f"xHR {row['xhrPerBbe'] * 100:.2f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}% | "
            f"EV90 {row['ev90']:.1f} | future HR/BBE {row['futureHrPerBbe'] * 100:.2f}%"
        )


def add_storm_no_prior_fix_scores_to_frame(
    frame: pd.DataFrame,
    league_xhr: float,
    league_thunder: float,
    stab_m: dict[str, int] | None = None,
) -> pd.DataFrame:
    if stab_m is not None:
        stab_m = STORM_NO_PRIOR_STAB_M
    output = frame.copy()
    output["priorStormContextMissing"] = output["priorXhrPerBbe"].isna() | output["priorThunderRate"].isna()
    prior_xhr = output["priorXhrPerBbe"].fillna(league_xhr)
    prior_thunder = output["priorThunderRate"].fillna(league_thunder)
    league_ev90 = output["ev90"].mean()

    standard_xhr_weight = output["firstBbe"] / (output["firstBbe"] + STORM_L2_XHR_M)
    standard_thunder_weight = output["firstBbe"] / (output["firstBbe"] + STORM_L2_THUNDER_M)
    output[f"stormPriorXhrBlendM{STORM_L2_XHR_M}"] = (
        standard_xhr_weight * output["xhrPerBbe"] + (1 - standard_xhr_weight) * prior_xhr
    )
    output[f"stormPriorThunderBlendM{STORM_L2_THUNDER_M}"] = (
        standard_thunder_weight * output["la25_40_105Rate"] + (1 - standard_thunder_weight) * prior_thunder
    )
    output[STORM_L2_CURRENT_COLUMN] = weighted_scores(
        output,
        {
            f"stormPriorXhrBlendM{STORM_L2_XHR_M}": 0.50,
            f"stormPriorThunderBlendM{STORM_L2_THUNDER_M}": 0.25,
            "ev90": 0.25,
        },
    )
    output[f"{STORM_L2_CURRENT_COLUMN}_xhrCurrentWeight"] = standard_xhr_weight
    output[f"{STORM_L2_CURRENT_COLUMN}_thunderCurrentWeight"] = standard_thunder_weight
    output[f"{STORM_L2_CURRENT_COLUMN}_xhrBlend"] = output[f"stormPriorXhrBlendM{STORM_L2_XHR_M}"]
    output[f"{STORM_L2_CURRENT_COLUMN}_thunderBlend"] = output[f"stormPriorThunderBlendM{STORM_L2_THUNDER_M}"]
    output[f"{STORM_L2_CURRENT_COLUMN}_effectivePriorXhr"] = prior_xhr
    output[f"{STORM_L2_CURRENT_COLUMN}_effectivePriorThunder"] = prior_thunder

    for column, (_, no_prior_m) in STORM_NO_PRIOR_VARIANTS.items():
        if no_prior_m == 0:
            no_prior_weight = pd.Series(1.0, index=output.index)
        else:
            no_prior_weight = output["firstBbe"] / (output["firstBbe"] + no_prior_m)
        xhr_weight = standard_xhr_weight.where(~output["priorStormContextMissing"], no_prior_weight)
        thunder_weight = standard_thunder_weight.where(~output["priorStormContextMissing"], no_prior_weight)
        xhr_blend = f"{column}_xhrBlend"
        thunder_blend = f"{column}_thunderBlend"
        output[xhr_blend] = xhr_weight * output["xhrPerBbe"] + (1 - xhr_weight) * prior_xhr
        output[thunder_blend] = thunder_weight * output["la25_40_105Rate"] + (1 - thunder_weight) * prior_thunder
        output[f"{column}_xhrCurrentWeight"] = xhr_weight
        output[f"{column}_thunderCurrentWeight"] = thunder_weight
        output[f"{column}_effectivePriorXhr"] = prior_xhr
        output[f"{column}_effectivePriorThunder"] = prior_thunder
        output[column] = weighted_scores(
            output,
            {
                xhr_blend: 0.50,
                thunder_blend: 0.25,
                "ev90": 0.25,
            },
        )
    if stab_m is not None:
        missing_prior = output["priorStormContextMissing"].fillna(True)
        no_prior_xhr_weight = output["firstBbe"] / (output["firstBbe"] + stab_m["xhr"])
        no_prior_thunder_weight = output["firstBbe"] / (output["firstBbe"] + stab_m["thunder"])
        no_prior_ev90_weight = output["firstBbe"] / (output["firstBbe"] + stab_m["ev90"])
        xhr_weight = standard_xhr_weight.where(~missing_prior, no_prior_xhr_weight)
        thunder_weight = standard_thunder_weight.where(~missing_prior, no_prior_thunder_weight)
        ev90_weight = pd.Series(1.0, index=output.index).where(~missing_prior, no_prior_ev90_weight)
        xhr_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_xhrBlend"
        thunder_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_thunderBlend"
        ev90_blend = f"{STORM_NO_PRIOR_STAB_COLUMN}_ev90Blend"
        output[xhr_blend] = xhr_weight * output["xhrPerBbe"] + (1 - xhr_weight) * prior_xhr
        output[thunder_blend] = thunder_weight * output["la25_40_105Rate"] + (1 - thunder_weight) * prior_thunder
        output[ev90_blend] = ev90_weight * output["ev90"] + (1 - ev90_weight) * league_ev90
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_xhrCurrentWeight"] = xhr_weight
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_thunderCurrentWeight"] = thunder_weight
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_ev90CurrentWeight"] = ev90_weight
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorXhr"] = prior_xhr
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorThunder"] = prior_thunder
        output[f"{STORM_NO_PRIOR_STAB_COLUMN}_effectivePriorEv90"] = league_ev90
        output[STORM_NO_PRIOR_STAB_COLUMN] = weighted_scores(
            output,
            {
                xhr_blend: 0.50,
                thunder_blend: 0.25,
                ev90_blend: 0.25,
            },
        )
    return output


def current_2026_storm_frame(stab_m: dict[str, int] | None = None) -> pd.DataFrame:
    lbi_path = Path("public/data/longball-index-2026.json")
    pitch_path = Path("data/raw/statcast-pitches.csv")
    if not lbi_path.exists() or not pitch_path.exists():
        return pd.DataFrame()
    payload = json.loads(lbi_path.read_text(encoding="utf-8"))
    players = pd.DataFrame(payload.get("players", []))
    if players.empty:
        return pd.DataFrame()
    players["batter"] = to_numeric(players["batter"])
    for column in ["bbe", "xhrPerBbe", "hrWindowThunderRate"]:
        players[column] = to_numeric(players.get(column, pd.Series(index=players.index)))
    pitches = pd.read_csv(pitch_path)
    pitches["game_date"] = pd.to_datetime(pitches["game_date"], errors="coerce").dt.date
    for column in ["batter", "launch_speed", "launch_angle"]:
        pitches[column] = to_numeric(pitches[column])
    pitches = scope_to_regular_season(pitches.dropna(subset=["game_date", "batter"]).copy(), 2026)
    bbe = pitches[pitches["launch_speed"].notna() & pitches["launch_angle"].notna()].copy()
    ev90 = bbe.groupby("batter", as_index=False).agg(ev90=("launch_speed", lambda values: values.quantile(0.90)))
    current = players.merge(ev90, on="batter", how="left")
    current = current.rename(columns={"bbe": "firstBbe", "hrWindowThunderRate": "la25_40_105Rate"})
    current["xhrPerBbe"] = to_numeric(current["xhrPerBbe"])
    current["firstAdjustedXhr"] = current["xhrPerBbe"] * current["firstBbe"]
    current["firstLa25_40_105Bbe"] = current["la25_40_105Rate"] * current["firstBbe"]
    league_xhr = current["firstAdjustedXhr"].sum() / current["firstBbe"].sum()
    league_thunder = current["firstLa25_40_105Bbe"].sum() / current["firstBbe"].sum()
    prior = load_prior_storm_components(2026)
    if not prior.empty:
        current = current.merge(prior, on="batter", how="left")
    else:
        current["priorXhrPerBbe"] = pd.NA
        current["priorThunderRate"] = pd.NA
        current["priorEv90"] = pd.NA
        current["priorBbe"] = pd.NA
    return add_storm_no_prior_fix_scores_to_frame(current, league_xhr, league_thunder, stab_m)


def print_storm_no_prior_current_check(models: dict[str, str], stab_m: dict[str, int]) -> None:
    current = current_2026_storm_frame(stab_m)
    print("\n=== PART 1: Current 2026 No-Prior Fallback Check ===")
    print(STORM_WATCH_DEFINITION)
    if current.empty:
        print("Current public LBI JSON or Statcast pitch cache unavailable; skipping current fallback check.")
        return
    for model in models:
        current[f"{model}_rank"] = current[model].rank(method="min", ascending=False)

    near_top_no_prior = current[
        current["priorStormContextMissing"]
        & current[[f"{model}_rank" for model in models]].le(35).any(axis=1)
    ]["player"].dropna().astype(str).tolist()
    names = []
    for player in ["Munetaka Murakami", "Kazuma Okamoto", *near_top_no_prior]:
        if player not in names:
            names.append(player)

    print(
        "Current L2 uses league-average no-prior at full veteran M. The test variants keep real-prior "
        "players unchanged and only reduce the no-prior M."
    )
    for player in names:
        matches = current[current["player"].astype("string").eq(player)]
        if matches.empty:
            continue
        row = matches.iloc[0]
        prior_label = "no real prior" if bool(row["priorStormContextMissing"]) else "real prior"
        print(
            f"\n{player}: BBE {int(row['firstBbe'])} | {prior_label} | "
            f"current xHR {row['xhrPerBbe'] * 100:.2f}% | current Thunder {row['la25_40_105Rate'] * 100:.2f}% | EV90 {row['ev90']:.1f}"
        )
        for model, label in models.items():
            detail = (
                f"  {label}: xHR prior weight {(1 - row[f'{model}_xhrCurrentWeight']) * 100:.1f}% -> "
                f"{row[f'{model}_xhrBlend'] * 100:.2f}% | Thunder prior weight "
                f"{(1 - row[f'{model}_thunderCurrentWeight']) * 100:.1f}% -> "
                f"{row[f'{model}_thunderBlend'] * 100:.2f}%"
            )
            if f"{model}_ev90CurrentWeight" in row.index:
                detail += (
                    f" | EV90 prior weight {(1 - row[f'{model}_ev90CurrentWeight']) * 100:.1f}% -> "
                    f"{row[f'{model}_ev90Blend']:.1f}"
                )
            detail += f" | score {row[model]:.1f} | rank {int(row[f'{model}_rank'])}"
            print(detail)


def print_storm_no_prior_guardrail(rows: pd.DataFrame, models: dict[str, str]) -> None:
    print("\n=== PART 2: Small-Sample No-Prior Guardrail ===")
    print(
        f"Eligible checkpoints use min-first-BBE {DEFAULT_MIN_FIRST_BBE}, so <40 BBE no-prior players "
        f"do not enter this harness. Guardrail sample here is no-prior with BBE < {NO_PRIOR_SMALL_BBE_THRESHOLD}."
    )
    for column, label in models.items():
        top_decile_count = 0
        top_decile_busts = 0
        top30_count = 0
        top30_busts = 0
        examples = []
        for _, frame in rows.groupby(["season", "window"]):
            frame = frame.copy()
            small_no_prior = frame["priorStormContextMissing"] & frame["firstBbe"].lt(NO_PRIOR_SMALL_BBE_THRESHOLD)
            if not small_no_prior.any():
                continue
            median_future = frame["futureHrPerBbe"].median()
            top_decile_cut = frame[column].quantile(0.90)
            in_top_decile = small_no_prior & frame[column].ge(top_decile_cut)
            in_top30 = small_no_prior & frame[column].rank(method="first", ascending=False).le(30)
            top_decile_count += int(in_top_decile.sum())
            top_decile_busts += int((in_top_decile & frame["futureHrPerBbe"].le(median_future)).sum())
            top30_count += int(in_top30.sum())
            top30_busts += int((in_top30 & frame["futureHrPerBbe"].le(median_future)).sum())
            for _, row in frame[in_top30].sort_values(column, ascending=False).head(2).iterrows():
                if len(examples) >= 5:
                    break
                examples.append(
                    f"{int(row['season'])} {row['player']} BBE {int(row['firstBbe'])} "
                    f"score {row[column]:.1f} future {row['futureHrPerBbe'] * 100:.2f}%"
                )
        print(
            f"{label}: top-decile small no-prior {top_decile_count}, busts {top_decile_busts}; "
            f"top-30 small no-prior {top30_count}, busts {top30_busts}"
        )
        if examples:
            print("  examples: " + " | ".join(examples))


def print_storm_no_prior_split(title: str, rows: pd.DataFrame, models: dict[str, str]) -> None:
    print(f"\n=== {title}: Prior Split ===")
    for split_label, frame in [
        ("REAL PRIOR", rows[~rows["priorStormContextMissing"]].copy()),
        ("NO PRIOR", rows[rows["priorStormContextMissing"]].copy()),
    ]:
        print(f"-- {split_label} --")
        for column, label in models.items():
            metrics = model_metrics(frame, column, "futureHrPerBbe")
            print_metric_line(label, metrics)


def print_storm_no_prior_defensibility(rows: pd.DataFrame, models: dict[str, str]) -> None:
    print("\n=== PART 3: No-Prior Real-vs-Fluke Separation ===")
    no_prior = rows[rows["priorStormContextMissing"]].copy()
    for column, label in models.items():
        top_future_values = []
        bottom_future_values = []
        high_signal_frames = []
        for _, frame in no_prior.groupby(["season", "window"]):
            frame = frame.dropna(subset=[column, "futureHrPerBbe"]).copy()
            if len(frame) < 20:
                continue
            top_cut = frame[column].quantile(0.90)
            bottom_cut = frame[column].quantile(0.50)
            top_future_values.extend(frame.loc[frame[column].ge(top_cut), "futureHrPerBbe"].tolist())
            bottom_future_values.extend(frame.loc[frame[column].le(bottom_cut), "futureHrPerBbe"].tolist())
            high_signal_frames.append(frame[frame[column].ge(frame[column].quantile(0.75))])
        high_signal = pd.concat(high_signal_frames, ignore_index=True) if high_signal_frames else pd.DataFrame()
        top_avg = pd.Series(top_future_values).mean() if top_future_values else float("nan")
        bottom_avg = pd.Series(bottom_future_values).mean() if bottom_future_values else float("nan")
        separation = (top_avg / bottom_avg - 1) if bottom_avg and not math.isnan(bottom_avg) else float("nan")
        pearson, spearman = (
            correlation_pair(high_signal[column], high_signal["futureHrPerBbe"])
            if not high_signal.empty
            else (float("nan"), float("nan"))
        )
        future_median = no_prior["futureHrPerBbe"].median()
        bust_rate = high_signal["futureHrPerBbe"].le(future_median).mean() if not high_signal.empty else float("nan")
        print(
            f"{label}: no-prior top-decile avg future {top_avg * 100:.2f}% vs lower-half {bottom_avg * 100:.2f}% "
            f"({separation * 100:+.1f}%); high-signal sustained corr P {pearson:.3f} S {spearman:.3f}; "
            f"high-signal bust rate {bust_rate * 100:.1f}%"
        )


def print_storm_phase2_diagnostic(monthly: pd.DataFrame, rest_monthly: pd.DataFrame) -> None:
    monthly = add_storm_phase2_l2_scores(monthly)
    rest_monthly = add_storm_phase2_l2_scores(rest_monthly)
    stab_m = estimate_storm_component_stabilization(monthly)
    monthly = add_storm_no_prior_stab_scores(monthly, stab_m)
    rest_monthly = add_storm_no_prior_stab_scores(rest_monthly, stab_m)
    print("\n=== Storm Watch v1 No-Prior Fallback Diagnostic ===")
    print("Working name only. This is a new predictive sibling stat, not an LBI variant and not public.")
    print("Harness used: LBI variant checkpoint harness, because this target is future HR/BBE.")
    print("Barrel remains Barrel/BBE where referenced; no PA fields are used in this harness.")
    print("Scoring: plus-style percentile component scoring within each checkpoint pool.")
    print("Leakage: all inputs are checkpoint-to-date only; EV90 is to-date 90th-pctile EV; targets are disjoint forward windows.")
    print(
        "This pass changes only the no-prior fallback path. Players with real prior-season context "
        "keep the existing L2 M150 xHR / M100 Thunder behavior."
    )
    print("Reliability weights use current BBE because this harness is BBE-based and does not carry PA.")
    models = {
        STORM_L2_CURRENT_COLUMN: STORM_L2_CURRENT_LABEL,
        STORM_WATCH_V1_COLUMN: STORM_WATCH_V1_LABEL,
        **{column: label for column, (label, _) in STORM_NO_PRIOR_VARIANTS.items()},
    }
    print(
        f"Storm Watch v1 no-prior M values: xHR {STORM_NO_PRIOR_STAB_M['xhr']} BBE | "
        f"Thunder {STORM_NO_PRIOR_STAB_M['thunder']} BBE | EV90 {STORM_NO_PRIOR_STAB_M['ev90']} BBE."
    )
    print_storm_no_prior_current_check(models, stab_m)
    print_storm_phase2_shrinkage_summary(monthly)
    may = monthly[monthly["window"].astype("string").str.contains("-05-01", regex=False, na=False)].copy()
    full_models = {
        "candidate_lbi_v14_heavy_thunder": "Heavy Thunder May bar",
        "storm_phase2_raw_combo": "raw combo 50 xHR / 25 Thunder / 25 EV90",
        **models,
    }
    print_storm_no_prior_guardrail(monthly, models)

    print("\n=== PART 3: Overall Stat Check, May 1 ===")
    may_table = storm_metrics_table(may, full_models, "futureHrPerBbe")
    for _, row in may_table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())

    print("\n=== PART 3: Overall Stat Check, Six-Week Monthly ===")
    six_week_table = storm_metrics_table(monthly, full_models, "futureHrPerBbe")
    for _, row in six_week_table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())

    print("\n=== PART 3: Overall Stat Check, Rest of Season ===")
    ros_table = storm_metrics_table(rest_monthly, full_models, "futureHrPerBbe")
    for _, row in ros_table.iterrows():
        print_metric_line(str(row["label"]), row.to_dict())

    print_storm_no_prior_split("May 1", may, models)
    print_storm_no_prior_split("Six-week monthly", monthly, models)
    print_storm_no_prior_defensibility(monthly, models)
    print_storm_phase2_volatility(monthly, models)

    print("\n=== Recommendation Inputs ===")
    for column, label in models.items():
        may_row = may_table[may_table["column"].eq(column)].iloc[0]
        six_row = six_week_table[six_week_table["column"].eq(column)].iloc[0]
        ros_row = ros_table[ros_table["column"].eq(column)].iloc[0]
        print(
            f"{label}: May lift {may_row['topDecileLift'] * 100:+.1f}% / P {may_row['pearson']:.3f}; "
            f"6w lift {six_row['topDecileLift'] * 100:+.1f}% / P {six_row['pearson']:.3f}; "
            f"ROS lift {ros_row['topDecileLift'] * 100:+.1f}% / P {ros_row['pearson']:.3f}"
        )


def print_top(rows: pd.DataFrame, column: str, title: str, limit: int) -> None:
    print(f"\n=== {title} ===")
    for rank, (_, row) in enumerate(rows.sort_values(column, ascending=False).head(limit).iterrows(), start=1):
        print(
            f"{rank:2}. {row['player']} ({int(row['season'])}) | {column} {row[column]:.1f} | "
            f"future HR/BBE {row['futureHrPerBbe'] * 100:.2f}% | "
            f"xHR/BBE {row['xhrPerBbe'] * 100:.2f}% | Brl% {row['barrelRate'] * 100:.1f}% | "
            f"LA25-40/100+ {row['la25_40_100Rate'] * 100:.1f}% | "
            f"LA25-40/105+ {row['la25_40_105Rate'] * 100:.1f}%"
        )


def print_bottom(rows: pd.DataFrame, column: str, title: str, limit: int) -> None:
    print(f"\n=== {title} ===")
    for rank, (_, row) in enumerate(rows.sort_values(column, ascending=True).head(limit).iterrows(), start=1):
        print(
            f"{rank:2}. {row['player']} ({int(row['season'])}) | {column} {row[column]:.1f} | "
            f"future HR/BBE {row['futureHrPerBbe'] * 100:.2f}% | "
            f"xHR/BBE {row['xhrPerBbe'] * 100:.2f}% | Brl% {row['barrelRate'] * 100:.1f}% | "
            f"Thunder {row['la25_40_105Rate'] * 100:.1f}% | HH% {row['hardHitRate'] * 100:.1f}%"
        )


def print_feature_diagnostics(rows: pd.DataFrame, title: str) -> None:
    qualified = rows.dropna(subset=["la25_40_105Rate", "barrelRate", "xhrPerBbe"]).copy()
    if qualified.empty:
        return
    zero_rate = qualified["la25_40_105Rate"].eq(0).mean()
    print(f"\n=== {title}: hrWindowThunderRate Diagnostics ===")
    print(
        f"Correlation with Barrel%: Pearson {qualified['la25_40_105Rate'].corr(qualified['barrelRate'], method='pearson'):.3f}, "
        f"Spearman {qualified['la25_40_105Rate'].corr(qualified['barrelRate'], method='spearman'):.3f}"
    )
    print(
        f"Correlation with adjusted xHR/BBE: Pearson {qualified['la25_40_105Rate'].corr(qualified['xhrPerBbe'], method='pearson'):.3f}, "
        f"Spearman {qualified['la25_40_105Rate'].corr(qualified['xhrPerBbe'], method='spearman'):.3f}"
    )
    print(
        f"Average hrWindowThunderRate {qualified['la25_40_105Rate'].mean() * 100:.2f}% | "
        f"median {qualified['la25_40_105Rate'].median() * 100:.2f}% | zero-count rate {zero_rate * 100:.1f}%"
    )
    early = qualified[qualified["window"].astype("string").str.contains("-05-01", regex=False, na=False)]
    if not early.empty:
        print(
            f"May 1 checkpoints: average {early['la25_40_105Rate'].mean() * 100:.2f}% | "
            f"median {early['la25_40_105Rate'].median() * 100:.2f}% | zero-count {early['la25_40_105Rate'].eq(0).mean() * 100:.1f}%"
        )


def print_sanity_players(rows: pd.DataFrame) -> None:
    names = [
        "Aaron Judge",
        "Shohei Ohtani",
        "Kyle Schwarber",
        "Cal Raleigh",
        "Yordan Alvarez",
        "James Wood",
        "Munetaka Murakami",
        "Bobby Witt",
        "Bobby Witt Jr.",
        "Alex Bregman",
        "Isaac Paredes",
        "Ke'Bryan Hayes",
        "Nico Hoerner",
        "Yandy Díaz",
        "Yandy Diaz",
        "Mike Zunino",
    ]
    final_2025 = rows[(rows["season"].eq(2025)) & (rows["window"].astype("string").str.contains("2025-08-01", regex=False, na=False))]
    if final_2025.empty:
        final_2025 = rows[rows["season"].eq(2025)]
    print("\n=== Sanity Players: Final 2025 Checkpoint Where Present ===")
    for name in names:
        sample = final_2025[final_2025["player"].astype("string").str.casefold().eq(name.casefold())]
        if sample.empty:
            continue
        row = sample.sort_values("candidate_lbi_xhr50_barrel", ascending=False).iloc[0]
        print(
            f"{row['player']}: current {row['current_lbi_v12_proxy']:.1f} | "
            f"B {row['candidate_lbi_xhr50_barrel']:.1f} | C {row['candidate_lbi_xhr55_105_25']:.1f} | "
            f"D {row['candidate_lbi_no_hh_barrel25']:.1f} | E {row['candidate_lbi_no_hh_105_30']:.1f} | "
            f"F {row['candidate_lbi_conservative_middle']:.1f} | xHR/BBE {row['xhrPerBbe'] * 100:.2f}% | "
            f"Brl% {row['barrelRate'] * 100:.1f}% | Thunder {row['la25_40_105Rate'] * 100:.1f}% | "
            f"HH% {row['hardHitRate'] * 100:.1f}% | future HR/BBE {row['futureHrPerBbe'] * 100:.2f}%"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest a candidate LBI component mix against future HR/BBE.")
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--next-weeks", type=int, default=DEFAULT_NEXT_WEEKS)
    parser.add_argument("--min-first-bbe", type=int, default=DEFAULT_MIN_FIRST_BBE)
    parser.add_argument("--min-future-bbe", type=int, default=DEFAULT_MIN_FUTURE_BBE)
    parser.add_argument("--top", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="sklearn")
    args = parse_args()
    monthly_frames = []
    rest_frames = []
    all_star_frames = []

    print("=== Storm Watch Phase 2 Diagnostic ===")
    print("Test focus: light-touch stabilization for the May/early six-week HR-surge signal.")
    print("Production LBI v1.3 is unchanged; this script only reports diagnostic shadow formulas.")
    print("Scaling: plus-style percentile component scoring within each checkpoint pool.")
    print("Adjusted xHR proxy: Home Run Tracker detail parks-cleared count / 30, date-filtered.")
    print(f"Monthly target: future HR/BBE over {args.next_weeks} weeks after May 1, June 1, July 1, August 1.")
    print("All-Star target: second-half HR/BBE.")

    for season in args.seasons:
        pitch_path = cache_path_for_season(season)
        detail_path = hrt_detail_path_for_season(season)
        pitches = load_pitch_cache(pitch_path)
        details = load_hrt_details(detail_path)
        names = load_name_map(season, details)

        for window in monthly_windows(season, pitches, args.next_weeks):
            monthly_frames.append(
                prepare_window(pitches, details, names, window, args.min_first_bbe, args.min_future_bbe)
            )
        for window in rest_of_season_windows(season, pitches):
            rest_frames.append(
                prepare_window(pitches, details, names, window, args.min_first_bbe, args.min_future_bbe)
            )
        all_star_frames.append(
            prepare_window(
                pitches,
                details,
                names,
                all_star_window(season),
                args.min_first_bbe,
                args.min_future_bbe,
            )
        )
        print(f"{season}: loaded {pitch_path.name}, {detail_path.name}")

    monthly = pd.concat(monthly_frames, ignore_index=True) if monthly_frames else pd.DataFrame()
    rest_monthly = pd.concat(rest_frames, ignore_index=True) if rest_frames else pd.DataFrame()
    all_star = pd.concat(all_star_frames, ignore_index=True) if all_star_frames else pd.DataFrame()
    if monthly.empty or all_star.empty or rest_monthly.empty:
        raise RuntimeError("No diagnostic rows produced.")
    print_storm_phase2_diagnostic(monthly, rest_monthly)
    return

    print_core_report("Pooled Monthly Checkpoints vs Future HR/BBE", monthly, "futureHrPerBbe")
    print_core_report("Pooled Monthly Checkpoints vs Future adjusted xHR/BBE", monthly, "futureAdjustedXhrPerBbe")
    print_core_report("Pooled Monthly Checkpoints vs Future HR-capable event rate", monthly, "futureHrCapableRate")
    print_core_report("All-Star First-Half to Second-Half vs Future HR/BBE", all_star, "futureHrPerBbe")
    print_core_report("All-Star First-Half to Second-Half vs Future adjusted xHR/BBE", all_star, "futureAdjustedXhrPerBbe")
    print_report("Pooled Monthly Checkpoints vs Future HR/BBE", metric_report(monthly, "futureHrPerBbe"))
    print_report("All-Star First-Half to Second-Half vs Future HR/BBE", metric_report(all_star, "futureHrPerBbe"))
    print_feature_diagnostics(monthly, "Monthly checkpoints")
    print_feature_diagnostics(all_star, "All-Star split")

    by_season = []
    for season, frame in monthly.groupby("season"):
        current = metric_report(frame, "futureHrPerBbe").set_index("metric")
        by_season.append(
            {
                "season": int(season),
                "currentPearson": current.loc["Current LBI v1.2 proxy", "pearson"],
                "candidatePearson": current.loc["Requested LA 25-40 / 100+ LBI", "pearson"],
                "splitPearson": current.loc["Split LA 25-40 / 100+ and 105+ LBI", "pearson"],
                "pure105Pearson": current.loc["Pure LA 25-40 / 105+ LBI", "pearson"],
                "pure10515Pearson": current.loc["Pure LA 25-40 / 105+ LBI at 15%", "pearson"],
                "flippedPearson": current.loc["Flipped Barrel and 105+ LBI", "pearson"],
                "xhr55Pearson": current.loc["55% xHR / 25% 105+ LBI", "pearson"],
                "xhr50SplitPearson": current.loc["50% xHR / split 5 points LBI", "pearson"],
                "xhr50BarrelPearson": current.loc["50% xHR / 5 points to Barrel LBI", "pearson"],
                "xhr50_105Pearson": current.loc["50% xHR / 5 points to 105+ LBI", "pearson"],
                "noHhBarrelPearson": current.loc["No Hard Hit / 25% Barrel LBI", "pearson"],
                "noHh105Pearson": current.loc["No Hard Hit / 30% 105+ LBI", "pearson"],
                "conservativePearson": current.loc["Conservative Middle 55/20/20/5 LBI", "pearson"],
                "currentSpearman": current.loc["Current LBI v1.2 proxy", "spearman"],
                "candidateSpearman": current.loc["Requested LA 25-40 / 100+ LBI", "spearman"],
                "splitSpearman": current.loc["Split LA 25-40 / 100+ and 105+ LBI", "spearman"],
                "pure105Spearman": current.loc["Pure LA 25-40 / 105+ LBI", "spearman"],
                "pure10515Spearman": current.loc["Pure LA 25-40 / 105+ LBI at 15%", "spearman"],
                "flippedSpearman": current.loc["Flipped Barrel and 105+ LBI", "spearman"],
                "xhr55Spearman": current.loc["55% xHR / 25% 105+ LBI", "spearman"],
                "xhr50SplitSpearman": current.loc["50% xHR / split 5 points LBI", "spearman"],
                "xhr50BarrelSpearman": current.loc["50% xHR / 5 points to Barrel LBI", "spearman"],
                "xhr50_105Spearman": current.loc["50% xHR / 5 points to 105+ LBI", "spearman"],
                "noHhBarrelSpearman": current.loc["No Hard Hit / 25% Barrel LBI", "spearman"],
                "noHh105Spearman": current.loc["No Hard Hit / 30% 105+ LBI", "spearman"],
                "conservativeSpearman": current.loc["Conservative Middle 55/20/20/5 LBI", "spearman"],
                "currentLift": current.loc["Current LBI v1.2 proxy", "topDecileLift"],
                "candidateLift": current.loc["Requested LA 25-40 / 100+ LBI", "topDecileLift"],
                "splitLift": current.loc["Split LA 25-40 / 100+ and 105+ LBI", "topDecileLift"],
                "pure105Lift": current.loc["Pure LA 25-40 / 105+ LBI", "topDecileLift"],
                "pure10515Lift": current.loc["Pure LA 25-40 / 105+ LBI at 15%", "topDecileLift"],
                "flippedLift": current.loc["Flipped Barrel and 105+ LBI", "topDecileLift"],
                "xhr55Lift": current.loc["55% xHR / 25% 105+ LBI", "topDecileLift"],
                "xhr50SplitLift": current.loc["50% xHR / split 5 points LBI", "topDecileLift"],
                "xhr50BarrelLift": current.loc["50% xHR / 5 points to Barrel LBI", "topDecileLift"],
                "xhr50_105Lift": current.loc["50% xHR / 5 points to 105+ LBI", "topDecileLift"],
                "noHhBarrelLift": current.loc["No Hard Hit / 25% Barrel LBI", "topDecileLift"],
                "noHh105Lift": current.loc["No Hard Hit / 30% 105+ LBI", "topDecileLift"],
                "conservativeLift": current.loc["Conservative Middle 55/20/20/5 LBI", "topDecileLift"],
                "n": int(current.loc["Current LBI v1.2 proxy", "n"]),
            }
        )
    print("\n=== Monthly Season-by-Season: Current vs Requested vs Split-EV Candidate ===")
    for row in by_season:
        print(
            f"{row['season']}: n={row['n']} | pearson {row['currentPearson']:.3f} -> "
            f"{row['candidatePearson']:.3f} / {row['splitPearson']:.3f} / {row['pure105Pearson']:.3f} / "
            f"{row['pure10515Pearson']:.3f} / {row['flippedPearson']:.3f} / {row['xhr55Pearson']:.3f} / "
            f"{row['xhr50SplitPearson']:.3f} / {row['xhr50BarrelPearson']:.3f} / {row['xhr50_105Pearson']:.3f} / "
            f"{row['noHhBarrelPearson']:.3f} / {row['noHh105Pearson']:.3f} / {row['conservativePearson']:.3f} | "
            f"spearman {row['currentSpearman']:.3f} -> {row['candidateSpearman']:.3f} / "
            f"{row['splitSpearman']:.3f} / {row['pure105Spearman']:.3f} / {row['pure10515Spearman']:.3f} / "
            f"{row['flippedSpearman']:.3f} / {row['xhr55Spearman']:.3f} / {row['xhr50SplitSpearman']:.3f} / "
            f"{row['xhr50BarrelSpearman']:.3f} / {row['xhr50_105Spearman']:.3f} / "
            f"{row['noHhBarrelSpearman']:.3f} / {row['noHh105Spearman']:.3f} / {row['conservativeSpearman']:.3f} | "
            f"top-decile lift "
            f"{row['currentLift'] * 100:+.1f}% -> {row['candidateLift'] * 100:+.1f}% / "
            f"{row['splitLift'] * 100:+.1f}% / {row['pure105Lift'] * 100:+.1f}% / "
            f"{row['pure10515Lift'] * 100:+.1f}% / {row['flippedLift'] * 100:+.1f}% / "
            f"{row['xhr55Lift'] * 100:+.1f}% / {row['xhr50SplitLift'] * 100:+.1f}% / "
            f"{row['xhr50BarrelLift'] * 100:+.1f}% / {row['xhr50_105Lift'] * 100:+.1f}% / "
            f"{row['noHhBarrelLift'] * 100:+.1f}% / {row['noHh105Lift'] * 100:+.1f}% / "
            f"{row['conservativeLift'] * 100:+.1f}%"
        )

    final_2025 = monthly[
        monthly["season"].eq(2025) & monthly["window"].astype("string").str.contains("2025-08-01", regex=False, na=False)
    ].copy()
    if final_2025.empty:
        final_2025 = monthly[monthly["season"].eq(2025)].copy()
    print_top(final_2025, "candidate_lbi_xhr50_barrel", "Top 30 Final 2025 Checkpoint: Formula B", 30)
    print_bottom(final_2025, "candidate_lbi_xhr50_barrel", "Bottom 30 Final 2025 Checkpoint: Formula B", 30)
    print_sanity_players(monthly)

    print_top(monthly, "current_lbi_v12_proxy", "Top Current LBI v1.2 Proxy Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_la25_40_100", "Top Requested Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_split_100_105", "Top Split-EV Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_la25_40_105", "Top Pure-105 Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_la25_40_105_15", "Top Pure-105 at 15% Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_flipped_barrel_105", "Top Flipped Barrel/105+ Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_xhr55_105_25", "Top 55% xHR / 25% 105+ Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_xhr50_split", "Top 50% xHR / Split 5 Points Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_xhr50_barrel", "Top 50% xHR / 5 Points to Barrel Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_xhr50_105", "Top 50% xHR / 5 Points to 105+ Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_no_hh_barrel25", "Top No Hard Hit / 25% Barrel Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_no_hh_105_30", "Top No Hard Hit / 30% 105+ Candidate Player-Checkpoints", args.top)
    print_top(monthly, "candidate_lbi_conservative_middle", "Top Conservative Middle Candidate Player-Checkpoints", args.top)


if __name__ == "__main__":
    main()
