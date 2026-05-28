#!/usr/bin/env python3
"""Canonical Longball Threat predictive HR/PA diagnostic.

This script is internal tooling only. It does not write frontend data, alter
the public Longball Index, or publish Longball Threat.

Canonical harness:
- Seasons: 2021-2025.
- Monthly checkpoints: May 1, June 1, July 1, and August 1.
- Target: future actual HR/PA over the next six weeks.
- Raw predictive results are reported separately from plus-scaled display
  results so formula testing does not get mixed with presentation scaling.

xHR source rule:
- Full-season Home Run Tracker aggregate adjusted xHR is reported for
  diagnostics, but it is not valid for checkpoint prediction because it leaks
  future information from later in the season.
- ``hrt_event_ct30_proxy_pa`` is the valid checkpoint xHR proxy in this local
  harness; it sums event-level Home Run Tracker ``ct / 30`` through the
  checkpoint and divides by PA.

Age and prior handling:
- Player age is fetched from the MLB Stats API people endpoint, cached
  locally, and calculated at each checkpoint date from player birth dates.
- Model E currently combines dynamic reliability, a three-year weighted
  multi-season prior, and age adjustment. It is the current best explainable
  diagnostic candidate, but Longball Threat remains internal and should not be
  published until further validation.
- Model E plus league-average no-prior fallback is the safest future public
  beta candidate. Excluding no-prior players improves correlations, but it is
  not viable for a public leaderboard; current-only fallback is too volatile
  for public use.

Recent incremental tests:
- Contact xISO, EV90, and pull-air EV additions improved Pearson only
  marginally and did not clearly improve top-decile lift, so they remain
  diagnostic comparisons rather than a new preferred model.
- Pull AIR%, pulled barrels, threshold Pull-Air Juice definitions, and weighted
  Pull-Air Juice were tested. Official Savant Pull AIR% is accessible, and the
  internal pullAirRate approximation matches it closely enough for diagnostics.
  Pull-Air Juice is mostly in the pulled-barrel family; the best weighted
  Pull-Air Juice definition narrowly beat pulled barrels, but the edge was tiny.
  It should remain a context/research stat for now, not a Longball Threat input
  or standalone public leaderboard. A useful future editorial angle is Pull
  AIR% misconceptions: pulled-air shape alone is not enough without loud contact.
- Official Savant Blast metrics are modern-era only. The public player-level
  CSV exposes Blast rates. Coverage is reliable mostly from 2024 forward, with
  2023 partial. The simple export has not proven checkpoint-date safe in this
  harness because date filters did not affect the output, so checkpoint tests
  use local event-level bat-speed proxies and label them as proxies rather than
  official Blast/PA. Modern-era Blast/PA proxies add only marginal lift to
  Model E, so Blast/PA should be tracked and researched, but it should not be
  added to core Longball Threat yet.
- Ridge remains a benchmark for whether a simple formula is leaving obvious
  signal on the table, not a public formula candidate.
- YoungE initially looked promising, but the gain was mostly a
  sample/composition effect from adding young no-prior player-checkpoints.
  When compared apples-to-apples, YoungE does not meaningfully beat current
  Model E. For any future public Longball Threat beta, no-prior players should
  use league-average prior fallback; current-only fallback is too volatile for
  public use. YoungE should remain a diagnostic footnote, not the formula.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import unicodedata
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))


DEFAULT_SEASON = 2025
DEFAULT_CHECKPOINT_MONTH_DAYS = ["05-01", "06-01", "07-01", "08-01"]
DEFAULT_NEXT_WEEKS = 6
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
SANITY_PLAYERS = [
    "Aaron Judge",
    "Kyle Schwarber",
    "Yordan Alvarez",
    "Yordan Álvarez",
    "James Wood",
    "Munetaka Murakami",
    "Ke'Bryan Hayes",
    "Nico Hoerner",
    "Isaac Paredes",
    "Bobby Witt Jr.",
]

THREAT_VARIANTS = {
    "threat_c_plus_scaled_75_xhr_25_barrel": {
        "label": "threat_c_plus_scaled_75_xhr_25_barrel",
        "scoreColumn": "threat_c_plus_scaled_75_xhr_25_barrel",
        "rankColumn": "threat_c_plus_rank",
        "weights": {
            "adjustedXhrPerPa": 0.75,
            "barrelsPerPa": 0.25,
        },
    },
}

LBI_PROXY_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "avgDistanceOnBarrels": 0.125,
    "hardHitRate": 0.075,
}

RIDGE_FEATURE_COLUMNS = [
    "firstAdjustedXhrPerPa",
    "firstBarrelsPerPa",
    "firstPrior2AdjustedXhrPerPa",
    "firstPrior2BarrelsPerPa",
    "firstPrior3AdjustedXhrPerPa",
    "firstPrior3BarrelsPerPa",
    "firstXhrTrajectoryVsPrior3",
    "firstBarrelTrajectoryVsPrior3",
    "firstAge",
    "firstHardHitAirBbePerPa",
    "firstHardHitPulledAirBbePerPa",
    "firstCrushedPulledAirBbePerPa",
    "firstEv90OnPulledAirShrunk10",
    "firstPulledAirLoudQuality",
    "firstEv90",
    "firstPullAirEvInteraction",
    "firstLbiProxy",
    "firstContactXisoProxy",
]

DYNAMIC_M_BARREL_GRID = [50, 75, 90, 100, 125, 150]
DYNAMIC_M_XHR_GRID = [150, 200, 225, 250, 300, 350, 400]
DYNAMIC_BLEND_XHR_GRID = [0.60, 0.65, 0.70, 0.75, 0.80]
MODERATE_AGE_CURVE = {
    20: 0.890,
    21: 0.920,
    22: 0.950,
    23: 0.975,
    24: 0.990,
    25: 0.998,
    26: 1.000,
    27: 1.000,
    28: 0.998,
    29: 0.995,
    30: 0.985,
    31: 0.970,
    32: 0.955,
    33: 0.935,
    34: 0.910,
    35: 0.880,
    36: 0.845,
    37: 0.805,
    38: 0.760,
    39: 0.710,
    40: 0.660,
}


def ev_slug(threshold: float) -> str:
    return str(threshold).replace(".", "p")


def pascal_slug(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def pull_air_juice_specs() -> list[dict[str, Any]]:
    raw_specs: list[dict[str, Any]] = [
        {
            "family": "A",
            "slug": "a1_pulled_barrel",
            "label": "A1 pulled official barrels",
            "shortLabel": "A1 pulled barrels",
            "mode": "barrel",
        },
        {
            "family": "B",
            "slug": "b1_la15_40_ev100",
            "label": "B1 pulled, 15-40 deg, 100+ mph",
            "shortLabel": "B1 100+ / 15-40",
            "mode": "threshold",
            "low": 15,
            "high": 40,
            "threshold": 100,
        },
        {
            "family": "B",
            "slug": "b2_la15_40_ev102p5",
            "label": "B2 pulled, 15-40 deg, 102.5+ mph",
            "shortLabel": "B2 102.5+ / 15-40",
            "mode": "threshold",
            "low": 15,
            "high": 40,
            "threshold": 102.5,
        },
        {
            "family": "B",
            "slug": "b3_la15_40_ev105",
            "label": "B3 pulled, 15-40 deg, 105+ mph",
            "shortLabel": "B3 105+ / 15-40",
            "mode": "threshold",
            "low": 15,
            "high": 40,
            "threshold": 105,
        },
        {
            "family": "B",
            "slug": "b4_la20_38_ev100",
            "label": "B4 pulled, 20-38 deg, 100+ mph",
            "shortLabel": "B4 100+ / 20-38",
            "mode": "threshold",
            "low": 20,
            "high": 38,
            "threshold": 100,
        },
        {
            "family": "B",
            "slug": "b5_la20_38_ev102p5",
            "label": "B5 pulled, 20-38 deg, 102.5+ mph",
            "shortLabel": "B5 102.5+ / 20-38",
            "mode": "threshold",
            "low": 20,
            "high": 38,
            "threshold": 102.5,
        },
        {
            "family": "B",
            "slug": "b6_la20_38_ev105",
            "label": "B6 pulled, 20-38 deg, 105+ mph",
            "shortLabel": "B6 105+ / 20-38",
            "mode": "threshold",
            "low": 20,
            "high": 38,
            "threshold": 105,
        },
        {
            "family": "C",
            "slug": "c1_weighted_plateau",
            "label": "C1 weighted pulled air, EV 95-105, LA plateau 24-33",
            "shortLabel": "C1 weighted plateau",
            "mode": "weighted",
            "evLow": 95,
            "evHigh": 105,
            "angleMode": "plateau",
        },
        {
            "family": "C",
            "slug": "c1_steep_weighted_plateau",
            "label": "C1 steep weighted pulled air, EV 98-108, LA plateau 24-33",
            "shortLabel": "C1 steep plateau",
            "mode": "weighted",
            "evLow": 98,
            "evHigh": 108,
            "angleMode": "plateau",
        },
        {
            "family": "C",
            "slug": "c2_weighted_triangular",
            "label": "C2 weighted pulled air, EV 95-105, LA peak 28",
            "shortLabel": "C2 weighted triangle",
            "mode": "weighted",
            "evLow": 95,
            "evHigh": 105,
            "angleMode": "triangle",
        },
        {
            "family": "C",
            "slug": "c2_steep_weighted_triangular",
            "label": "C2 steep weighted pulled air, EV 98-108, LA peak 28",
            "shortLabel": "C2 steep triangle",
            "mode": "weighted",
            "evLow": 98,
            "evHigh": 108,
            "angleMode": "triangle",
        },
        {
            "family": "D",
            "slug": "d1_fly_line_ev100",
            "label": "D1 pulled fly balls + liners, 100+ mph",
            "shortLabel": "D1 fly+LD 100+",
            "mode": "bbtype",
            "threshold": 100,
            "bbtype": "fly_line",
        },
        {
            "family": "D",
            "slug": "d2_fly_line_ev105",
            "label": "D2 pulled fly balls + liners, 105+ mph",
            "shortLabel": "D2 fly+LD 105+",
            "mode": "bbtype",
            "threshold": 105,
            "bbtype": "fly_line",
        },
        {
            "family": "D",
            "slug": "d3_fly_ball_ev100",
            "label": "D3 pulled fly balls, 100+ mph",
            "shortLabel": "D3 fly 100+",
            "mode": "bbtype",
            "threshold": 100,
            "bbtype": "fly_ball_only",
        },
        {
            "family": "D",
            "slug": "d4_fly_ball_ev105",
            "label": "D4 pulled fly balls, 105+ mph",
            "shortLabel": "D4 fly 105+",
            "mode": "bbtype",
            "threshold": 105,
            "bbtype": "fly_ball_only",
        },
    ]
    for spec in raw_specs:
        spec["columnSlug"] = pascal_slug(spec["slug"])
    return raw_specs


PULL_AIR_JUICE_SPECS = pull_air_juice_specs()
AGE_CURVE_STRENGTHS = {
    "Age1Moderate": 1.00,
    "Age2Conservative": 0.50,
    "Age3Aggressive": 1.35,
}
MULTI_PRIOR_CACHE: dict[int, pd.DataFrame] = {}
PLAYER_PEOPLE_CACHE_PATH = Path("data/cache/longball-threat-backtest/player-people-cache.json")
MLB_PEOPLE_ENDPOINT = "https://statsapi.mlb.com/api/v1/people"
BAT_TRACKING_CACHE_DIR = Path("data/cache/longball-threat-backtest")


@dataclass(frozen=True)
class BacktestCheckpoint:
    checkpoint: date
    period_end: date
    rows: pd.DataFrame


VALIDATION_MODELS = {
    "Model E: 3-year prior + age": "firstDynamicPrior3AgeAdjusted",
    "No-prior Policy B: league-average prior fallback": "firstDynamicPrior3NoPriorLeagueFallback",
    "No-prior Policy C: current-only fallback": "firstDynamicPrior3NoPriorCurrentOnlyFallback",
    "No-prior Policy D: hybrid rookie fallback": "firstDynamicPrior3NoPriorHybridFallback",
    "Age1 moderate age-adjusted priors": "firstDynamicPrior3AgeCurveModerate",
    "Age2 conservative age-adjusted priors": "firstDynamicPrior3AgeCurveConservative",
    "Age3 aggressive age-adjusted priors": "firstDynamicPrior3AgeCurveAggressive",
    "YoungA <=23 Age2 prior only": "firstYoungAUnder23Age2",
    "YoungB <=23 Age1 prior only": "firstYoungBUnder23Age1",
    "YoungC <=23 +2% final": "firstYoungCUnder23Boost2",
    "YoungC <=23 +3% final": "firstYoungCUnder23Boost3",
    "YoungC <=23 +4% final": "firstYoungCUnder23Boost4",
    "YoungD <=24 Age2 prior only": "firstYoungDUnder24Age2",
    "YoungE <=23 and <2 prior Age2": "firstYoungEUnder23LowPriorAge2",
    "YoungE with league-average no-prior fallback": "firstYoungEWithLeagueFallback",
    "dynamic reliability baseline": "firstDynamicBaseM150X150B060",
    "fixed prior-stabilized": "firstPriorStabilized",
    "threat_c_raw_75_xhr_25_barrel": "firstRawThreatC",
    "barrel_pa": "firstBarrelsPerPa",
    "hrt_event_ct30_proxy_pa": "firstAdjustedXhrPerPa",
}


def normalize_name(value: Any) -> str:
    text = str(value or "").replace("’", "'").strip()
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_text.lower().replace(".", "").split())


def display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def default_checkpoints_for_season(season: int) -> list[date]:
    return [parse_date(f"{season}-{month_day}") for month_day in DEFAULT_CHECKPOINT_MONTH_DAYS]


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def season_lbi_path(season: int) -> Path:
    archive = Path(f"public/data/longball-index-{season}.json")
    if archive.exists():
        return archive
    return Path("public/data/hr-distance-latest.json")


def pitch_cache_paths(season: int) -> list[Path]:
    split_paths = [
        Path(f"data/cache/longball-threat-backtest/statcast-pitches-{season}-first.csv"),
        Path(f"data/cache/longball-threat-backtest/statcast-pitches-{season}-second.csv"),
    ]
    if all(path.exists() for path in split_paths):
        return split_paths
    canonical = Path("data/raw/statcast-pitches.csv")
    if canonical.exists():
        return [canonical]
    bbe = Path(f"data/raw/statcast-bbe-events-{season}.csv")
    return [bbe]


def hrt_detail_path(season: int) -> Path:
    return Path(f"data/cache/longball-threat-backtest/hrt-details-{season}-adj_xhr.csv")


def load_lbi_players(path: Path) -> tuple[pd.DataFrame, dict[int, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = payload.get("players", [])
    if not isinstance(players, list) or not players:
        raise RuntimeError(f"No players found in {path}")

    frame = pd.DataFrame(players)
    frame["batter"] = to_numeric(frame["batter"]).astype("Int64")
    for column in ["bbe", "hr", "xhr", "longballIndex", "avgDistanceOnBarrels"]:
        frame[column] = to_numeric(frame[column])
    frame["lbiRank"] = frame["longballIndex"].rank(method="first", ascending=False).astype(int)
    frame["nameKey"] = frame["player"].map(normalize_name)
    names = {
        int(row["batter"]): str(row["player"])
        for _, row in frame.dropna(subset=["batter", "player"]).iterrows()
    }
    return frame, names


def aggregate_xhr_frame(players: pd.DataFrame, prefix: str = "first") -> pd.DataFrame:
    frame = players[["batter", "xhr"]].copy()
    frame = frame.rename(columns={"xhr": f"{prefix}HrtAggregateAdjustedXhr"})
    frame[f"{prefix}HrtAggregateAdjustedXhr"] = to_numeric(frame[f"{prefix}HrtAggregateAdjustedXhr"])
    return frame


def load_pitch_frames(paths: list[Path]) -> tuple[pd.DataFrame, str]:
    frames: list[pd.DataFrame] = []
    used: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        frames.append(pd.read_csv(path))
        used.append(str(path))
    if not frames:
        raise RuntimeError(f"No pitch cache files found: {', '.join(str(path) for path in paths)}")
    frame = pd.concat(frames, ignore_index=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce").dt.date
    for column in [
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "batter",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "hit_distance_sc",
        "estimated_ba_using_speedangle",
        "estimated_slg_using_speedangle",
        "hc_x",
        "bat_speed",
        "swing_length",
        "attack_angle",
        "attack_direction",
        "swing_path_tilt",
    ]:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = to_numeric(frame[column])
    return frame.dropna(subset=["game_date", "batter"]).copy(), ", ".join(used)


def load_hrt_details(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"Missing Home Run Tracker detail cache: {path}")
    details = pd.read_csv(path)
    for column in ["game_date", "batter_id", "ct"]:
        if column not in details.columns:
            raise RuntimeError(f"{path} is missing required column: {column}")
    details["game_date"] = pd.to_datetime(details["game_date"], errors="coerce").dt.date
    details["batter_id"] = to_numeric(details["batter_id"])
    details["ct"] = to_numeric(details["ct"]).clip(0, 30)
    return details.dropna(subset=["game_date", "batter_id"]).copy()


def bat_tracking_cache_path(season: int) -> Path:
    return BAT_TRACKING_CACHE_DIR / f"bat-tracking-{season}.csv"


def load_official_bat_tracking(season: int) -> pd.DataFrame:
    path = bat_tracking_cache_path(season)
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if "id" not in frame.columns:
        return pd.DataFrame()
    frame = frame.rename(columns={"id": "batter"})
    frame["batter"] = to_numeric(frame["batter"]).astype("Int64")
    for column in [
        "swings_competitive",
        "contact",
        "avg_bat_speed",
        "hard_swing_rate",
        "squared_up_per_bat_contact",
        "squared_up_per_swing",
        "blast_per_bat_contact",
        "blast_per_swing",
        "batted_ball_events",
    ]:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = to_numeric(frame[column])
    frame["officialBlastCount"] = frame["blast_per_swing"] * frame["swings_competitive"]
    frame["officialSquaredUpCount"] = frame["squared_up_per_swing"] * frame["swings_competitive"]
    return frame[
        [
            "batter",
            "name",
            "swings_competitive",
            "contact",
            "avg_bat_speed",
            "hard_swing_rate",
            "squared_up_per_bat_contact",
            "squared_up_per_swing",
            "blast_per_bat_contact",
            "blast_per_swing",
            "batted_ball_events",
            "officialBlastCount",
            "officialSquaredUpCount",
        ]
    ].dropna(subset=["batter"]).copy()


def load_prior_season_rates(season: int) -> pd.DataFrame:
    try:
        _, _, pitches, details, _, _, _ = load_season_context(season - 1)
    except Exception as exc:
        print(f"Prior-season stabilization unavailable for {season}: {exc}")
        return pd.DataFrame(columns=["batter", "priorAdjustedXhrPerPa", "priorBarrelsPerPa"])

    season_start = min(pitches["game_date"])
    season_end = max(pitches["game_date"])
    stats = pitch_window_stats(pitches, season_start, season_end, "prior")
    xhr = adjusted_xhr(details, season_start, season_end, "prior")
    prior = stats.merge(xhr, on="batter", how="left")
    for column in ["priorPa", "priorBarrels", "priorAdjustedXhr"]:
        prior[column] = to_numeric(prior[column]).fillna(0)
    prior["priorAdjustedXhrPerPa"] = prior["priorAdjustedXhr"] / prior["priorPa"].where(prior["priorPa"].gt(0))
    prior["priorBarrelsPerPa"] = prior["priorBarrels"] / prior["priorPa"].where(prior["priorPa"].gt(0))
    return prior[["batter", "priorAdjustedXhrPerPa", "priorBarrelsPerPa"]]


def full_season_prior_rate_frame(season: int) -> pd.DataFrame:
    if season in MULTI_PRIOR_CACHE:
        return MULTI_PRIOR_CACHE[season].copy()
    try:
        _, _, pitches, details, _, _, _ = load_season_context(season)
    except Exception:
        frame = pd.DataFrame(columns=["batter", "priorSeasonAdjustedXhrPerPa", "priorSeasonBarrelsPerPa"])
        MULTI_PRIOR_CACHE[season] = frame
        return frame.copy()

    season_start = min(pitches["game_date"])
    season_end = max(pitches["game_date"])
    stats = pitch_window_stats(pitches, season_start, season_end, "priorSeason")
    xhr = adjusted_xhr(details, season_start, season_end, "priorSeason")
    frame = stats.merge(xhr, on="batter", how="left")
    for column in ["priorSeasonPa", "priorSeasonBbe", "priorSeasonBarrels", "priorSeasonAdjustedXhr"]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = to_numeric(frame[column]).fillna(0)
    frame = add_rate_columns(frame, "priorSeason")
    frame = frame[["batter", "priorSeasonAdjustedXhrPerPa", "priorSeasonBarrelsPerPa"]].copy()
    MULTI_PRIOR_CACHE[season] = frame
    return frame.copy()


def load_multi_year_prior_rates(season: int) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for offset, weight in [(1, 5), (2, 4), (3, 3)]:
        prior = full_season_prior_rate_frame(season - offset).rename(
            columns={
                "priorSeasonAdjustedXhrPerPa": f"prior{offset}AdjustedXhrPerPa",
                "priorSeasonBarrelsPerPa": f"prior{offset}BarrelsPerPa",
            }
        )
        prior[f"prior{offset}Weight"] = weight
        if merged is None:
            merged = prior
        else:
            merged = merged.merge(prior, on="batter", how="outer")

    if merged is None or merged.empty:
        return pd.DataFrame(columns=["batter"])

    def weighted_average(frame: pd.DataFrame, metric: str, max_offset: int) -> pd.Series:
        numerator = pd.Series(0.0, index=frame.index)
        denominator = pd.Series(0.0, index=frame.index)
        for offset, weight in [(1, 5), (2, 4), (3, 3)]:
            if offset > max_offset:
                continue
            column = f"prior{offset}{metric}"
            values = to_numeric(frame.get(column, pd.Series(index=frame.index, dtype="float64")))
            present = values.notna()
            numerator = numerator + values.fillna(0) * weight
            denominator = denominator + present.astype(float) * weight
        return numerator / denominator.where(denominator.gt(0))

    merged["prior2AdjustedXhrPerPa"] = weighted_average(merged, "AdjustedXhrPerPa", 2)
    merged["prior2BarrelsPerPa"] = weighted_average(merged, "BarrelsPerPa", 2)
    merged["prior3AdjustedXhrPerPa"] = weighted_average(merged, "AdjustedXhrPerPa", 3)
    merged["prior3BarrelsPerPa"] = weighted_average(merged, "BarrelsPerPa", 3)
    merged["priorSeasonCount"] = (
        to_numeric(merged.get("prior1AdjustedXhrPerPa", pd.Series(index=merged.index))).notna().astype(int)
        + to_numeric(merged.get("prior2AdjustedXhrPerPa", pd.Series(index=merged.index))).notna().astype(int)
        + to_numeric(merged.get("prior3AdjustedXhrPerPa", pd.Series(index=merged.index))).notna().astype(int)
    )
    keep = [
        "batter",
        "prior1AdjustedXhrPerPa",
        "prior1BarrelsPerPa",
        "prior2AdjustedXhrPerPa",
        "prior2BarrelsPerPa",
        "prior3AdjustedXhrPerPa",
        "prior3BarrelsPerPa",
        "priorSeasonCount",
    ]
    for column in keep:
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged[keep].copy()


def read_people_cache() -> dict[str, Any]:
    if not PLAYER_PEOPLE_CACHE_PATH.exists():
        return {"source": MLB_PEOPLE_ENDPOINT, "people": []}
    return json.loads(PLAYER_PEOPLE_CACHE_PATH.read_text(encoding="utf-8"))


def write_people_cache(payload: dict[str, Any]) -> None:
    PLAYER_PEOPLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAYER_PEOPLE_CACHE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_mlb_people(player_ids: list[int]) -> list[dict[str, Any]]:
    if not player_ids:
        return []
    query = urllib.parse.urlencode(
        {
            "personIds": ",".join(str(player_id) for player_id in player_ids),
            "fields": "people,id,fullName,birthDate,currentAge",
        }
    )
    request = urllib.request.Request(
        f"{MLB_PEOPLE_ENDPOINT}?{query}",
        headers={"User-Agent": "TheLongBall/LongballThreatDiagnostic"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    people = payload.get("people", [])
    return people if isinstance(people, list) else []


def ensure_age_cache(player_ids: set[int]) -> dict[int, str]:
    payload = read_people_cache()
    people = payload.get("people", [])
    if not isinstance(people, list):
        people = []
    by_id = {int(person["id"]): person for person in people if person.get("id")}
    missing = sorted(player_id for player_id in player_ids if player_id and player_id not in by_id)
    if missing:
        print(f"Fetching MLB Stats API people data for {len(missing)} missing players...")
    for index in range(0, len(missing), 100):
        batch = missing[index : index + 100]
        for person in fetch_mlb_people(batch):
            player_id = person.get("id")
            if player_id:
                by_id[int(player_id)] = person
    if missing:
        write_people_cache(
            {
                "source": MLB_PEOPLE_ENDPOINT,
                "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                "people": list(sorted(by_id.values(), key=lambda person: int(person.get("id", 0)))),
            }
        )

    lookup: dict[int, str] = {}
    for player_id, person in by_id.items():
        birth_date = person.get("birthDate")
        if birth_date:
            lookup[int(player_id)] = str(birth_date)
    return lookup


def load_age_lookup() -> dict[int, str]:
    payload = read_people_cache()
    lookup: dict[int, str] = {}
    for person in payload.get("people", []):
        player_id = person.get("id")
        birth_date = person.get("birthDate")
        if player_id and birth_date:
            lookup[int(player_id)] = str(birth_date)
    return lookup


def age_at_checkpoint(birth_date: str | None, checkpoint: date) -> float | None:
    if not birth_date:
        return None
    try:
        born = parse_date(birth_date)
    except Exception:
        return None
    return (checkpoint - born).days / 365.2425


def age_power_factor(age: Any) -> float | None:
    if pd.isna(age):
        return None
    value = float(age)
    if value <= 23:
        return 1.03
    if value <= 26:
        return 1.02
    if value <= 29:
        return 1.00
    if value <= 32:
        return 0.98
    return 0.95


def moderate_age_curve_factor(age: Any) -> float | None:
    if pd.isna(age):
        return None
    value = float(age)
    if value <= 20:
        return MODERATE_AGE_CURVE[20]
    if value >= 40:
        return MODERATE_AGE_CURVE[40]
    lower = math.floor(value)
    upper = math.ceil(value)
    if lower == upper:
        return MODERATE_AGE_CURVE[lower]
    fraction = value - lower
    return MODERATE_AGE_CURVE[lower] + fraction * (MODERATE_AGE_CURVE[upper] - MODERATE_AGE_CURVE[lower])


def age_curve_factor(age: Any, strength: float) -> float | None:
    moderate = moderate_age_curve_factor(age)
    if moderate is None:
        return None
    return 1 + strength * (moderate - 1)


def add_age_adjusted_prior_columns(rows: pd.DataFrame, variant: str, strength: float) -> None:
    current_factor = rows["firstAge"].map(lambda age: age_curve_factor(age, strength))
    for metric in ["AdjustedXhrPerPa", "BarrelsPerPa"]:
        numerator = pd.Series(0.0, index=rows.index)
        denominator = pd.Series(0.0, index=rows.index)
        for offset, weight in [(1, 5), (2, 4), (3, 3)]:
            source = to_numeric(rows.get(f"prior{offset}{metric}", pd.Series(index=rows.index, dtype="float64")))
            prior_age = rows["firstAge"] - offset
            prior_factor = prior_age.map(lambda age: age_curve_factor(age, strength))
            ratio = current_factor / prior_factor
            adjusted = source * ratio
            present = adjusted.notna()
            numerator = numerator + adjusted.fillna(0) * weight
            denominator = denominator + present.astype(float) * weight
        prior_column = f"firstPrior3{variant}{metric}"
        rows[prior_column] = numerator / denominator.where(denominator.gt(0))
        league_prior = rows.loc[rows[prior_column].notna(), prior_column].mean()
        if pd.isna(league_prior):
            league_prior = rows[f"first{metric}"].mean()
        rows[f"{prior_column}LeagueBaseline"] = league_prior
        filled = rows[prior_column].copy()
        fill_mask = rows["firstNoPriorBaselineFlag"].fillna(False) & current_factor.notna() & filled.isna()
        filled.loc[fill_mask] = league_prior
        rows[f"{prior_column}Filled"] = filled


def percentile_scores(values: pd.Series) -> pd.Series:
    ranks = values.rank(method="average", pct=True)

    def score(percentile: Any) -> float | None:
        if pd.isna(percentile):
            return None
        clipped = min(max(float(percentile), 0.01), 0.99)
        return 100 + NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped)

    return ranks.map(score)


def weighted_plus_score(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    score_maps = {key: percentile_scores(frame[key]) for key in weights}
    values: list[float | None] = []
    for index, _ in frame.iterrows():
        weighted = 0.0
        total = 0.0
        for key, weight in weights.items():
            score = score_maps[key].get(index)
            if score is None or pd.isna(score):
                continue
            weighted += float(score) * weight
            total += weight
        values.append(max(weighted / total, 0) if total else None)
    return pd.Series(values, index=frame.index)


def threat_input_frame(frame: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "barrelsPerPa": frame[f"{prefix}BarrelsPerPa"],
            "adjustedXhrPerPa": frame[f"{prefix}AdjustedXhrPerPa"],
            "hardHitAirBbePerPa": frame[f"{prefix}HardHitAirBbePerPa"],
            "expectedPowerQuality": frame[f"{prefix}ExpectedPowerQuality"],
            "lbiQuality": frame[f"{prefix}LbiProxy"] if prefix else frame["longballIndex"],
            "contactXisoProxy": frame[f"{prefix}ContactXisoProxy"],
            "contactXslg": frame[f"{prefix}ContactXslg"],
            "priorAdjustedXhrPerPa": frame.get(f"{prefix}PriorAdjustedXhrPerPa", pd.Series(index=frame.index, dtype="float64")),
            "priorBarrelsPerPa": frame.get(f"{prefix}PriorBarrelsPerPa", pd.Series(index=frame.index, dtype="float64")),
            "pulledHardHitAirBbePerPa": frame[f"{prefix}PulledHardHitAirBbePerPa"],
            "hardHitPulledAirBbePerPa": frame[f"{prefix}HardHitPulledAirBbePerPa"],
            "ev90": frame[f"{prefix}Ev90"],
            "pullAirEvInteraction": frame[f"{prefix}PullAirEvInteraction"],
        },
        index=frame.index,
    )


def add_threat_variants(frame: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    inputs = threat_input_frame(frame, prefix)
    for variant in THREAT_VARIANTS.values():
        frame[variant["scoreColumn"]] = weighted_plus_score(inputs, variant["weights"])
    return frame


def pitch_window_stats(pitches: pd.DataFrame, start: date, end: date, prefix: str) -> pd.DataFrame:
    window = pitches[(pitches["game_date"] >= start) & (pitches["game_date"] <= end)].copy()
    terminal = window[window["events"].notna() & window["events"].astype("string").str.strip().ne("")]
    if {"game_pk", "at_bat_number", "batter"}.issubset(terminal.columns):
        pa = (
            terminal.drop_duplicates(["game_pk", "at_bat_number", "batter"])
            .groupby("batter", as_index=False)
            .size()
            .rename(columns={"size": f"{prefix}Pa"})
        )
    else:
        pa = pd.DataFrame(columns=["batter", f"{prefix}Pa"])

    bbe = window[window["launch_speed"].notna() & window["launch_angle"].notna()].copy()
    if bbe.empty:
        return pa
    bbe["isHr"] = bbe["events"].astype("string").str.lower().eq("home_run")
    bbe["isBarrel"] = bbe["launch_speed_angle"].eq(6)
    bbe["isHardHit"] = bbe["launch_speed"].ge(95)
    bbe["isAir"] = bbe["launch_angle"].between(15, 45, inclusive="both")
    bbe["isHardHitAir"] = bbe["launch_speed"].ge(95) & bbe["isAir"]
    bbe["isPulled"] = False
    if "stand" in bbe.columns and "hc_x" in bbe.columns:
        stand = bbe["stand"].astype("string").str.upper()
        # Diagnostic approximation from Statcast batted-ball x coordinate:
        # right-handed pull air tends left-field side (lower hc_x), left-handed
        # pull air tends right-field side (higher hc_x).
        bbe["isPulled"] = (stand.eq("R") & bbe["hc_x"].lt(125)) | (stand.eq("L") & bbe["hc_x"].gt(125))
        bbe["sprayDirection"] = "center/oppo"
        bbe.loc[bbe["isPulled"], "sprayDirection"] = "pull"
    bbe["isPulledAir"] = bbe["isAir"] & bbe["isPulled"]
    bbe["isPulledHardHitAir"] = bbe["isHardHitAir"] & bbe["isPulled"]
    bbe["isHardHitPulledAir"] = bbe["isPulledHardHitAir"]
    bbe["isLoudPulledAir"] = bbe["isPulledAir"] & bbe["launch_speed"].ge(100)
    bbe["isCrushedPulledAir"] = bbe["isPulledAir"] & bbe["launch_speed"].ge(105)
    bbe["isPulledHr"] = bbe["isPulled"] & bbe["isHr"]
    bbe["barrelDistance"] = bbe["hit_distance_sc"].where(bbe["isBarrel"])
    bbe["pulledAirEv"] = bbe["launch_speed"].where(bbe["isPulledAir"])
    bbe["bbTypeNorm"] = bbe.get("bb_type", pd.Series(index=bbe.index, dtype="string")).astype("string").str.lower()
    for spec in PULL_AIR_JUICE_SPECS:
        if spec["mode"] == "barrel":
            match = bbe["isPulled"] & bbe["isBarrel"]
            score = match.astype(float)
        elif spec["mode"] == "threshold":
            match = (
                bbe["isPulled"]
                & bbe["launch_angle"].between(spec["low"], spec["high"], inclusive="both")
                & bbe["launch_speed"].ge(spec["threshold"])
            )
            score = match.astype(float)
        elif spec["mode"] == "bbtype":
            if spec["bbtype"] == "fly_ball_only":
                type_match = bbe["bbTypeNorm"].eq("fly_ball")
            elif spec["bbtype"] == "fly_line":
                type_match = bbe["bbTypeNorm"].isin(["fly_ball", "line_drive"])
            else:
                type_match = ~bbe["bbTypeNorm"].isin(["ground_ball", "popup", "pop_up"])
            match = bbe["isPulled"] & type_match & bbe["launch_speed"].ge(spec["threshold"])
            score = match.astype(float)
        else:
            pulled_air_window = bbe["isPulled"] & bbe["launch_angle"].between(15, 40, inclusive="both")
            ev_score = ((bbe["launch_speed"] - spec["evLow"]) / (spec["evHigh"] - spec["evLow"])).clip(0, 1)
            if spec["angleMode"] == "plateau":
                angle = bbe["launch_angle"]
                angle_score = pd.Series(1.0, index=bbe.index)
                angle_score = angle_score.where(angle.ge(24), ((angle - 15) / (24 - 15)).clip(0, 1))
                angle_score = angle_score.where(angle.le(33), ((40 - angle) / (40 - 33)).clip(0, 1))
            else:
                angle_score = (1 - ((bbe["launch_angle"] - 28).abs() / 13)).clip(0, 1)
            score = (ev_score * angle_score).where(pulled_air_window, 0).fillna(0)
            match = score.gt(0)
        match_column = f"isPaj{spec['columnSlug']}"
        hr_column = f"isPajHr{spec['columnSlug']}"
        score_column = f"pajScore{spec['columnSlug']}"
        bbe[match_column] = match
        bbe[hr_column] = bbe[match_column] & bbe["isHr"]
        bbe[score_column] = score
    bbe["estimatedBa"] = to_numeric(bbe.get("estimated_ba_using_speedangle", pd.Series(index=bbe.index, dtype="float64")))
    bbe["estimatedSlg"] = to_numeric(bbe.get("estimated_slg_using_speedangle", pd.Series(index=bbe.index, dtype="float64")))
    swing_window = window[window["bat_speed"].notna()].copy()
    if not swing_window.empty:
        swing_window["isFastSwing"] = swing_window["bat_speed"].ge(75)
        swing_window["isContact"] = swing_window["launch_speed"].notna()
        swing_window["isFastContact"] = swing_window["isFastSwing"] & swing_window["isContact"]
        swing_window["isFastLoudContact"] = swing_window["isFastContact"] & swing_window["launch_speed"].ge(95)
        swing_window["isFastBarrel"] = swing_window["isFastSwing"] & swing_window["launch_speed_angle"].eq(6)
        swing_stats = (
            swing_window.groupby("batter", as_index=False)
            .agg(
                **{
                    f"{prefix}TrackedSwings": ("bat_speed", "size"),
                    f"{prefix}FastSwings": ("isFastSwing", "sum"),
                    f"{prefix}TrackedContact": ("isContact", "sum"),
                    f"{prefix}FastContact": ("isFastContact", "sum"),
                    f"{prefix}FastLoudContact": ("isFastLoudContact", "sum"),
                    f"{prefix}FastBarrels": ("isFastBarrel", "sum"),
                    f"{prefix}AvgBatSpeed": ("bat_speed", "mean"),
                    f"{prefix}SwingLength": ("swing_length", "mean"),
                }
            )
        )
    else:
        swing_stats = pd.DataFrame(columns=["batter"])
    agg_kwargs: dict[str, tuple[str, str | Any]] = {
        "bbe": ("batter", "size"),
        "hr": ("isHr", "sum"),
        "barrels": ("isBarrel", "sum"),
        "hardHitBbe": ("isHardHit", "sum"),
        "hardHitAirBbe": ("isHardHitAir", "sum"),
        "pulledAirBbe": ("isPulledAir", "sum"),
        "pulledHardHitAirBbe": ("isPulledHardHitAir", "sum"),
        "hardHitPulledAirBbe": ("isHardHitPulledAir", "sum"),
        "loudPulledAirBbe": ("isLoudPulledAir", "sum"),
        "crushedPulledAirBbe": ("isCrushedPulledAir", "sum"),
        "pulledHr": ("isPulledHr", "sum"),
        "avgEvOnPulledAir": ("pulledAirEv", "mean"),
        "ev90OnPulledAir": ("pulledAirEv", lambda values: values.dropna().quantile(0.90) if values.notna().any() else pd.NA),
        "maxEvOnPulledAir": ("pulledAirEv", "max"),
        "ev90": ("launch_speed", lambda values: values.dropna().quantile(0.90) if values.notna().any() else pd.NA),
        "maxEv": ("launch_speed", "max"),
        "avgDistanceOnBarrels": ("barrelDistance", "mean"),
        "contactXba": ("estimatedBa", "mean"),
        "contactXslg": ("estimatedSlg", "mean"),
    }
    rename_columns = {
        "bbe": f"{prefix}Bbe",
        "hr": f"{prefix}Hr",
        "barrels": f"{prefix}Barrels",
        "hardHitBbe": f"{prefix}HardHitBbe",
        "hardHitAirBbe": f"{prefix}HardHitAirBbe",
        "pulledAirBbe": f"{prefix}PulledAirBbe",
        "pulledHardHitAirBbe": f"{prefix}PulledHardHitAirBbe",
        "hardHitPulledAirBbe": f"{prefix}HardHitPulledAirBbe",
        "loudPulledAirBbe": f"{prefix}LoudPulledAirBbe",
        "crushedPulledAirBbe": f"{prefix}CrushedPulledAirBbe",
        "pulledHr": f"{prefix}PulledHr",
        "avgEvOnPulledAir": f"{prefix}AvgEvOnPulledAir",
        "ev90OnPulledAir": f"{prefix}Ev90OnPulledAir",
        "maxEvOnPulledAir": f"{prefix}MaxEvOnPulledAir",
        "ev90": f"{prefix}Ev90",
        "maxEv": f"{prefix}MaxEv",
        "avgDistanceOnBarrels": f"{prefix}AvgDistanceOnBarrels",
        "contactXba": f"{prefix}ContactXba",
        "contactXslg": f"{prefix}ContactXslg",
    }
    for spec in PULL_AIR_JUICE_SPECS:
        raw_count = f"paj{spec['columnSlug']}Count"
        raw_score = f"paj{spec['columnSlug']}Score"
        raw_hr = f"paj{spec['columnSlug']}Hr"
        agg_kwargs[raw_count] = (f"isPaj{spec['columnSlug']}", "sum")
        agg_kwargs[raw_score] = (f"pajScore{spec['columnSlug']}", "sum")
        agg_kwargs[raw_hr] = (f"isPajHr{spec['columnSlug']}", "sum")
        rename_columns[raw_count] = f"{prefix}Paj{spec['columnSlug']}Count"
        rename_columns[raw_score] = f"{prefix}Paj{spec['columnSlug']}Score"
        rename_columns[raw_hr] = f"{prefix}Paj{spec['columnSlug']}Hr"
    stats = (
        bbe.groupby("batter", as_index=False)
        .agg(**agg_kwargs)
        .rename(columns=rename_columns)
    )
    merged = pa.merge(stats, on="batter", how="outer").fillna(0)
    merged = merged.merge(swing_stats, on="batter", how="left")
    required_columns = [
        f"{prefix}Bbe",
        f"{prefix}Hr",
        f"{prefix}Barrels",
        f"{prefix}HardHitBbe",
        f"{prefix}HardHitAirBbe",
        f"{prefix}PulledAirBbe",
        f"{prefix}PulledHardHitAirBbe",
        f"{prefix}HardHitPulledAirBbe",
        f"{prefix}LoudPulledAirBbe",
        f"{prefix}CrushedPulledAirBbe",
        f"{prefix}PulledHr",
        f"{prefix}AvgEvOnPulledAir",
        f"{prefix}Ev90OnPulledAir",
        f"{prefix}MaxEvOnPulledAir",
        f"{prefix}Ev90",
        f"{prefix}MaxEv",
        f"{prefix}AvgDistanceOnBarrels",
        f"{prefix}ContactXba",
        f"{prefix}ContactXslg",
        f"{prefix}TrackedSwings",
        f"{prefix}FastSwings",
        f"{prefix}TrackedContact",
        f"{prefix}FastContact",
        f"{prefix}FastLoudContact",
        f"{prefix}FastBarrels",
        f"{prefix}AvgBatSpeed",
        f"{prefix}SwingLength",
    ]
    for spec in PULL_AIR_JUICE_SPECS:
        required_columns.extend(
            [
                f"{prefix}Paj{spec['columnSlug']}Count",
                f"{prefix}Paj{spec['columnSlug']}Score",
                f"{prefix}Paj{spec['columnSlug']}Hr",
            ]
        )
    for column in required_columns:
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged


def adjusted_xhr(details: pd.DataFrame, start: date, end: date, prefix: str = "") -> pd.DataFrame:
    window = details[(details["game_date"] >= start) & (details["game_date"] <= end)].copy()
    if window.empty:
        return pd.DataFrame(columns=["batter", f"{prefix}AdjustedXhr"])
    # Local Home Run Tracker detail cache does not expose a direct xHR column;
    # ct / 30 is the same diagnostic proxy used by the historical threat tests.
    window["detailXhr"] = window["ct"].fillna(0) / 30
    return (
        window.groupby("batter_id", as_index=False)
        .agg(**{f"{prefix}AdjustedXhr": ("detailXhr", "sum")})
        .rename(columns={"batter_id": "batter"})
    )


def add_rate_columns(frame: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    pa = frame[f"{prefix}Pa"].where(frame[f"{prefix}Pa"].gt(0))
    bbe = frame[f"{prefix}Bbe"].where(frame[f"{prefix}Bbe"].gt(0))
    frame[f"{prefix}AdjustedXhrPerPa"] = frame[f"{prefix}AdjustedXhr"] / pa
    aggregate_column = f"{prefix}HrtAggregateAdjustedXhr"
    if aggregate_column in frame.columns:
        frame[f"{prefix}HrtAggregateAdjustedXhrPerPa"] = frame[aggregate_column] / pa
    else:
        frame[f"{prefix}HrtAggregateAdjustedXhrPerPa"] = pd.NA
    frame[f"{prefix}BarrelsPerPa"] = frame[f"{prefix}Barrels"] / pa
    frame[f"{prefix}HardHitAirBbePerPa"] = frame[f"{prefix}HardHitAirBbe"] / pa
    frame[f"{prefix}PulledAirBbePerPa"] = frame[f"{prefix}PulledAirBbe"] / pa
    frame[f"{prefix}PulledHardHitAirBbePerPa"] = frame[f"{prefix}PulledHardHitAirBbe"] / pa
    frame[f"{prefix}HardHitPulledAirBbePerPa"] = frame[f"{prefix}HardHitPulledAirBbe"] / pa
    frame[f"{prefix}LoudPulledAirBbePerPa"] = frame[f"{prefix}LoudPulledAirBbe"] / pa
    frame[f"{prefix}CrushedPulledAirBbePerPa"] = frame[f"{prefix}CrushedPulledAirBbe"] / pa
    frame[f"{prefix}ActualHrPerPa"] = frame[f"{prefix}Hr"] / pa
    frame[f"{prefix}TrackedSwings"] = to_numeric(frame.get(f"{prefix}TrackedSwings", pd.Series(index=frame.index))).fillna(0)
    tracked_swings = frame[f"{prefix}TrackedSwings"].where(frame[f"{prefix}TrackedSwings"].gt(0))
    tracked_contact = to_numeric(frame.get(f"{prefix}TrackedContact", pd.Series(index=frame.index))).fillna(0)
    tracked_contact_denominator = tracked_contact.where(tracked_contact.gt(0))
    for column in [
        "FastSwings",
        "TrackedContact",
        "FastContact",
        "FastLoudContact",
        "FastBarrels",
        "AvgBatSpeed",
        "SwingLength",
    ]:
        frame[f"{prefix}{column}"] = to_numeric(frame.get(f"{prefix}{column}", pd.Series(index=frame.index))).fillna(0)
    frame[f"{prefix}FastSwingPerPa"] = frame[f"{prefix}FastSwings"] / pa
    frame[f"{prefix}FastSwingRate"] = frame[f"{prefix}FastSwings"] / tracked_swings
    frame[f"{prefix}FastContactPerPa"] = frame[f"{prefix}FastContact"] / pa
    frame[f"{prefix}FastContactRate"] = frame[f"{prefix}FastContact"] / tracked_contact_denominator
    frame[f"{prefix}FastLoudContactPerPa"] = frame[f"{prefix}FastLoudContact"] / pa
    frame[f"{prefix}FastBarrelsPerPa"] = frame[f"{prefix}FastBarrels"] / pa
    frame[f"{prefix}XhrPerBbe"] = frame[f"{prefix}AdjustedXhr"] / bbe
    frame[f"{prefix}BarrelRate"] = frame[f"{prefix}Barrels"] / bbe
    frame[f"{prefix}PulledAirRate"] = frame[f"{prefix}PulledAirBbe"] / bbe
    frame[f"{prefix}HardHitRate"] = frame[f"{prefix}HardHitBbe"] / bbe
    frame[f"{prefix}ExpectedPowerQuality"] = frame[f"{prefix}AvgDistanceOnBarrels"]
    frame[f"{prefix}ContactXba"] = to_numeric(frame.get(f"{prefix}ContactXba", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}ContactXslg"] = to_numeric(frame.get(f"{prefix}ContactXslg", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}ContactXisoProxy"] = frame[f"{prefix}ContactXslg"] - frame[f"{prefix}ContactXba"]
    frame[f"{prefix}Ev90"] = to_numeric(frame.get(f"{prefix}Ev90", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}MaxEv"] = to_numeric(frame.get(f"{prefix}MaxEv", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}AvgEvOnPulledAir"] = to_numeric(
        frame.get(f"{prefix}AvgEvOnPulledAir", pd.Series(index=frame.index, dtype="float64"))
    )
    frame[f"{prefix}Ev90OnPulledAir"] = to_numeric(
        frame.get(f"{prefix}Ev90OnPulledAir", pd.Series(index=frame.index, dtype="float64"))
    )
    frame[f"{prefix}MaxEvOnPulledAir"] = to_numeric(
        frame.get(f"{prefix}MaxEvOnPulledAir", pd.Series(index=frame.index, dtype="float64"))
    )
    frame[f"{prefix}PullAirEvInteraction"] = frame[f"{prefix}HardHitPulledAirBbePerPa"] * (frame[f"{prefix}Ev90"] / 100)
    frame[f"{prefix}PulledAirEvQuality"] = frame[f"{prefix}PulledAirBbePerPa"] * (frame[f"{prefix}Ev90OnPulledAir"] / 100)
    frame[f"{prefix}PulledAirLoudQuality"] = frame[f"{prefix}HardHitPulledAirBbePerPa"] * (
        frame[f"{prefix}Ev90OnPulledAir"] / 100
    )
    for spec in PULL_AIR_JUICE_SPECS:
        count_col = f"{prefix}Paj{spec['columnSlug']}Count"
        score_col = f"{prefix}Paj{spec['columnSlug']}Score"
        hr_col = f"{prefix}Paj{spec['columnSlug']}Hr"
        if count_col not in frame.columns:
            frame[count_col] = 0
        if score_col not in frame.columns:
            frame[score_col] = frame[count_col]
        if hr_col not in frame.columns:
            frame[hr_col] = 0
        frame[count_col] = to_numeric(frame[count_col]).fillna(0)
        frame[score_col] = to_numeric(frame[score_col]).fillna(0)
        frame[hr_col] = to_numeric(frame[hr_col]).fillna(0)
        frame[f"{prefix}Paj{spec['columnSlug']}PerPa"] = frame[score_col] / pa
        frame[f"{prefix}Paj{spec['columnSlug']}Per100Pa"] = frame[f"{prefix}Paj{spec['columnSlug']}PerPa"] * 100
    frame[f"{prefix}RawThreatC"] = 0.75 * frame[f"{prefix}AdjustedXhrPerPa"] + 0.25 * frame[f"{prefix}BarrelsPerPa"]
    frame[f"{prefix}ContactXisoProxy"] = to_numeric(frame[f"{prefix}ContactXisoProxy"])
    return frame


def scale_to_xhr_rate(frame: pd.DataFrame, source_column: str, target_column: str, xhr_column: str) -> None:
    """Scale non-rate features onto the checkpoint xHR/PA magnitude for blends."""
    source = to_numeric(frame[source_column])
    xhr = to_numeric(frame[xhr_column])
    source_mean = source.replace([float("inf"), -float("inf")], pd.NA).dropna().mean()
    xhr_mean = xhr.replace([float("inf"), -float("inf")], pd.NA).dropna().mean()
    if pd.isna(source_mean) or pd.isna(xhr_mean) or source_mean == 0:
        frame[target_column] = pd.NA
        return
    frame[target_column] = source / source_mean * xhr_mean


def calculate_full_season(
    players: pd.DataFrame,
    pitches: pd.DataFrame,
    details: pd.DataFrame,
    season: int,
    min_pa: int,
    min_bbe: int,
) -> pd.DataFrame:
    season_start = min(pitches["game_date"])
    season_end = max(pitches["game_date"])
    stats = pitch_window_stats(pitches, season_start, season_end, "")
    xhr = adjusted_xhr(details, season_start, season_end, "")
    frame = players.merge(stats, on="batter", how="left").merge(xhr, on="batter", how="left")
    frame = frame.merge(aggregate_xhr_frame(players, ""), on="batter", how="left")
    for column in [
        "Pa",
        "Bbe",
        "Hr",
        "Barrels",
        "HardHitBbe",
        "HardHitAirBbe",
        "PulledAirBbe",
        "PulledHardHitAirBbe",
        "HardHitPulledAirBbe",
        "LoudPulledAirBbe",
        "CrushedPulledAirBbe",
        "Ev90",
        "MaxEv",
        "AvgEvOnPulledAir",
        "Ev90OnPulledAir",
        "MaxEvOnPulledAir",
        "AdjustedXhr",
        "HrtAggregateAdjustedXhr",
    ]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = to_numeric(frame[column]).fillna(0)
    frame = add_rate_columns(frame, "")

    qualified = frame[frame["Pa"].ge(min_pa) & frame["Bbe"].ge(min_bbe)].copy()
    qualified = add_threat_variants(qualified, "")
    qualified["longballThreat"] = qualified["threat_c_plus_scaled_75_xhr_25_barrel"]
    qualified["lbiRank"] = qualified["longballIndex"].rank(method="first", ascending=False).astype(int)
    for variant in THREAT_VARIANTS.values():
        qualified[variant["rankColumn"]] = qualified[variant["scoreColumn"]].rank(method="first", ascending=False).astype(int)
    qualified = qualified.sort_values(["threat_c_plus_scaled_75_xhr_25_barrel", "AdjustedXhrPerPa"], ascending=[False, False])
    qualified["threatRank"] = qualified["threat_c_plus_rank"]
    qualified["rankDeltaThreatMinusLbi"] = qualified["threat_c_plus_rank"] - qualified["lbiRank"]

    league_xhr_per_barrel = qualified["AdjustedXhr"].sum() / qualified["Barrels"].sum() if qualified["Barrels"].sum() else 0
    league_xhr_per_hard_air = (
        qualified["AdjustedXhr"].sum() / qualified["HardHitAirBbe"].sum() if qualified["HardHitAirBbe"].sum() else 0
    )
    league_xhr_per_pa = qualified["AdjustedXhr"].sum() / qualified["Pa"].sum() if qualified["Pa"].sum() else 0
    power_score = percentile_scores(qualified["ExpectedPowerQuality"]).fillna(100) / 100
    projected_rate = (
        0.40 * qualified["BarrelsPerPa"].fillna(0) * league_xhr_per_barrel
        + 0.35 * qualified["AdjustedXhrPerPa"].fillna(0)
        + 0.15 * qualified["HardHitAirBbePerPa"].fillna(0) * league_xhr_per_hard_air
        + 0.10 * league_xhr_per_pa * power_score
    )
    qualified["projectedHrPer600"] = (projected_rate * 600).round(1)
    qualified["season"] = season
    return qualified


def lbi_proxy(frame: pd.DataFrame) -> pd.Series:
    scratch = pd.DataFrame(
        {
            "xhrPerBbe": frame["firstXhrPerBbe"],
            "barrelRate": frame["firstBarrelRate"],
            "avgDistanceOnBarrels": frame["firstAvgDistanceOnBarrels"],
            "hardHitRate": frame["firstHardHitRate"],
        }
    )
    return weighted_plus_score(scratch, LBI_PROXY_WEIGHTS)


def prepare_checkpoint(
    pitches: pd.DataFrame,
    details: pd.DataFrame,
    names: dict[int, str],
    players: pd.DataFrame,
    prior_rates: pd.DataFrame,
    multi_prior_rates: pd.DataFrame,
    age_lookup: dict[int, str],
    season_start: date,
    checkpoint: date,
    next_weeks: int,
    min_first_pa: int,
    min_future_pa: int,
    min_first_bbe: int,
) -> BacktestCheckpoint:
    period_start = checkpoint + timedelta(days=1)
    period_end = checkpoint + timedelta(weeks=next_weeks)
    rest_period_end = max(pitches["game_date"])
    first = pitch_window_stats(pitches, season_start, checkpoint, "first")
    future = pitch_window_stats(pitches, period_start, period_end, "future")
    rest_future = pitch_window_stats(pitches, period_start, rest_period_end, "restFuture")
    xhr = adjusted_xhr(details, season_start, checkpoint, "first")
    rows = first.merge(xhr, on="batter", how="left").merge(
        future[["batter", "futurePa", "futureBbe", "futureHr"]],
        on="batter",
        how="left",
    )
    rows = rows.merge(
        rest_future[["batter", "restFuturePa", "restFutureBbe", "restFutureHr"]],
        on="batter",
        how="left",
    )
    rows = rows.merge(aggregate_xhr_frame(players, "first"), on="batter", how="left")
    if not prior_rates.empty:
        rows = rows.merge(prior_rates, on="batter", how="left")
    else:
        rows["priorAdjustedXhrPerPa"] = pd.NA
        rows["priorBarrelsPerPa"] = pd.NA
    if not multi_prior_rates.empty:
        rows = rows.merge(multi_prior_rates, on="batter", how="left")
    else:
        for column in [
            "prior1AdjustedXhrPerPa",
            "prior1BarrelsPerPa",
            "prior2AdjustedXhrPerPa",
            "prior2BarrelsPerPa",
            "prior3AdjustedXhrPerPa",
            "prior3BarrelsPerPa",
            "priorSeasonCount",
        ]:
            rows[column] = pd.NA
    for column in [
        "firstPa",
        "firstBbe",
        "firstHr",
        "firstBarrels",
        "firstHardHitBbe",
        "firstHardHitAirBbe",
        "firstPulledAirBbe",
        "firstPulledHardHitAirBbe",
        "firstHardHitPulledAirBbe",
        "firstLoudPulledAirBbe",
        "firstCrushedPulledAirBbe",
        "firstPulledHr",
        "firstEv90",
        "firstMaxEv",
        "firstAvgEvOnPulledAir",
        "firstEv90OnPulledAir",
        "firstMaxEvOnPulledAir",
        "firstTrackedSwings",
        "firstFastSwings",
        "firstTrackedContact",
        "firstFastContact",
        "firstFastLoudContact",
        "firstFastBarrels",
        "firstAvgBatSpeed",
        "firstSwingLength",
        "firstAdjustedXhr",
        "firstHrtAggregateAdjustedXhr",
        "futurePa",
        "futureBbe",
        "futureHr",
        "restFuturePa",
        "restFutureBbe",
        "restFutureHr",
    ]:
        if column not in rows.columns:
            rows[column] = 0
        rows[column] = to_numeric(rows[column]).fillna(0)
    rows = add_rate_columns(rows, "first")
    rows["firstPriorAdjustedXhrPerPa"] = to_numeric(rows["priorAdjustedXhrPerPa"])
    rows["firstPriorBarrelsPerPa"] = to_numeric(rows["priorBarrelsPerPa"])
    for column in [
        "prior1AdjustedXhrPerPa",
        "prior1BarrelsPerPa",
        "prior2AdjustedXhrPerPa",
        "prior2BarrelsPerPa",
        "prior3AdjustedXhrPerPa",
        "prior3BarrelsPerPa",
        "priorSeasonCount",
    ]:
        rows[f"first{column[0].upper()}{column[1:]}"] = to_numeric(rows[column])
    rows["firstAge"] = to_numeric(rows["batter"].map(lambda value: age_at_checkpoint(age_lookup.get(int(value)), checkpoint)))
    rows["firstAgePowerFactor"] = rows["firstAge"].map(age_power_factor)
    rows["firstAgeBucket"] = pd.cut(
        rows["firstAge"],
        bins=[0, 23, 26, 29, 32, 99],
        labels=["<=23", "24-26", "27-29", "30-32", "33+"],
        include_lowest=True,
    )
    rows["firstNoPriorBaselineFlag"] = rows["firstPriorSeasonCount"].fillna(0).eq(0)
    for variant, strength in AGE_CURVE_STRENGTHS.items():
        add_age_adjusted_prior_columns(rows, variant, strength)
    rows["firstXhrTrajectoryVsPrior3"] = rows["firstAdjustedXhrPerPa"] - rows["firstPrior3AdjustedXhrPerPa"]
    rows["firstBarrelTrajectoryVsPrior3"] = rows["firstBarrelsPerPa"] - rows["firstPrior3BarrelsPerPa"]
    scale_to_xhr_rate(rows, "firstContactXisoProxy", "firstContactXisoProxyRateScale", "firstAdjustedXhrPerPa")
    scale_to_xhr_rate(rows, "firstEv90", "firstEv90RateScale", "firstAdjustedXhrPerPa")
    scale_to_xhr_rate(rows, "firstPullAirEvInteraction", "firstPullAirEvInteractionRateScale", "firstAdjustedXhrPerPa")
    league_pull_air_ev90 = rows.loc[rows["firstPulledAirBbe"].gt(0), "firstEv90OnPulledAir"].dropna().mean()
    for m_pull_air_ev in [5, 10, 15, 20]:
        weight = rows["firstPulledAirBbe"] / (rows["firstPulledAirBbe"] + m_pull_air_ev)
        rows[f"firstEv90OnPulledAirShrunk{m_pull_air_ev}"] = (
            weight * rows["firstEv90OnPulledAir"] + (1 - weight) * league_pull_air_ev90
        )
        rows[f"firstPulledAirEvQualityShrunk{m_pull_air_ev}"] = rows["firstPulledAirBbePerPa"] * (
            rows[f"firstEv90OnPulledAirShrunk{m_pull_air_ev}"] / 100
        )
        rows[f"firstPulledAirLoudQualityShrunk{m_pull_air_ev}"] = rows["firstHardHitPulledAirBbePerPa"] * (
            rows[f"firstEv90OnPulledAirShrunk{m_pull_air_ev}"] / 100
        )
        scale_to_xhr_rate(
            rows,
            f"firstEv90OnPulledAirShrunk{m_pull_air_ev}",
            f"firstEv90OnPulledAirShrunk{m_pull_air_ev}RateScale",
            "firstAdjustedXhrPerPa",
        )
        scale_to_xhr_rate(
            rows,
            f"firstPulledAirEvQualityShrunk{m_pull_air_ev}",
            f"firstPulledAirEvQualityShrunk{m_pull_air_ev}RateScale",
            "firstAdjustedXhrPerPa",
        )
        scale_to_xhr_rate(
            rows,
            f"firstPulledAirLoudQualityShrunk{m_pull_air_ev}",
            f"firstPulledAirLoudQualityShrunk{m_pull_air_ev}RateScale",
            "firstAdjustedXhrPerPa",
        )
    for source in [
        "firstEv90OnPulledAir",
        "firstMaxEvOnPulledAir",
        "firstAvgEvOnPulledAir",
        "firstPulledAirEvQuality",
        "firstPulledAirLoudQuality",
        "firstHardHitPulledAirBbePerPa",
        "firstLoudPulledAirBbePerPa",
        "firstCrushedPulledAirBbePerPa",
        "firstFastSwingPerPa",
        "firstFastSwingRate",
        "firstFastContactPerPa",
        "firstFastContactRate",
        "firstFastLoudContactPerPa",
        "firstFastBarrelsPerPa",
        "firstAvgBatSpeed",
    ]:
        scale_to_xhr_rate(rows, source, f"{source}RateScale", "firstAdjustedXhrPerPa")
    for spec in PULL_AIR_JUICE_SPECS:
        source = f"firstPaj{spec['columnSlug']}PerPa"
        scale_to_xhr_rate(rows, source, f"{source}RateScale", "firstAdjustedXhrPerPa")
    rows["firstPriorStabilized"] = (
        0.55 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
    )
    rows["firstPriorStabilizedContactXiso"] = (
        0.50 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
        + 0.05 * rows["firstContactXisoProxyRateScale"]
    )
    rows["firstPriorStabilizedEv90"] = (
        0.50 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
        + 0.05 * rows["firstEv90RateScale"]
    )
    rows["firstPriorStabilizedPullAirEvInteraction"] = (
        0.50 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
        + 0.05 * rows["firstPullAirEvInteractionRateScale"]
    )
    rows["firstPriorStabilizedContactXisoEv90"] = (
        0.475 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
        + 0.05 * rows["firstContactXisoProxyRateScale"]
        + 0.025 * rows["firstEv90RateScale"]
    )
    rows["firstDynamicBaseM150X150B060"] = (
        0.60
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstAdjustedXhrPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPriorAdjustedXhrPerPa"]
        )
        + 0.40
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstBarrelsPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPriorBarrelsPerPa"]
        )
    )
    rows["firstDynamicAgeAdjusted"] = rows["firstDynamicBaseM150X150B060"] * rows["firstAgePowerFactor"]
    rows["firstDynamicPrior2"] = (
        0.60
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstAdjustedXhrPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPrior2AdjustedXhrPerPa"]
        )
        + 0.40
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstBarrelsPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPrior2BarrelsPerPa"]
        )
    )
    rows["firstDynamicPrior3"] = (
        0.60
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstAdjustedXhrPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPrior3AdjustedXhrPerPa"]
        )
        + 0.40
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstBarrelsPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows["firstPrior3BarrelsPerPa"]
        )
    )
    rows["firstDynamicPrior3AgeAdjusted"] = rows["firstDynamicPrior3"] * rows["firstAgePowerFactor"]
    current_raw_threat = 0.60 * rows["firstAdjustedXhrPerPa"] + 0.40 * rows["firstBarrelsPerPa"]
    no_prior = rows["firstNoPriorBaselineFlag"].fillna(False)
    league_prior_xhr = rows.loc[rows["firstPrior3AdjustedXhrPerPa"].notna(), "firstPrior3AdjustedXhrPerPa"].mean()
    league_prior_barrel = rows.loc[rows["firstPrior3BarrelsPerPa"].notna(), "firstPrior3BarrelsPerPa"].mean()
    if pd.isna(league_prior_xhr):
        league_prior_xhr = rows["firstAdjustedXhrPerPa"].mean()
    if pd.isna(league_prior_barrel):
        league_prior_barrel = rows["firstBarrelsPerPa"].mean()
    league_prior_blend = 0.60 * league_prior_xhr + 0.40 * league_prior_barrel
    prior3_xhr_league_filled = rows["firstPrior3AdjustedXhrPerPa"].copy()
    prior3_barrel_league_filled = rows["firstPrior3BarrelsPerPa"].copy()
    prior3_xhr_league_filled.loc[no_prior] = league_prior_xhr
    prior3_barrel_league_filled.loc[no_prior] = league_prior_barrel
    rows["firstDynamicPrior3NoPriorLeagueFallback"] = (
        0.60
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstAdjustedXhrPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * prior3_xhr_league_filled
        )
        + 0.40
        * (
            rows["firstPa"]
            / (rows["firstPa"] + 150)
            * rows["firstBarrelsPerPa"]
            + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * prior3_barrel_league_filled
        )
    ) * rows["firstAgePowerFactor"]
    rows["firstDynamicPrior3NoPriorCurrentOnlyFallback"] = rows["firstDynamicPrior3AgeAdjusted"].copy()
    rows.loc[no_prior, "firstDynamicPrior3NoPriorCurrentOnlyFallback"] = current_raw_threat.loc[no_prior] * rows.loc[
        no_prior, "firstAgePowerFactor"
    ]
    rookie_current_weight = rows["firstPa"] / (rows["firstPa"] + 150)
    rookie_hybrid = (rookie_current_weight * current_raw_threat) + ((1 - rookie_current_weight) * league_prior_blend)
    rows["firstDynamicPrior3NoPriorHybridFallback"] = rows["firstDynamicPrior3AgeAdjusted"].copy()
    rows.loc[no_prior, "firstDynamicPrior3NoPriorHybridFallback"] = rookie_hybrid.loc[no_prior] * rows.loc[
        no_prior, "firstAgePowerFactor"
    ]
    for variant, output_column in [
        ("Age1Moderate", "firstDynamicPrior3AgeCurveModerate"),
        ("Age2Conservative", "firstDynamicPrior3AgeCurveConservative"),
        ("Age3Aggressive", "firstDynamicPrior3AgeCurveAggressive"),
    ]:
        rows[output_column] = (
            0.60
            * (
                rows["firstPa"]
                / (rows["firstPa"] + 150)
                * rows["firstAdjustedXhrPerPa"]
                + (1 - rows["firstPa"] / (rows["firstPa"] + 150))
                * rows[f"firstPrior3{variant}AdjustedXhrPerPaFilled"]
            )
            + 0.40
            * (
                rows["firstPa"]
                / (rows["firstPa"] + 150)
                * rows["firstBarrelsPerPa"]
                + (1 - rows["firstPa"] / (rows["firstPa"] + 150)) * rows[f"firstPrior3{variant}BarrelsPerPaFilled"]
            )
        )
    rows["firstDynamicPrior3Trajectory"] = rows["firstDynamicPrior3"] + 0.025 * rows["firstXhrTrajectoryVsPrior3"] + 0.025 * rows[
        "firstBarrelTrajectoryVsPrior3"
    ]
    under23 = rows["firstAge"].le(23)
    under24 = rows["firstAge"].le(24)
    under23_low_prior = under23 & rows["firstPriorSeasonCount"].fillna(0).lt(2)
    rows["firstYoungAUnder23Age2"] = rows["firstDynamicPrior3AgeAdjusted"].where(~under23, rows["firstDynamicPrior3AgeCurveConservative"])
    rows["firstYoungBUnder23Age1"] = rows["firstDynamicPrior3AgeAdjusted"].where(~under23, rows["firstDynamicPrior3AgeCurveModerate"])
    rows["firstYoungCUnder23Boost2"] = rows["firstDynamicPrior3AgeAdjusted"].where(
        ~under23, rows["firstDynamicPrior3AgeAdjusted"] * 1.02
    )
    rows["firstYoungCUnder23Boost3"] = rows["firstDynamicPrior3AgeAdjusted"].where(
        ~under23, rows["firstDynamicPrior3AgeAdjusted"] * 1.03
    )
    rows["firstYoungCUnder23Boost4"] = rows["firstDynamicPrior3AgeAdjusted"].where(
        ~under23, rows["firstDynamicPrior3AgeAdjusted"] * 1.04
    )
    rows["firstYoungDUnder24Age2"] = rows["firstDynamicPrior3AgeAdjusted"].where(~under24, rows["firstDynamicPrior3AgeCurveConservative"])
    rows["firstYoungEUnder23LowPriorAge2"] = rows["firstDynamicPrior3AgeAdjusted"].where(
        ~under23_low_prior, rows["firstDynamicPrior3AgeCurveConservative"]
    )
    rows["firstYoungEWithLeagueFallback"] = rows["firstDynamicPrior3NoPriorLeagueFallback"].where(
        ~under23_low_prior, rows["firstDynamicPrior3AgeCurveConservative"]
    )
    rows["firstPa1DynamicPlusEv90OnPulledAir"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstEv90OnPulledAirRateScale"
    ]
    rows["firstPa2DynamicPlusShrunkEv90OnPulledAir"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstEv90OnPulledAirShrunk10RateScale"
    ]
    rows["firstPa3DynamicPlusMaxEvOnPulledAir"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstMaxEvOnPulledAirRateScale"
    ]
    rows["firstPa4DynamicPlusAvgEvOnPulledAir"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstAvgEvOnPulledAirRateScale"
    ]
    rows["firstPa5DynamicPlusPulledAirEvQuality"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstPulledAirEvQualityRateScale"
    ]
    rows["firstPa6DynamicPlusPulledAirLoudQuality"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstPulledAirLoudQualityRateScale"
    ]
    rows["firstPa7DynamicPlusHardHitPulledAirBbePerPa"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstHardHitPulledAirBbePerPaRateScale"
    ]
    rows["firstPa8DynamicPlusLoudPulledAirBbePerPa"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstLoudPulledAirBbePerPaRateScale"
    ]
    rows["firstPa9DynamicPlusCrushedPulledAirBbePerPa"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[
        "firstCrushedPulledAirBbePerPaRateScale"
    ]
    for spec in PULL_AIR_JUICE_SPECS:
        source = f"firstPaj{spec['columnSlug']}PerPa"
        scaled = f"{source}RateScale"
        rows[f"{source}DynamicSeasoning"] = 0.95 * rows["firstDynamicBaseM150X150B060"] + 0.05 * rows[scaled]
        rows[f"{source}ModelESeasoning"] = 0.95 * rows["firstDynamicPrior3NoPriorLeagueFallback"] + 0.05 * rows[scaled]
    for source in [
        "firstFastSwingPerPa",
        "firstFastSwingRate",
        "firstFastContactPerPa",
        "firstFastContactRate",
        "firstFastLoudContactPerPa",
        "firstFastBarrelsPerPa",
        "firstAvgBatSpeed",
    ]:
        rows[f"{source}ModelESeasoning"] = 0.95 * rows["firstDynamicPrior3NoPriorLeagueFallback"] + 0.05 * rows[
            f"{source}RateScale"
        ]
    rows["futureHrPerPa"] = rows["futureHr"] / rows["futurePa"].where(rows["futurePa"].gt(0))
    rows["futureHrPerBbe"] = rows["futureHr"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
    rows["restFutureHrPerPa"] = rows["restFutureHr"] / rows["restFuturePa"].where(rows["restFuturePa"].gt(0))
    rows["restFutureHrPerBbe"] = rows["restFutureHr"] / rows["restFutureBbe"].where(rows["restFutureBbe"].gt(0))
    rows["firstLbiProxy"] = lbi_proxy(rows)
    rows["firstExpectedPowerQuality"] = rows["firstAvgDistanceOnBarrels"]
    rows["player"] = rows["batter"].map(lambda value: names.get(int(value), f"MLBAM {int(value)}"))

    qualified = rows[
        rows["firstPa"].ge(min_first_pa)
        & rows["futurePa"].ge(min_future_pa)
        & rows["firstBbe"].ge(min_first_bbe)
    ].copy()
    qualified = add_threat_variants(qualified, "first")
    qualified["longballThreat"] = qualified["threat_c_plus_scaled_75_xhr_25_barrel"]
    return BacktestCheckpoint(checkpoint=checkpoint, period_end=period_end, rows=qualified)


def fmt_pct(value: Any, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:.{decimals}f}%"


def print_top_threat(rows: pd.DataFrame, limit: int, variant_key: str) -> None:
    variant = THREAT_VARIANTS[variant_key]
    score_column = variant["scoreColumn"]
    rank_column = variant["rankColumn"]
    sorted_rows = rows.sort_values([score_column, "AdjustedXhrPerPa"], ascending=[False, False])
    print(f"\n=== Top {limit} Longball Threat {variant_key} ({variant['label']}) ===")
    for _, row in sorted_rows.head(limit).iterrows():
        print(
            f"{int(row[rank_column]):2}. {row['player']} ({row.get('team', '---')}) "
            f"LBT {row[score_column]:.1f} | HR/600 {row['projectedHrPer600']:.1f} | "
            f"PA {int(row['Pa'])} | HR {int(row['hr'])} | "
            f"Brl/PA {fmt_pct(row['BarrelsPerPa'])} | xHR/PA {fmt_pct(row['AdjustedXhrPerPa'])} | "
            f"HH Pull Air/PA {fmt_pct(row['HardHitPulledAirBbePerPa'])} | "
            f"EV90 {row['Ev90']:.1f} | PullEV {row['PullAirEvInteraction']:.4f} | LBI {row['longballIndex']:.1f}"
        )


def print_sanity(rows: pd.DataFrame) -> None:
    print("\n=== Sanity Player Outputs ===")
    by_name = {normalize_name(row["player"]): row for _, row in rows.iterrows()}
    seen: set[str] = set()
    for name in SANITY_PLAYERS:
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        row = by_name.get(key)
        if row is None:
            print(f"{name}: not qualified or not present")
            continue
        print(
            f"{row['player']} ({row.get('team', '---')}) | PA {int(row['Pa'])} | BBE {int(row['Bbe'])} | HR {int(row['hr'])} | "
            f"rawC {row['RawThreatC']:.4f} | plusC {row['threat_c_plus_scaled_75_xhr_25_barrel']:.1f} | "
            f"HR/600 {row['projectedHrPer600']:.1f} | LBI {row['longballIndex']:.1f}"
        )
        print(
            f"  Brl/PA {fmt_pct(row['BarrelsPerPa'])} | xHR/PA {fmt_pct(row['AdjustedXhrPerPa'])} | "
            f"HH Air/PA {fmt_pct(row['HardHitAirBbePerPa'])} | HH Pull Air/PA {fmt_pct(row['HardHitPulledAirBbePerPa'])} | "
            f"Pull Air Rate {fmt_pct(row['PulledAirRate'])} | EV90 {row['Ev90']:.1f} | MaxEV {row['MaxEv']:.1f} | "
            f"cXISO {row['ContactXisoProxy']:.3f} | cXSLG {row['ContactXslg']:.3f} | "
            f"Expected quality {row['ExpectedPowerQuality']}"
        )


def print_rank_gaps(rows: pd.DataFrame) -> None:
    print("\n=== Much Higher in Threat C than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi").head(12).iterrows():
        print(
            f"{row['player']} ({row.get('team', '---')}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta {int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT C {row['threat_c_plus_scaled_75_xhr_25_barrel']:.1f}, LBI {row['longballIndex']:.1f}"
        )

    print("\n=== Much Lower in Threat C than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi", ascending=False).head(12).iterrows():
        print(
            f"{row['player']} ({row.get('team', '---')}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta +{int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT C {row['threat_c_plus_scaled_75_xhr_25_barrel']:.1f}, LBI {row['longballIndex']:.1f}"
        )


def correlation_table(checkpoints: list[BacktestCheckpoint]) -> pd.DataFrame:
    rows = pd.concat([checkpoint.rows.assign(checkpoint=checkpoint.checkpoint) for checkpoint in checkpoints], ignore_index=True)
    metric_columns = {
        "barrel_pa": ("RAW PREDICTIVE RESULTS", "firstBarrelsPerPa"),
        "hrt_aggregate_adjusted_xhr_pa": ("RAW PREDICTIVE RESULTS", "firstHrtAggregateAdjustedXhrPerPa"),
        "hrt_event_ct30_proxy_pa": ("RAW PREDICTIVE RESULTS", "firstAdjustedXhrPerPa"),
        "current_script_adjusted_xhr_pa": ("RAW PREDICTIVE RESULTS", "firstAdjustedXhrPerPa"),
        "actual_hr_pa_to_date": ("RAW PREDICTIVE RESULTS", "firstActualHrPerPa"),
        "lbi_alone": ("RAW PREDICTIVE RESULTS", "firstLbiProxy"),
        "threat_c_raw_75_xhr_25_barrel": ("RAW PREDICTIVE RESULTS", "firstRawThreatC"),
        "prior_stabilized_current_prior_xhr_barrel": ("RAW PREDICTIVE RESULTS", "firstPriorStabilized"),
        "prior_stabilized_plus_contact_xiso": ("RAW PREDICTIVE RESULTS", "firstPriorStabilizedContactXiso"),
        "prior_stabilized_plus_ev90": ("RAW PREDICTIVE RESULTS", "firstPriorStabilizedEv90"),
        "prior_stabilized_plus_pull_air_ev_interaction": (
            "RAW PREDICTIVE RESULTS",
            "firstPriorStabilizedPullAirEvInteraction",
        ),
        "prior_stabilized_plus_contact_xiso_ev90": (
            "RAW PREDICTIVE RESULTS",
            "firstPriorStabilizedContactXisoEv90",
        ),
        "Model A: dynamic reliability baseline": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicBaseM150X150B060"),
        "Model B: dynamic reliability + age adjustment": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicAgeAdjusted"),
        "Model C: dynamic reliability + 2-year prior": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior2"),
        "Model D: dynamic reliability + 3-year prior": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3"),
        "Model E: 3-year prior + age": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3AgeAdjusted"),
        "No-prior Policy B: league-average prior fallback": (
            "AGE/MULTI-SEASON DIAGNOSTIC",
            "firstDynamicPrior3NoPriorLeagueFallback",
        ),
        "No-prior Policy C: current-only fallback": (
            "AGE/MULTI-SEASON DIAGNOSTIC",
            "firstDynamicPrior3NoPriorCurrentOnlyFallback",
        ),
        "No-prior Policy D: hybrid rookie fallback": (
            "AGE/MULTI-SEASON DIAGNOSTIC",
            "firstDynamicPrior3NoPriorHybridFallback",
        ),
        "Age1 moderate age-adjusted priors": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3AgeCurveModerate"),
        "Age2 conservative age-adjusted priors": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3AgeCurveConservative"),
        "Age3 aggressive age-adjusted priors": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3AgeCurveAggressive"),
        "YoungA <=23 Age2 prior only": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungAUnder23Age2"),
        "YoungB <=23 Age1 prior only": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungBUnder23Age1"),
        "YoungC <=23 +2% final": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungCUnder23Boost2"),
        "YoungC <=23 +3% final": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungCUnder23Boost3"),
        "YoungC <=23 +4% final": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungCUnder23Boost4"),
        "YoungD <=24 Age2 prior only": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungDUnder24Age2"),
        "YoungE <=23 and <2 prior Age2": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstYoungEUnder23LowPriorAge2"),
        "Model F: 3-year prior + trajectory": ("AGE/MULTI-SEASON DIAGNOSTIC", "firstDynamicPrior3Trajectory"),
        "dynamic_base_m150_x150_b060": ("PULLED-AIR EV DIAGNOSTIC", "firstDynamicBaseM150X150B060"),
        "PA1_base_plus_ev90_on_pulled_air": ("PULLED-AIR EV DIAGNOSTIC", "firstPa1DynamicPlusEv90OnPulledAir"),
        "PA2_base_plus_shrunk_ev90_on_pulled_air": (
            "PULLED-AIR EV DIAGNOSTIC",
            "firstPa2DynamicPlusShrunkEv90OnPulledAir",
        ),
        "PA3_base_plus_max_ev_on_pulled_air": ("PULLED-AIR EV DIAGNOSTIC", "firstPa3DynamicPlusMaxEvOnPulledAir"),
        "PA4_base_plus_avg_ev_on_pulled_air": ("PULLED-AIR EV DIAGNOSTIC", "firstPa4DynamicPlusAvgEvOnPulledAir"),
        "PA5_base_plus_pulled_air_ev_quality": (
            "PULLED-AIR EV DIAGNOSTIC",
            "firstPa5DynamicPlusPulledAirEvQuality",
        ),
        "PA6_base_plus_pulled_air_loud_quality": (
            "PULLED-AIR EV DIAGNOSTIC",
            "firstPa6DynamicPlusPulledAirLoudQuality",
        ),
        "PA7_base_plus_hard_hit_pulled_air_per_pa": (
            "PULLED-AIR EV DIAGNOSTIC",
            "firstPa7DynamicPlusHardHitPulledAirBbePerPa",
        ),
        "PA8_base_plus_loud_pulled_air_per_pa": ("PULLED-AIR EV DIAGNOSTIC", "firstPa8DynamicPlusLoudPulledAirBbePerPa"),
        "PA9_base_plus_crushed_pulled_air_per_pa": (
            "PULLED-AIR EV DIAGNOSTIC",
            "firstPa9DynamicPlusCrushedPulledAirBbePerPa",
        ),
        "contact_xiso_proxy": ("RAW PREDICTIVE RESULTS", "firstContactXisoProxy"),
        "pull_air_ev_interaction": ("RAW PREDICTIVE RESULTS", "firstPullAirEvInteraction"),
        "threat_c_plus_scaled_75_xhr_25_barrel": ("PLUS-SCALED DISPLAY RESULTS", "threat_c_plus_scaled_75_xhr_25_barrel"),
    }
    all_future_rate = rows["futureHr"].sum() / rows["futurePa"].sum() if rows["futurePa"].sum() else None
    output = []
    for label, (category, column) in metric_columns.items():
        sample = rows[[column, "futureHrPerPa"]].dropna()
        if len(sample) < 3:
            pearson = None
            spearman = None
            top_decile_rate = None
            top_decile_lift = None
            top25_rate = None
        else:
            pearson = sample[column].corr(sample["futureHrPerPa"], method="pearson")
            spearman = sample[column].corr(sample["futureHrPerPa"], method="spearman")
            sorted_rows = rows.dropna(subset=[column]).sort_values(column, ascending=False)
            top_decile_n = max(int(len(sorted_rows) * 0.10), 1)
            top_decile = sorted_rows.head(top_decile_n)
            top25 = sorted_rows.head(min(25, len(sorted_rows)))
            top_decile_rate = top_decile["futureHr"].sum() / top_decile["futurePa"].sum() if top_decile["futurePa"].sum() else None
            top25_rate = top25["futureHr"].sum() / top25["futurePa"].sum() if top25["futurePa"].sum() else None
            top_decile_lift = (top_decile_rate / all_future_rate - 1) if top_decile_rate is not None and all_future_rate else None
        output.append(
            {
                "metric": label,
                "category": category,
                "n": len(sample),
                "pearson": pearson,
                "spearman": spearman,
                "topDecileFutureHrPa": top_decile_rate,
                "topDecileLift": top_decile_lift,
                "top25FutureHrPa": top25_rate,
            }
        )
    return pd.DataFrame(output).sort_values("pearson", ascending=False)


def metric_summary_from_rows_target(
    rows: pd.DataFrame,
    metric_label: str,
    column: str,
    target_prefix: str = "future",
) -> dict[str, Any]:
    target_rate_column = f"{target_prefix}HrPerPa"
    target_hr_column = f"{target_prefix}Hr"
    target_pa_column = f"{target_prefix}Pa"
    sample = rows[[column, target_rate_column]].dropna()
    all_future_rate = rows[target_hr_column].sum() / rows[target_pa_column].sum() if rows[target_pa_column].sum() else None
    if len(sample) < 3:
        pearson = None
        spearman = None
        rmse = None
        top_decile_rate = None
        top_decile_lift = None
        top25_rate = None
    else:
        pearson = sample[column].corr(sample[target_rate_column], method="pearson")
        spearman = sample[column].corr(sample[target_rate_column], method="spearman")
        rmse = float(((sample[column] - sample[target_rate_column]) ** 2).mean() ** 0.5)
        sorted_rows = rows.dropna(subset=[column]).sort_values(column, ascending=False)
        top_decile_n = max(int(len(sorted_rows) * 0.10), 1)
        top_decile = sorted_rows.head(top_decile_n)
        top25 = sorted_rows.head(min(25, len(sorted_rows)))
        top_decile_rate = top_decile[target_hr_column].sum() / top_decile[target_pa_column].sum() if top_decile[target_pa_column].sum() else None
        top25_rate = top25[target_hr_column].sum() / top25[target_pa_column].sum() if top25[target_pa_column].sum() else None
        top_decile_lift = (top_decile_rate / all_future_rate - 1) if top_decile_rate is not None and all_future_rate else None
    return {
        "metric": metric_label,
        "n": len(sample),
        "pearson": pearson,
        "spearman": spearman,
        "rmse": rmse,
        "topDecileFutureHrPa": top_decile_rate,
        "topDecileLift": top_decile_lift,
        "top25FutureHrPa": top25_rate,
    }


def metric_summary_from_rows(rows: pd.DataFrame, metric_label: str, column: str) -> dict[str, Any]:
    return metric_summary_from_rows_target(rows, metric_label, column, "future")


def average_metric_across_seasons(rows: pd.DataFrame, label: str, column: str, target_prefix: str = "future") -> dict[str, Any]:
    season_summaries = [
        metric_summary_from_rows_target(season_rows, label, column, target_prefix)
        for _, season_rows in rows.groupby("season")
    ]
    if not season_summaries:
        return {
            "metric": label,
            "column": column,
            "n": 0,
            "avgPearson": None,
            "avgSpearman": None,
            "avgRmse": None,
            "avgTopDecileLift": None,
            "avgTop25FutureHrPa": None,
            "seasonResults": [],
        }
    return {
        "metric": label,
        "column": column,
        "n": sum(int(summary["n"]) for summary in season_summaries),
        "avgPearson": pd.Series([summary["pearson"] for summary in season_summaries], dtype="float64").mean(),
        "avgSpearman": pd.Series([summary["spearman"] for summary in season_summaries], dtype="float64").mean(),
        "avgRmse": pd.Series([summary["rmse"] for summary in season_summaries], dtype="float64").mean(),
        "avgTopDecileLift": pd.Series([summary["topDecileLift"] for summary in season_summaries], dtype="float64").mean(),
        "avgTop25FutureHrPa": pd.Series([summary["top25FutureHrPa"] for summary in season_summaries], dtype="float64").mean(),
        "seasonResults": season_summaries,
    }


def summarize_pull_air_juice_definition(rows: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    count_col = f"firstPaj{spec['columnSlug']}Count"
    hr_col = f"firstPaj{spec['columnSlug']}Hr"
    per_pa_col = f"firstPaj{spec['columnSlug']}PerPa"
    dynamic_col = f"{per_pa_col}DynamicSeasoning"
    modele_col = f"{per_pa_col}ModelESeasoning"
    count = to_numeric(rows.get(count_col, pd.Series(index=rows.index, dtype="float64"))).fillna(0)
    hr_count = to_numeric(rows.get(hr_col, pd.Series(index=rows.index, dtype="float64"))).fillna(0)
    first_hr = to_numeric(rows.get("firstHr", pd.Series(index=rows.index, dtype="float64"))).fillna(0)
    first_pulled_hr = to_numeric(rows.get("firstPulledHr", pd.Series(index=rows.index, dtype="float64"))).fillna(0)
    first_pa = to_numeric(rows.get("firstPa", pd.Series(index=rows.index, dtype="float64"))).fillna(0)
    conversion = hr_count.sum() / count.sum() if count.sum() else None
    coverage = hr_count.sum() / first_hr.sum() if first_hr.sum() else None
    pulled_coverage = hr_count.sum() / first_pulled_hr.sum() if first_pulled_hr.sum() else None
    same_window_sample = rows[[per_pa_col, "firstActualHrPerPa"]].dropna() if per_pa_col in rows.columns else pd.DataFrame()
    same_window_pearson = (
        same_window_sample[per_pa_col].corr(same_window_sample["firstActualHrPerPa"], method="pearson")
        if len(same_window_sample) >= 3
        else None
    )
    same_window_spearman = (
        same_window_sample[per_pa_col].corr(same_window_sample["firstActualHrPerPa"], method="spearman")
        if len(same_window_sample) >= 3
        else None
    )
    standalone = average_metric_across_seasons(rows, spec["label"], per_pa_col)
    dynamic = average_metric_across_seasons(rows, f"{spec['label']} + dynamic seasoning", dynamic_col)
    modele = average_metric_across_seasons(rows, f"{spec['label']} + Model E seasoning", modele_col)
    return {
        "spec": spec,
        "countColumn": count_col,
        "perPaColumn": per_pa_col,
        "dynamicColumn": dynamic_col,
        "modelEColumn": modele_col,
        "totalEvents": float(count.sum()),
        "totalEventHr": float(hr_count.sum()),
        "conversionRate": conversion,
        "hrCoverage": coverage,
        "pulledHrCoverage": pulled_coverage,
        "zeroPct": float(count.eq(0).mean()),
        "avgCount": float(count.mean()),
        "medianCount": float(count.median()),
        "avgPer100Pa": float(((count / first_pa.where(first_pa.gt(0))) * 100).mean()),
        "sameWindowPearson": same_window_pearson,
        "sameWindowSpearman": same_window_spearman,
        "standalone": standalone,
        "dynamic": dynamic,
        "modelE": modele,
    }


def fmt_metric(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def fmt_signed_pct(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:+.{digits}f}%"


def print_pull_air_juice_definition_report(rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    summaries = [summarize_pull_air_juice_definition(rows, spec) for spec in PULL_AIR_JUICE_SPECS]
    print("\n=== Pull-Air Juice Definition Diagnostic ===")
    print(
        "Pulled side uses the existing checkpoint-safe Statcast hc_x/stand classifier. "
        "All definitions require pulled contact, launch_speed at the listed threshold, and the listed launch-angle window; "
        "bb_type variants are additional filters."
    )
    print(
        "Definitions tested: pulled barrels, six binary threshold versions, "
        "four weighted damage-score versions, and four bb_type versions "
        f"({len(summaries)} total). A2 pulled barrel + HR-capable event is not tested here because "
        "the checkpoint-safe Statcast cache does not expose a direct HR-capable flag."
    )

    def ranking_frame(kind: str) -> pd.DataFrame:
        output = []
        for summary in summaries:
            metric = summary[kind]
            output.append(
                {
                    "label": summary["spec"]["label"],
                    "shortLabel": summary["spec"]["shortLabel"],
                    "column": summary[f"{kind}Column"] if kind in {"dynamic", "modelE"} else summary["perPaColumn"],
                    "pearson": metric["avgPearson"],
                    "spearman": metric["avgSpearman"],
                    "rmse": metric["avgRmse"],
                    "topDecileLift": metric["avgTopDecileLift"],
                    "top25FutureHrPa": metric["avgTop25FutureHrPa"],
                    "conversionRate": summary["conversionRate"],
                    "hrCoverage": summary["hrCoverage"],
                    "pulledHrCoverage": summary["pulledHrCoverage"],
                    "zeroPct": summary["zeroPct"],
                    "avgCount": summary["avgCount"],
                    "medianCount": summary["medianCount"],
                    "avgPer100Pa": summary["avgPer100Pa"],
                    "sameWindowPearson": summary["sameWindowPearson"],
                    "sameWindowSpearman": summary["sameWindowSpearman"],
                    "spec": summary["spec"],
                    "summary": summary,
                }
            )
        return pd.DataFrame(output)

    standalone = ranking_frame("standalone").sort_values("pearson", ascending=False)
    dynamic = ranking_frame("dynamic").sort_values("pearson", ascending=False)
    modele = ranking_frame("modelE").sort_values("pearson", ascending=False)
    conversion = standalone.sort_values("conversionRate", ascending=False)
    coverage = standalone.sort_values("hrCoverage", ascending=False)

    def print_table(title: str, frame: pd.DataFrame, limit: int = 10) -> None:
        print(f"\n{title}")
        for _, row in frame.head(limit).iterrows():
            print(
                f"- {row['shortLabel']}: Pearson {fmt_metric(row['pearson'])}, "
                f"Spearman {fmt_metric(row['spearman'])}, RMSE {fmt_metric(row['rmse'], 4)}, "
                f"top-decile lift {fmt_signed_pct(row['topDecileLift'])}, "
                f"top-25 HR/PA {fmt_pct(row['top25FutureHrPa'])}, "
                f"HR conv {fmt_pct(row['conversionRate'], 1)}, HR coverage {fmt_pct(row['hrCoverage'], 1)}, "
                f"pulled HR coverage {fmt_pct(row['pulledHrCoverage'], 1)}, zero {fmt_pct(row['zeroPct'], 1)}, "
                f"avg count {row['avgCount']:.2f}, median {row['medianCount']:.1f}"
            )

    print_table("Standalone Pull-Air Juice candidates, ranked by future HR/PA Pearson", standalone)
    print_table("5% seasoning on dynamic Longball Threat base, ranked by Pearson", dynamic)
    print_table("5% seasoning on Model E + league no-prior fallback, ranked by Pearson", modele)
    print_table("Cleanest HR-conversion definitions", conversion.head(10), 10)
    print_table("Best actual-HR coverage definitions", coverage.head(10), 10)

    pulled_barrels = standalone[standalone["spec"].map(lambda spec: spec["slug"] == "a1_pulled_barrel")]
    threshold_15_40 = standalone[
        standalone["spec"].map(lambda spec: spec.get("mode") == "threshold" and spec.get("low") == 15 and spec.get("high") == 40)
    ].sort_values("pearson", ascending=False)
    threshold_20_38 = standalone[
        standalone["spec"].map(lambda spec: spec.get("mode") == "threshold" and spec.get("low") == 20 and spec.get("high") == 38)
    ].sort_values("pearson", ascending=False)
    ev100 = standalone[standalone["spec"].map(lambda spec: spec.get("threshold") == 100)].sort_values("pearson", ascending=False)
    ev105 = standalone[standalone["spec"].map(lambda spec: spec.get("threshold") == 105)].sort_values("pearson", ascending=False)
    weighted = standalone[standalone["spec"].map(lambda spec: spec.get("mode") == "weighted")].sort_values("pearson", ascending=False)
    fly_only = standalone[standalone["spec"].map(lambda spec: spec.get("bbtype") == "fly_ball_only")].sort_values("pearson", ascending=False)
    fly_line = standalone[standalone["spec"].map(lambda spec: spec.get("bbtype") == "fly_line")].sort_values("pearson", ascending=False)

    best = standalone.iloc[0]
    best_dynamic = dynamic.iloc[0]
    best_modele = modele.iloc[0]
    print("\nPull-Air Juice key checks")
    if not pulled_barrels.empty:
        row = pulled_barrels.iloc[0]
        print(
            f"- Pulled barrels: Pearson {fmt_metric(row['pearson'])}, "
            f"HR conv {fmt_pct(row['conversionRate'], 1)}, coverage {fmt_pct(row['hrCoverage'], 1)}, "
            f"pulled HR coverage {fmt_pct(row['pulledHrCoverage'], 1)}, zero {fmt_pct(row['zeroPct'], 1)}, "
            f"median count {row['medianCount']:.1f}."
        )
    if not threshold_15_40.empty and not threshold_20_38.empty:
        wide = threshold_15_40.iloc[0]
        tight = threshold_20_38.iloc[0]
        print(
            f"- 15-40 vs 20-38: best 15-40 Pearson {fmt_metric(wide['pearson'])} "
            f"({wide['shortLabel']}) vs best 20-38 Pearson {fmt_metric(tight['pearson'])} ({tight['shortLabel']})."
        )
    if not ev100.empty and not ev105.empty:
        print(
            f"- 100+ vs 105+: best 100+ Pearson {fmt_metric(ev100.iloc[0]['pearson'])}, "
            f"zero {fmt_pct(ev100.iloc[0]['zeroPct'], 1)}; best 105+ Pearson {fmt_metric(ev105.iloc[0]['pearson'])}, "
            f"zero {fmt_pct(ev105.iloc[0]['zeroPct'], 1)}."
        )
    if not weighted.empty:
        print(
            f"- Weighted versions: best weighted Pearson {fmt_metric(weighted.iloc[0]['pearson'])} "
            f"({weighted.iloc[0]['shortLabel']}) vs best binary Pearson {fmt_metric(standalone.iloc[0]['pearson'])}."
        )
    if not fly_only.empty and not fly_line.empty:
        print(
            f"- Batted-ball filters: fly_ball-only best Pearson {fmt_metric(fly_only.iloc[0]['pearson'])}; "
            f"fly_ball+line_drive best {fmt_metric(fly_line.iloc[0]['pearson'])}."
        )
    print(
        f"- Best standalone context stat: {best['shortLabel']} "
        f"(Pearson {fmt_metric(best['pearson'])}, HR conv {fmt_pct(best['conversionRate'], 1)}, "
        f"coverage {fmt_pct(best['hrCoverage'], 1)}, pulled HR coverage {fmt_pct(best['pulledHrCoverage'], 1)})."
    )
    print(
        f"- Best dynamic seasoning: {best_dynamic['shortLabel']} "
        f"(Pearson {fmt_metric(best_dynamic['pearson'])}, top-decile lift {fmt_signed_pct(best_dynamic['topDecileLift'])})."
    )
    print(
        f"- Best Model E seasoning: {best_modele['shortLabel']} "
        f"(Pearson {fmt_metric(best_modele['pearson'])}, top-decile lift {fmt_signed_pct(best_modele['topDecileLift'])})."
    )

    final_2025 = rows[rows["season"].eq(2025)].copy()
    if not final_2025.empty:
        final_checkpoint = final_2025["checkpoint"].max()
        final_rows = final_2025[final_2025["checkpoint"].eq(final_checkpoint)].copy()
        if not final_rows.empty:
            print(f"\nTop 20 final 2025 checkpoint leaders for {best['shortLabel']} ({final_checkpoint})")
            count_col = best["summary"]["countColumn"]
            per100_col = best["summary"]["perPaColumn"].replace("PerPa", "Per100Pa")
            top = final_rows.sort_values([per100_col, count_col, "firstPa"], ascending=[False, False, False]).head(20)
            for _, row in top.iterrows():
                print(
                    f"- {row['player']}: {row[per100_col]:.2f} per 100 PA, "
                    f"{int(row[count_col])} events, PA {int(row['firstPa'])}, "
                    f"HR {int(row['firstHr'])}, future HR/PA {fmt_pct(row['futureHrPerPa'])}"
                )

    print("\nPull-Air Juice recommendation")
    print(
        "Use this as context only for now. Pick the public definition for interpretability and sample stability, "
        "not because it materially improves Longball Threat. The diagnostic copy should avoid 'pulled fly balls' "
        "unless the fly_ball-only filter is chosen."
    )


def official_bat_tracking_with_pa(season: int) -> pd.DataFrame:
    official = load_official_bat_tracking(season)
    if official.empty:
        return pd.DataFrame()
    try:
        _, _, pitches, _, _, _, _ = load_season_context(season)
    except Exception:
        return official
    stats = pitch_window_stats(pitches, min(pitches["game_date"]), max(pitches["game_date"]), "batTracking")
    keep = ["batter", "batTrackingPa"] if "batTrackingPa" in stats.columns else ["batter"]
    merged = official.merge(stats[keep], on="batter", how="left")
    pa = to_numeric(merged.get("batTrackingPa", pd.Series(index=merged.index))).where(
        to_numeric(merged.get("batTrackingPa", pd.Series(index=merged.index))).gt(0)
    )
    merged["officialBlastPerPa"] = merged["officialBlastCount"] / pa
    merged["officialSquaredUpPerPa"] = merged["officialSquaredUpCount"] / pa
    return merged


def print_blast_pa_modern_era_report(rows: pd.DataFrame) -> None:
    print("\n=== Modern-Era Blast/PA Diagnostic (2024-2025) ===")
    print("Official Savant bat-tracking fields found in local cache:")
    for season in [2024, 2025]:
        official = load_official_bat_tracking(season)
        path = bat_tracking_cache_path(season)
        if official.empty:
            print(f"- {season}: no local cache at {path}")
            continue
        print(
            f"- {season}: {path} | players {len(official)} | fields: "
            "swings_competitive, contact, avg_bat_speed, hard_swing_rate, "
            "squared_up_per_bat_contact, squared_up_per_swing, blast_per_bat_contact, "
            "blast_per_swing, batted_ball_events"
        )
    print(
        "Date-filter safety: simple Savant CSV tests with game_date_gt/game_date_lt returned the same rows as the "
        "full-season export, so official Blast is treated as season-level only here. Checkpoint-safe tests below use "
        "event-level bat-speed proxies from the local Statcast cache, not official Blast flags."
    )
    print(
        "Official definition context: Savant describes a Blast as a squared-up swing with a fast swing. "
        "The local pitch cache has bat_speed, but not the official event-level squared-up/blast flag."
    )

    modern = rows[rows["season"].isin([2024, 2025])].copy()
    if modern.empty:
        print("No 2024-2025 checkpoint rows available.")
        return

    model_columns = {
        "Model E + league no-prior fallback": "firstDynamicPrior3NoPriorLeagueFallback",
        "dynamic reliability baseline": "firstDynamicBaseM150X150B060",
        "barrel_pa": "firstBarrelsPerPa",
        "xHR proxy/PA": "firstAdjustedXhrPerPa",
        "checkpoint fast swing/PA proxy": "firstFastSwingPerPa",
        "checkpoint fast swing rate proxy": "firstFastSwingRate",
        "checkpoint fast contact/PA proxy": "firstFastContactPerPa",
        "checkpoint fast contact rate proxy": "firstFastContactRate",
        "checkpoint fast loud contact/PA proxy": "firstFastLoudContactPerPa",
        "checkpoint fast barrel/PA proxy": "firstFastBarrelsPerPa",
        "Model E + fast swing/PA seasoning": "firstFastSwingPerPaModelESeasoning",
        "Model E + fast swing rate seasoning": "firstFastSwingRateModelESeasoning",
        "Model E + fast contact/PA seasoning": "firstFastContactPerPaModelESeasoning",
        "Model E + fast loud contact/PA seasoning": "firstFastLoudContactPerPaModelESeasoning",
        "Model E + fast barrel/PA seasoning": "firstFastBarrelsPerPaModelESeasoning",
    }
    output = []
    for label, column in model_columns.items():
        if column in modern.columns:
            output.append(average_metric_across_seasons(modern, label, column, "future"))
    summary = pd.DataFrame(output).sort_values("avgPearson", ascending=False)
    print("\nCheckpoint-safe 2024-2025 bat-speed proxy tests")
    for _, row in summary.iterrows():
        print(
            f"- {row['metric']}: Pearson {fmt_metric(row['avgPearson'])}, "
            f"Spearman {fmt_metric(row['avgSpearman'])}, RMSE {fmt_metric(row['avgRmse'], 4)}, "
            f"top-decile lift {fmt_signed_pct(row['avgTopDecileLift'])}, "
            f"top-25 HR/PA {fmt_pct(row['avgTop25FutureHrPa'])}, n={int(row['n'])}"
        )

    prior_official = official_bat_tracking_with_pa(2024)
    rows_2025 = modern[modern["season"].eq(2025)].copy()
    if not prior_official.empty and not rows_2025.empty:
        prior = prior_official[
            [
                "batter",
                "officialBlastPerPa",
                "officialSquaredUpPerPa",
                "blast_per_swing",
                "blast_per_bat_contact",
                "avg_bat_speed",
                "hard_swing_rate",
            ]
        ].rename(
            columns={
                "officialBlastPerPa": "priorOfficialBlastPerPa",
                "officialSquaredUpPerPa": "priorOfficialSquaredUpPerPa",
                "blast_per_swing": "priorOfficialBlastPerSwing",
                "blast_per_bat_contact": "priorOfficialBlastPerContact",
                "avg_bat_speed": "priorOfficialAvgBatSpeed",
                "hard_swing_rate": "priorOfficialHardSwingRate",
            }
        )
        joined = rows_2025.merge(prior, on="batter", how="left")
        for source in [
            "priorOfficialBlastPerPa",
            "priorOfficialSquaredUpPerPa",
            "priorOfficialBlastPerSwing",
            "priorOfficialBlastPerContact",
            "priorOfficialAvgBatSpeed",
            "priorOfficialHardSwingRate",
        ]:
            scale_to_xhr_rate(joined, source, f"{source}RateScale", "firstAdjustedXhrPerPa")
            joined[f"{source}ModelESeasoning"] = 0.95 * joined["firstDynamicPrior3NoPriorLeagueFallback"] + 0.05 * joined[
                f"{source}RateScale"
            ]
        official_models = {
            "2024 official Blast/PA prior": "priorOfficialBlastPerPa",
            "2024 official Blast/swing prior": "priorOfficialBlastPerSwing",
            "2024 official Blast/contact prior": "priorOfficialBlastPerContact",
            "2024 official avg bat speed prior": "priorOfficialAvgBatSpeed",
            "Model E + 2024 official Blast/PA prior": "priorOfficialBlastPerPaModelESeasoning",
            "Model E + 2024 official Blast/swing prior": "priorOfficialBlastPerSwingModelESeasoning",
            "Model E + 2024 official Blast/contact prior": "priorOfficialBlastPerContactModelESeasoning",
        }
        print("\n2025 checkpoint test using 2024 official season-level Blast as a no-leak prior")
        for label, column in official_models.items():
            result = metric_summary_from_rows_target(joined, label, column, "future")
            print(
                f"- {label}: Pearson {fmt_metric(result['pearson'])}, Spearman {fmt_metric(result['spearman'])}, "
                f"RMSE {fmt_metric(result['rmse'], 4)}, top-decile lift {fmt_signed_pct(result['topDecileLift'])}, "
                f"top-25 HR/PA {fmt_pct(result['top25FutureHrPa'])}, n={int(result['n'])}"
            )
    else:
        print("\nNo 2024 official bat-tracking cache available for the 2025 prior test.")

    final_2025 = rows_2025[rows_2025["checkpoint"].eq(rows_2025["checkpoint"].max())].copy()
    if not final_2025.empty:
        print("\nFinal 2025 checkpoint leaders: fast barrel/PA proxy")
        leaders = final_2025.sort_values("firstFastBarrelsPerPa", ascending=False).head(20)
        for _, row in leaders.iterrows():
            print(
                f"- {row['player']}: fast barrel/PA {fmt_pct(row['firstFastBarrelsPerPa'])}, "
                f"fast loud contact/PA {fmt_pct(row['firstFastLoudContactPerPa'])}, "
                f"fast swing rate {fmt_pct(row['firstFastSwingRate'])}, "
                f"Model E {fmt_metric(row['firstDynamicPrior3NoPriorLeagueFallback'], 4)}, "
                f"future HR/PA {fmt_pct(row['futureHrPerPa'])}"
            )

    print("\nBlast/PA interpretation")
    print(
        "- For a future public modern-era Longball Threat, official Blast/PA should be added only if we can fetch "
        "date-filtered official bat-tracking exports or archive daily/weekly bat-tracking snapshots."
    )
    print(
        "- With the current local data, the checkpoint-safe proxy is fast/loud or fast-barrel contact per PA. "
        "That measures a similar idea, but it is not official Blast/PA because the official squared-up flag is missing."
    )


def dynamic_threat_grid_evaluation(checkpoint_rows: pd.DataFrame) -> pd.DataFrame:
    rows = checkpoint_rows.copy()
    required_columns = [
        "firstPa",
        "firstAdjustedXhrPerPa",
        "firstBarrelsPerPa",
        "firstPriorAdjustedXhrPerPa",
        "firstPriorBarrelsPerPa",
        "futureHrPerPa",
    ]
    for column in required_columns:
        if column not in rows.columns:
            rows[column] = pd.NA
        rows[column] = to_numeric(rows[column])

    output = []
    for m_barrel in DYNAMIC_M_BARREL_GRID:
        w_barrel = rows["firstPa"] / (rows["firstPa"] + m_barrel)
        stabilized_barrel = (
            w_barrel * rows["firstBarrelsPerPa"]
            + (1 - w_barrel) * rows["firstPriorBarrelsPerPa"]
        )
        for m_xhr in DYNAMIC_M_XHR_GRID:
            w_xhr = rows["firstPa"] / (rows["firstPa"] + m_xhr)
            stabilized_xhr = (
                w_xhr * rows["firstAdjustedXhrPerPa"]
                + (1 - w_xhr) * rows["firstPriorAdjustedXhrPerPa"]
            )
            for blend_xhr in DYNAMIC_BLEND_XHR_GRID:
                label = (
                    f"dynamic_reliability_mbarrel_{m_barrel}_"
                    f"mxhr_{m_xhr}_blend_{blend_xhr:.2f}"
                )
                rows[label] = blend_xhr * stabilized_xhr + (1 - blend_xhr) * stabilized_barrel
                for season, season_rows in rows.groupby("season"):
                    summary = metric_summary_from_rows(season_rows, label, label)
                    summary["season"] = season
                    summary["mBarrel"] = m_barrel
                    summary["mXhr"] = m_xhr
                    summary["blendXhr"] = blend_xhr
                    output.append(summary)
                rows.drop(columns=[label], inplace=True)
    return pd.DataFrame(output)


def summarize_dynamic_grid(dynamic: pd.DataFrame) -> pd.DataFrame:
    if dynamic.empty:
        return pd.DataFrame()
    return (
        dynamic.groupby(["metric", "mBarrel", "mXhr", "blendXhr"], as_index=False)
        .agg(
            avgPearson=("pearson", "mean"),
            avgSpearman=("spearman", "mean"),
            avgRmse=("rmse", "mean"),
            avgTopDecileLift=("topDecileLift", "mean"),
            avgTop25FutureHrPa=("top25FutureHrPa", "mean"),
            seasons=("season", "nunique"),
        )
    )


def print_dynamic_grid(dynamic: pd.DataFrame) -> pd.DataFrame:
    summary = summarize_dynamic_grid(dynamic)
    if summary.empty:
        print("\n=== Dynamic Reliability Grid ===")
        print("No dynamic reliability results available.")
        return summary

    def print_row(label: str, row: pd.Series) -> None:
        print(
            f"{label}: M_barrel={int(row['mBarrel'])}, M_xhr={int(row['mXhr'])}, "
            f"blend_xhr={row['blendXhr']:.2f} | Pearson {row['avgPearson']:.3f}, "
            f"Spearman {row['avgSpearman']:.3f}, RMSE {row['avgRmse']:.4f}, "
            f"top-decile lift {row['avgTopDecileLift'] * 100:+.1f}%, "
            f"top-25 HR/PA {row['avgTop25FutureHrPa'] * 100:.2f}%"
        )

    best_pearson = summary.sort_values("avgPearson", ascending=False).iloc[0]
    best_spearman = summary.sort_values("avgSpearman", ascending=False).iloc[0]
    best_rmse = summary.sort_values("avgRmse", ascending=True).iloc[0]
    best_lift = summary.sort_values("avgTopDecileLift", ascending=False).iloc[0]

    print("\n=== Dynamic Reliability Grid ===")
    print_row("Best by Pearson", best_pearson)
    print_row("Best by Spearman", best_spearman)
    print_row("Best by RMSE", best_rmse)
    print_row("Best by top-decile lift", best_lift)

    print("\nTop dynamic combos by Pearson")
    for _, row in summary.sort_values("avgPearson", ascending=False).head(10).iterrows():
        print_row("-", row)

    print("\nDynamic season winners")
    for season, season_rows in dynamic.dropna(subset=["pearson"]).groupby("season"):
        winner = season_rows.sort_values("pearson", ascending=False).iloc[0]
        print(
            f"- {int(season)}: M_barrel={int(winner['mBarrel'])}, M_xhr={int(winner['mXhr'])}, "
            f"blend_xhr={winner['blendXhr']:.2f}, Pearson {winner['pearson']:.3f}, "
            f"Spearman {winner['spearman']:.3f}, top-decile lift {winner['topDecileLift'] * 100:+.1f}%"
        )

    return summary


def ridge_scored_rows(checkpoint_rows: pd.DataFrame, target_prefix: str = "future") -> pd.DataFrame:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import RidgeCV
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        print(f"\nCandidate G ridge model skipped: sklearn unavailable ({exc}).")
        return pd.DataFrame()

    rows = checkpoint_rows.copy()
    target_rate_column = f"{target_prefix}HrPerPa"
    for column in RIDGE_FEATURE_COLUMNS + [target_rate_column]:
        if column not in rows.columns:
            rows[column] = pd.NA
        rows[column] = to_numeric(rows[column])
    feature_columns = [column for column in RIDGE_FEATURE_COLUMNS if rows[column].notna().any()]
    if not feature_columns:
        print("\nCandidate G ridge model skipped: no non-null feature columns.")
        return pd.DataFrame()

    predictions: list[pd.DataFrame] = []
    coefficient_rows = []
    for season in sorted(rows["season"].dropna().unique()):
        train = rows[rows["season"].ne(season)].dropna(subset=[target_rate_column])
        test = rows[rows["season"].eq(season)].dropna(subset=[target_rate_column])
        if len(train) < 50 or len(test) < 10:
            continue
        train_features = train[feature_columns].replace([float("inf"), -float("inf")], pd.NA)
        test_features = test[feature_columns].replace([float("inf"), -float("inf")], pd.NA)
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            RidgeCV(alphas=[0.01, 0.1, 1.0, 3.0, 10.0, 30.0]),
        )
        model.fit(train_features, train[target_rate_column])
        scored = test.copy()
        scored["ridgePrediction"] = model.predict(test_features)
        predictions.append(scored)
        ridge = model.named_steps["ridgecv"]
        coefficient_rows.append(
            {
                "season": season,
                "alpha": float(ridge.alpha_),
                **{feature: float(coef) for feature, coef in zip(feature_columns, ridge.coef_)},
            }
        )

    if not predictions:
        return pd.DataFrame()

    scored_rows = pd.concat(predictions, ignore_index=True)
    if coefficient_rows:
        coef_frame = pd.DataFrame(coefficient_rows)
        scored_rows.attrs["ridge_coefficients"] = coef_frame
        scored_rows.attrs["ridge_feature_columns"] = feature_columns
    return scored_rows


def ridge_evaluation(checkpoint_rows: pd.DataFrame, target_prefix: str = "future") -> pd.DataFrame:
    scored_rows = ridge_scored_rows(checkpoint_rows, target_prefix)
    if scored_rows.empty:
        return pd.DataFrame()

    output = []
    for season, season_rows in scored_rows.groupby("season"):
        summary = metric_summary_from_rows_target(season_rows, "Candidate G: ridge model", "ridgePrediction", target_prefix)
        summary["season"] = season
        output.append(summary)
    coef_frame = scored_rows.attrs.get("ridge_coefficients")
    feature_columns = scored_rows.attrs.get("ridge_feature_columns", [])
    if isinstance(coef_frame, pd.DataFrame) and not coef_frame.empty:
        print("\n=== Ridge Coefficients (standardized features, leave-one-season-out) ===")
        print(f"Average alpha: {coef_frame['alpha'].mean():.2f}")
        means = coef_frame[feature_columns].mean().sort_values(key=lambda series: series.abs(), ascending=False)
        for feature, value in means.items():
            print(f"- {feature}: {value:+.5f}")
    return pd.DataFrame(output)


def print_backtest(checkpoints: list[BacktestCheckpoint], season: int) -> pd.DataFrame:
    print(f"\n=== {season} Monthly Checkpoint Backtest ===")
    for checkpoint in checkpoints:
        rate = checkpoint.rows["futureHr"].sum() / checkpoint.rows["futurePa"].sum()
        print(
            f"{checkpoint.checkpoint} -> {checkpoint.period_end}: "
            f"{len(checkpoint.rows)} hitters | future HR/PA {rate * 100:.2f}%"
        )

    table = correlation_table(checkpoints)
    for category in [
        "RAW PREDICTIVE RESULTS",
        "AGE/MULTI-SEASON DIAGNOSTIC",
        "PULLED-AIR EV DIAGNOSTIC",
        "PLUS-SCALED DISPLAY RESULTS",
    ]:
        print(f"\n{category}")
        section = table[table["category"].eq(category)]
        for _, row in section.iterrows():
            pearson = "n/a" if pd.isna(row["pearson"]) else f"{row['pearson']:.3f}"
            spearman = "n/a" if pd.isna(row["spearman"]) else f"{row['spearman']:.3f}"
            lift = "n/a" if pd.isna(row["topDecileLift"]) else f"{row['topDecileLift'] * 100:+.1f}%"
            top25 = "n/a" if pd.isna(row["top25FutureHrPa"]) else f"{row['top25FutureHrPa'] * 100:.2f}%"
            print(
                f"- {row['metric']}: Pearson {pearson}, Spearman {spearman}, "
                f"top-decile lift {lift}, top-25 HR/PA {top25}, n={int(row['n'])}"
            )

    barrel = table[table["metric"].eq("barrel_pa")]["pearson"].iloc[0]
    event_xhr = table[table["metric"].eq("hrt_event_ct30_proxy_pa")]["pearson"].iloc[0]
    raw_threat_c = table[table["metric"].eq("threat_c_raw_75_xhr_25_barrel")]["pearson"].iloc[0]
    plus_threat_c = table[table["metric"].eq("threat_c_plus_scaled_75_xhr_25_barrel")]["pearson"].iloc[0]
    print("\nBacktest readout")
    print(
        f"Canonical core: barrel_pa {barrel:.3f}, hrt_event_ct30_proxy_pa {event_xhr:.3f}, "
        f"raw Threat C {raw_threat_c:.3f}, plus-scaled Threat C {plus_threat_c:.3f}."
    )
    return table


def print_xhr_source_diagnostics(checkpoints: list[BacktestCheckpoint], season: int) -> None:
    rows = pd.concat([checkpoint.rows.assign(checkpoint=checkpoint.checkpoint) for checkpoint in checkpoints], ignore_index=True)
    aggregate = rows["firstHrtAggregateAdjustedXhrPerPa"]
    event = rows["firstAdjustedXhrPerPa"]
    paired = rows[["firstHrtAggregateAdjustedXhrPerPa", "firstAdjustedXhrPerPa"]].dropna()
    print(f"\n=== xHR Source Diagnostics ({season}) ===")
    print("HRT aggregate adjusted xHR/PA: from season-level Longball Index JSON player xhr divided by checkpoint PA.")
    print("  Warning: this is full-season aggregate data in this local archive, so it is not a valid predictive checkpoint input.")
    print("HRT event ct/30 proxy / PA: sum of event-level Home Run Tracker ct / 30 through checkpoint, divided by PA.")
    print("Current script adjusted xHR/PA: identical to HRT event ct/30 proxy / PA in this diagnostic.")
    print(f"Players with aggregate xHR/PA: {aggregate.notna().sum()} | missing {aggregate.isna().sum()}")
    print(f"Players with event ct/30 xHR/PA: {event.notna().sum()} | missing {event.isna().sum()}")
    if len(paired) >= 3:
        print(
            "Aggregate vs event proxy correlation where both exist: "
            f"Pearson {paired['firstHrtAggregateAdjustedXhrPerPa'].corr(paired['firstAdjustedXhrPerPa'], method='pearson'):.3f}, "
            f"Spearman {paired['firstHrtAggregateAdjustedXhrPerPa'].corr(paired['firstAdjustedXhrPerPa'], method='spearman'):.3f}, "
            f"n={len(paired)}"
        )
    print("Canonical models use hrt_event_ct30_proxy_pa as best_available_adjusted_xhr_pa to avoid full-season leakage.")


def print_age_prior_diagnostics(checkpoints: list[BacktestCheckpoint], season: int) -> None:
    rows = pd.concat([checkpoint.rows.assign(checkpoint=checkpoint.checkpoint) for checkpoint in checkpoints], ignore_index=True)
    print(f"\n=== Age and Multi-Season Prior Diagnostics ({season}) ===")
    age = to_numeric(rows.get("firstAge", pd.Series(index=rows.index, dtype="float64")))
    print(f"Age present: {age.notna().sum()} | missing {age.isna().sum()}")
    if age.notna().any():
        print(
            f"Age distribution: min {age.min():.1f}, median {age.median():.1f}, "
            f"mean {age.mean():.1f}, max {age.max():.1f}"
        )
        print("Age buckets:")
        for bucket, count in rows["firstAgeBucket"].value_counts(dropna=False).sort_index().items():
            print(f"- {bucket}: {count}")
    for label, column in [
        ("1-year prior", "firstPrior1AdjustedXhrPerPa"),
        ("2-year weighted prior", "firstPrior2AdjustedXhrPerPa"),
        ("3-year weighted prior", "firstPrior3AdjustedXhrPerPa"),
    ]:
        values = to_numeric(rows.get(column, pd.Series(index=rows.index, dtype="float64")))
        print(f"{label} present: {values.notna().sum()} | missing {values.isna().sum()}")


def validation_table(
    checkpoint_rows: pd.DataFrame,
    target_prefix: str,
    ridge_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    output = []
    for season, season_rows in checkpoint_rows.groupby("season"):
        for label, column in VALIDATION_MODELS.items():
            summary = metric_summary_from_rows_target(season_rows, label, column, target_prefix)
            summary["season"] = season
            output.append(summary)
    if ridge_rows is not None and not ridge_rows.empty:
        for season, season_rows in ridge_rows.groupby("season"):
            summary = metric_summary_from_rows_target(season_rows, "ridge_model_if_available", "ridgePrediction", target_prefix)
            summary["season"] = season
            output.append(summary)
    return pd.DataFrame(output)


def summarize_validation(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return pd.DataFrame()
    return (
        table.groupby("metric", as_index=False)
        .agg(
            avgPearson=("pearson", "mean"),
            avgSpearman=("spearman", "mean"),
            avgRmse=("rmse", "mean"),
            avgTopDecileLift=("topDecileLift", "mean"),
            avgTop25FutureHrPa=("top25FutureHrPa", "mean"),
            seasons=("season", "nunique"),
            n=("n", "sum"),
        )
        .sort_values("avgPearson", ascending=False)
    )


def print_validation_report(table: pd.DataFrame, target_label: str) -> pd.DataFrame:
    summary = summarize_validation(table)
    print(f"\n=== Longball Threat Final Validation: {target_label} ===")
    if summary.empty:
        print("No validation rows available.")
        return summary

    for _, row in summary.iterrows():
        print(
            f"- {row['metric']}: Pearson {row['avgPearson']:.3f}, "
            f"Spearman {row['avgSpearman']:.3f}, RMSE {row['avgRmse']:.4f}, "
            f"top-decile lift {row['avgTopDecileLift'] * 100:+.1f}%, "
            f"top-25 HR/PA {row['avgTop25FutureHrPa'] * 100:.2f}%, "
            f"n={int(row['n'])}"
        )

    print("\nSeason-by-season results")
    for season, season_rows in table.dropna(subset=["pearson"]).groupby("season"):
        winner = season_rows.sort_values("pearson", ascending=False).iloc[0]
        print(f"- {int(season)} winner: {winner['metric']} Pearson {winner['pearson']:.3f}")
        for _, row in season_rows.sort_values("pearson", ascending=False).iterrows():
            print(
                f"  {row['metric']}: Pearson {row['pearson']:.3f}, "
                f"Spearman {row['spearman']:.3f}, RMSE {row['rmse']:.4f}, "
                f"top-decile lift {row['topDecileLift'] * 100:+.1f}%, "
                f"top-25 HR/PA {row['top25FutureHrPa'] * 100:.2f}%, n={int(row['n'])}"
            )
    return summary


def print_prior_and_age_policy_audit(checkpoint_rows: pd.DataFrame) -> None:
    print("\n=== Model E Prior and Age Handling Audit ===")
    print("Current Model E age handling: firstDynamicPrior3AgeAdjusted = firstDynamicPrior3 * firstAgePowerFactor.")
    print("Current Model E age factor buckets: <=23 1.03, 24-26 1.02, 27-29 1.00, 30-32 0.98, 33+ 0.95.")
    print("Current Model E uses an explicit multiplier, not raw age directly.")
    print("Ridge uses raw firstAge as one standardized feature when sklearn is available.")
    print("Existing prior weights are normalized over available prior seasons only.")
    print("New age-curve variants age-adjust each prior season into current-age terms before weighting.")
    print("New age-curve variants fill zero-prior players with a checkpoint league-average prior baseline and flag them.")

    counts = to_numeric(checkpoint_rows.get("firstPriorSeasonCount", pd.Series(index=checkpoint_rows.index, dtype="float64"))).fillna(0).astype(int)
    print("Prior-season counts:")
    for value in [3, 2, 1, 0]:
        print(f"- {value} prior years: {int(counts.eq(value).sum())}")
    print(f"No-prior baseline flags: {int(checkpoint_rows.get('firstNoPriorBaselineFlag', pd.Series(False, index=checkpoint_rows.index)).fillna(False).sum())}")
    age = to_numeric(checkpoint_rows.get("firstAge", pd.Series(index=checkpoint_rows.index, dtype="float64")))
    print(f"Missing age count: {int(age.isna().sum())}")


def print_age_bucket_validation(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== Age-Bucket Validation ({target_prefix} HR/PA target) ===")
    models = [
        ("dynamic baseline", "firstDynamicBaseM150X150B060"),
        ("current Model E", "firstDynamicPrior3AgeAdjusted"),
        ("Age1 moderate", "firstDynamicPrior3AgeCurveModerate"),
        ("Age2 conservative", "firstDynamicPrior3AgeCurveConservative"),
        ("Age3 aggressive", "firstDynamicPrior3AgeCurveAggressive"),
        ("YoungA <=23 Age2", "firstYoungAUnder23Age2"),
        ("YoungB <=23 Age1", "firstYoungBUnder23Age1"),
        ("YoungC +3%", "firstYoungCUnder23Boost3"),
        ("YoungD <=24 Age2", "firstYoungDUnder24Age2"),
        ("YoungE low-prior", "firstYoungEUnder23LowPriorAge2"),
    ]
    buckets = ["<=23", "24-26", "27-29", "30-32", "33+"]
    for bucket in buckets:
        group = checkpoint_rows[checkpoint_rows["firstAgeBucket"].astype("string").eq(bucket)].copy()
        print(f"\n{bucket} | player-checkpoints {len(group)}")
        if len(group) < 20:
            print("- sample too small")
            continue
        for label, column in models:
            summary = metric_summary_from_rows_target(group, label, column, target_prefix)
            pearson = "n/a" if summary["pearson"] is None or pd.isna(summary["pearson"]) else f"{summary['pearson']:.3f}"
            lift = (
                "n/a"
                if summary["topDecileLift"] is None or pd.isna(summary["topDecileLift"])
                else f"{summary['topDecileLift'] * 100:+.1f}%"
            )
            print(f"- {label}: Pearson {pearson}, top-decile lift {lift}, n={int(summary['n'])}")


def print_no_prior_policy_impact(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== No-Prior Policy Impact ({target_prefix} HR/PA target) ===")
    no_prior = checkpoint_rows[checkpoint_rows["firstNoPriorBaselineFlag"].fillna(False)].copy()
    print(f"No-prior player-checkpoints: {len(no_prior)}")
    if no_prior.empty:
        return
    models = [
        ("Policy A current excluded", "firstDynamicPrior3AgeAdjusted"),
        ("Policy B league-average prior", "firstDynamicPrior3NoPriorLeagueFallback"),
        ("Policy C current-only", "firstDynamicPrior3NoPriorCurrentOnlyFallback"),
        ("Policy D hybrid rookie", "firstDynamicPrior3NoPriorHybridFallback"),
    ]
    for label, column in models:
        summary = metric_summary_from_rows_target(no_prior, label, column, target_prefix)
        pearson = "n/a" if summary["pearson"] is None or pd.isna(summary["pearson"]) else f"{summary['pearson']:.3f}"
        lift = (
            "n/a"
            if summary["topDecileLift"] is None or pd.isna(summary["topDecileLift"])
            else f"{summary['topDecileLift'] * 100:+.1f}%"
        )
        top25 = (
            "n/a"
            if summary["top25FutureHrPa"] is None or pd.isna(summary["top25FutureHrPa"])
            else f"{summary['top25FutureHrPa'] * 100:.2f}%"
        )
        print(f"- {label}: Pearson {pearson}, top-decile lift {lift}, top-25 HR/PA {top25}, n={int(summary['n'])}")


def print_young_player_diagnostics(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== Young-Player Adjustment Diagnostics ({target_prefix} HR/PA target) ===")
    young = checkpoint_rows[checkpoint_rows["firstAge"].le(23)].copy()
    print(f"<=23 player-checkpoints: {len(young)}")
    if young.empty:
        return
    models = [
        ("Current Model E", "firstDynamicPrior3AgeAdjusted"),
        ("YoungA <=23 Age2", "firstYoungAUnder23Age2"),
        ("YoungB <=23 Age1", "firstYoungBUnder23Age1"),
        ("YoungC +2%", "firstYoungCUnder23Boost2"),
        ("YoungC +3%", "firstYoungCUnder23Boost3"),
        ("YoungC +4%", "firstYoungCUnder23Boost4"),
        ("YoungD <=24 Age2", "firstYoungDUnder24Age2"),
        ("YoungE <=23 low-prior", "firstYoungEUnder23LowPriorAge2"),
    ]
    for label, column in models:
        summary = metric_summary_from_rows_target(young, label, column, target_prefix)
        pearson = "n/a" if summary["pearson"] is None or pd.isna(summary["pearson"]) else f"{summary['pearson']:.3f}"
        spearman = "n/a" if summary["spearman"] is None or pd.isna(summary["spearman"]) else f"{summary['spearman']:.3f}"
        lift = (
            "n/a"
            if summary["topDecileLift"] is None or pd.isna(summary["topDecileLift"])
            else f"{summary['topDecileLift'] * 100:+.1f}%"
        )
        print(f"- {label}: Pearson {pearson}, Spearman {spearman}, top-decile lift {lift}, n={int(summary['n'])}")
    for label, column in models[1:]:
        print(f"\nTop <=23 by {label}")
        top = young[~young["player"].astype(str).str.startswith("MLBAM ")].dropna(subset=[column]).sort_values(column, ascending=False).head(20)
        for rank, (_, row) in enumerate(top.iterrows(), 1):
            target_rate = row.get(f"{target_prefix}HrPerPa")
            print(
                f"{rank:2}. {row['player']} | age {row['firstAge']:.1f} | score {row[column]:.4f} | "
                f"xHR/PA {fmt_pct(row['firstAdjustedXhrPerPa'])} | Brl/PA {fmt_pct(row['firstBarrelsPerPa'])} | "
                f"target HR/PA {fmt_pct(target_rate)}"
            )
    best_column = "firstYoungAUnder23Age2"
    hits = young.dropna(subset=[best_column, f"{target_prefix}HrPerPa"]).copy()
    if not hits.empty:
        hits["youngModelResidual"] = hits[f"{target_prefix}HrPerPa"] - hits[best_column]
        print("\nBiggest <=23 hits by YoungA residual")
        for _, row in hits.sort_values("youngModelResidual", ascending=False).head(10).iterrows():
            print(f"- {row['player']}: residual {row['youngModelResidual']:+.4f}, target HR/PA {fmt_pct(row[f'{target_prefix}HrPerPa'])}")
        print("Biggest <=23 misses by YoungA residual")
        for _, row in hits.sort_values("youngModelResidual").head(10).iterrows():
            print(f"- {row['player']}: residual {row['youngModelResidual']:+.4f}, target HR/PA {fmt_pct(row[f'{target_prefix}HrPerPa'])}")


def format_summary_line(label: str, summary: dict[str, Any], total_rows: int, young_rows: int) -> str:
    pearson = "n/a" if summary["pearson"] is None or pd.isna(summary["pearson"]) else f"{summary['pearson']:.3f}"
    spearman = "n/a" if summary["spearman"] is None or pd.isna(summary["spearman"]) else f"{summary['spearman']:.3f}"
    rmse = "n/a" if summary["rmse"] is None or pd.isna(summary["rmse"]) else f"{summary['rmse']:.4f}"
    lift = (
        "n/a"
        if summary["topDecileLift"] is None or pd.isna(summary["topDecileLift"])
        else f"{summary['topDecileLift'] * 100:+.1f}%"
    )
    top25 = (
        "n/a"
        if summary["top25FutureHrPa"] is None or pd.isna(summary["top25FutureHrPa"])
        else f"{summary['top25FutureHrPa'] * 100:.2f}%"
    )
    return (
        f"- {label}: rows {total_rows}, <=23 rows {young_rows}, n={int(summary['n'])}, "
        f"Pearson {pearson}, Spearman {spearman}, RMSE {rmse}, "
        f"top-decile lift {lift}, top-25 HR/PA {top25}"
    )


def print_younge_apples_to_apples(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== YoungE Apples-to-Apples Validation ({target_prefix} HR/PA target) ===")
    target_column = f"{target_prefix}HrPerPa"
    base_rows = checkpoint_rows.dropna(subset=[target_column]).copy()
    if base_rows.empty:
        print("No target rows available.")
        return

    original_mask = base_rows["firstDynamicPrior3AgeAdjusted"].notna()
    shared_fallback_mask = (
        base_rows["firstDynamicPrior3NoPriorLeagueFallback"].notna()
        & base_rows["firstYoungEWithLeagueFallback"].notna()
    )
    modes = [
        ("A. Current Model E original behavior", base_rows, "firstDynamicPrior3AgeAdjusted"),
        ("B. Model E + league-average no-prior fallback", base_rows, "firstDynamicPrior3NoPriorLeagueFallback"),
        ("C. YoungE current behavior", base_rows, "firstYoungEUnder23LowPriorAge2"),
        ("D. YoungE on original Model E non-null rows", base_rows[original_mask].copy(), "firstYoungEUnder23LowPriorAge2"),
        ("E1. Model E, shared no-prior fallback rows", base_rows[shared_fallback_mask].copy(), "firstDynamicPrior3NoPriorLeagueFallback"),
        ("E2. YoungE, shared no-prior fallback rows", base_rows[shared_fallback_mask].copy(), "firstYoungEWithLeagueFallback"),
    ]
    for label, rows, column in modes:
        young_rows = int(rows["firstAge"].le(23).sum()) if "firstAge" in rows.columns else 0
        summary = metric_summary_from_rows_target(rows, label, column, target_prefix)
        print(format_summary_line(label, summary, len(rows), young_rows))


def print_younge_prior_bucket_diagnostics(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== YoungE <=23 Prior-Season Buckets ({target_prefix} HR/PA target) ===")
    young = checkpoint_rows[checkpoint_rows["firstAge"].le(23)].dropna(subset=[f"{target_prefix}HrPerPa"]).copy()
    if young.empty:
        print("No <=23 rows available.")
        return
    buckets = [
        ("2+ prior MLB seasons", young["firstPriorSeasonCount"].fillna(0).ge(2)),
        ("1 prior MLB season", young["firstPriorSeasonCount"].fillna(0).eq(1)),
        ("0 prior MLB seasons", young["firstPriorSeasonCount"].fillna(0).eq(0)),
    ]
    for label, mask in buckets:
        rows = young[mask].copy()
        print(f"\n{label}: rows {len(rows)}")
        if rows.empty:
            continue
        for model_label, column in [
            ("Model E", "firstDynamicPrior3AgeAdjusted"),
            ("Model E fallback", "firstDynamicPrior3NoPriorLeagueFallback"),
            ("YoungE", "firstYoungEUnder23LowPriorAge2"),
            ("YoungE shared fallback", "firstYoungEWithLeagueFallback"),
        ]:
            summary = metric_summary_from_rows_target(rows, model_label, column, target_prefix)
            print(format_summary_line(model_label, summary, len(rows), len(rows)))

        best_column = "firstYoungEWithLeagueFallback"
        residuals = rows.dropna(subset=[best_column, f"{target_prefix}HrPerPa"]).copy()
        if residuals.empty:
            continue
        residuals["residual"] = residuals[f"{target_prefix}HrPerPa"] - residuals[best_column]
        print("  Biggest hits")
        for _, row in residuals.sort_values("residual", ascending=False).head(5).iterrows():
            print(
                f"  - {row['season']} {row['checkpoint']} {row['player']}: "
                f"score {row[best_column]:.4f}, target {fmt_pct(row[f'{target_prefix}HrPerPa'])}, residual {row['residual']:+.4f}"
            )
        print("  Biggest misses")
        for _, row in residuals.sort_values("residual").head(5).iterrows():
            print(
                f"  - {row['season']} {row['checkpoint']} {row['player']}: "
                f"score {row[best_column]:.4f}, target {fmt_pct(row[f'{target_prefix}HrPerPa'])}, residual {row['residual']:+.4f}"
            )


def print_younge_contributors(checkpoint_rows: pd.DataFrame, target_prefix: str) -> None:
    print(f"\n=== YoungE Error/Ranking Contributors ({target_prefix} HR/PA target) ===")
    target_column = f"{target_prefix}HrPerPa"
    rows = checkpoint_rows.dropna(
        subset=[
            target_column,
            "firstDynamicPrior3NoPriorLeagueFallback",
            "firstYoungEWithLeagueFallback",
        ]
    ).copy()
    if rows.empty:
        print("No comparable rows available.")
        return
    rows["modelEAbsError"] = (rows["firstDynamicPrior3NoPriorLeagueFallback"] - rows[target_column]).abs()
    rows["youngEAbsError"] = (rows["firstYoungEWithLeagueFallback"] - rows[target_column]).abs()
    rows["youngEErrorImprovement"] = rows["modelEAbsError"] - rows["youngEAbsError"]
    rows["modelERank"] = rows.groupby(["season", "checkpoint"])["firstDynamicPrior3NoPriorLeagueFallback"].rank(
        ascending=False, method="min"
    )
    rows["youngERank"] = rows.groupby(["season", "checkpoint"])["firstYoungEWithLeagueFallback"].rank(ascending=False, method="min")
    rows["rankMoveUp"] = rows["modelERank"] - rows["youngERank"]
    comparable = rows[rows["firstAge"].le(23)].copy()
    print(f"Comparable <=23 rows with shared fallback: {len(comparable)}")
    print("YoungE improves absolute error most")
    for _, row in comparable.sort_values("youngEErrorImprovement", ascending=False).head(10).iterrows():
        print(
            f"- {row['season']} {row['checkpoint']} {row['player']}: "
            f"ModelE {row['firstDynamicPrior3NoPriorLeagueFallback']:.4f}, YoungE {row['firstYoungEWithLeagueFallback']:.4f}, "
            f"target {fmt_pct(row[target_column])}, error gain {row['youngEErrorImprovement']:+.4f}, rank move {row['rankMoveUp']:+.0f}"
        )
    print("YoungE hurts absolute error most")
    for _, row in comparable.sort_values("youngEErrorImprovement").head(10).iterrows():
        print(
            f"- {row['season']} {row['checkpoint']} {row['player']}: "
            f"ModelE {row['firstDynamicPrior3NoPriorLeagueFallback']:.4f}, YoungE {row['firstYoungEWithLeagueFallback']:.4f}, "
            f"target {fmt_pct(row[target_column])}, error gain {row['youngEErrorImprovement']:+.4f}, rank move {row['rankMoveUp']:+.0f}"
        )
    added = checkpoint_rows[
        checkpoint_rows["firstAge"].le(23)
        & checkpoint_rows["firstDynamicPrior3AgeAdjusted"].isna()
        & checkpoint_rows["firstYoungEUnder23LowPriorAge2"].notna()
    ].copy()
    print(f"<=23 rows added by YoungE vs original Model E: {len(added)}")
    if not added.empty:
        for _, row in added.dropna(subset=[target_column]).sort_values("firstYoungEUnder23LowPriorAge2", ascending=False).head(10).iterrows():
            prior_count = row.get("firstPriorSeasonCount")
            prior_text = "n/a" if pd.isna(prior_count) else str(int(prior_count))
            print(
                f"- {row['season']} {row['checkpoint']} {row['player']}: "
                f"YoungE {row['firstYoungEUnder23LowPriorAge2']:.4f}, target {fmt_pct(row[target_column])}, "
                f"prior seasons {prior_text}"
            )


def print_ridge_editorial_diagnostic(checkpoint_rows: pd.DataFrame, ridge_rows: pd.DataFrame | None) -> None:
    if ridge_rows is None or ridge_rows.empty:
        return
    rows_2025 = checkpoint_rows[checkpoint_rows["season"].eq(2025)].copy()
    ridge_2025 = ridge_rows[ridge_rows["season"].eq(2025)].copy()
    if rows_2025.empty or ridge_2025.empty:
        return
    final_checkpoint = rows_2025["checkpoint"].max()
    model_e = rows_2025[rows_2025["checkpoint"].eq(final_checkpoint)].copy()
    ridge = ridge_2025[ridge_2025["checkpoint"].eq(final_checkpoint)].copy()
    merged = model_e.merge(ridge[["batter", "ridgePrediction"]], on="batter", how="inner", suffixes=("", "_ridge"))
    merged = merged[~merged["player"].astype(str).str.startswith("MLBAM ")].copy()
    if merged.empty:
        return
    merged["modelERank"] = merged["firstDynamicPrior3AgeAdjusted"].rank(ascending=False, method="min")
    merged["ridgeRank"] = merged["ridgePrediction"].rank(ascending=False, method="min")
    both = merged[merged["modelERank"].le(30) & merged["ridgeRank"].le(30)].sort_values("modelERank").head(15)
    model_only = merged[merged["modelERank"].le(30) & merged["ridgeRank"].gt(30)].sort_values("modelERank").head(15)
    ridge_only = merged[merged["ridgeRank"].le(30) & merged["modelERank"].gt(30)].sort_values("ridgeRank").head(15)
    print("\n=== Ridge Editorial Diagnostic (Final 2025 Checkpoint) ===")
    print("Both Model E and Ridge like")
    for _, row in both.iterrows():
        print(f"- {row['player']}: Model E rank {int(row['modelERank'])}, Ridge rank {int(row['ridgeRank'])}")
    print("Model E likes more than Ridge")
    for _, row in model_only.iterrows():
        print(f"- {row['player']}: Model E rank {int(row['modelERank'])}, Ridge rank {int(row['ridgeRank'])}")
    print("Ridge likes more than Model E")
    for _, row in ridge_only.iterrows():
        print(f"- {row['player']}: Ridge rank {int(row['ridgeRank'])}, Model E rank {int(row['modelERank'])}")


def unresolved_name_count(rows: pd.DataFrame) -> int:
    return int(rows["player"].astype(str).str.startswith("MLBAM ").sum()) if "player" in rows.columns else 0


def print_checkpoint_top30(rows: pd.DataFrame, label: str, column: str) -> None:
    clean = rows[~rows["player"].astype(str).str.startswith("MLBAM ")].copy()
    print(f"\n=== Final 2025 Checkpoint Top 30: {label} ===")
    for rank, (_, row) in enumerate(clean.dropna(subset=[column]).sort_values(column, ascending=False).head(30).iterrows(), start=1):
        print(
            f"{rank:2}. {row['player']} | age {row['firstAge']:.1f} | "
            f"score {row[column]:.4f} | xHR/PA {fmt_pct(row['firstAdjustedXhrPerPa'])} | "
            f"Brl/PA {fmt_pct(row['firstBarrelsPerPa'])} | "
            f"3yr xHR/PA {fmt_pct(row['firstPrior3AdjustedXhrPerPa'])} | "
            f"3yr Brl/PA {fmt_pct(row['firstPrior3BarrelsPerPa'])} | "
            f"6wk future HR/PA {fmt_pct(row['futureHrPerPa'])} | "
            f"ROS future HR/PA {fmt_pct(row['restFutureHrPerPa'])}"
        )


def print_final_2025_details(
    checkpoint_rows: pd.DataFrame,
    ridge_rows: pd.DataFrame | None = None,
    best_age_curve: tuple[str, str] | None = None,
) -> None:
    rows_2025 = checkpoint_rows[checkpoint_rows["season"].eq(2025)].copy()
    if rows_2025.empty:
        print("\nNo 2025 checkpoint rows available for final top-30 output.")
        return
    final_checkpoint = rows_2025["checkpoint"].max()
    final_rows = rows_2025[rows_2025["checkpoint"].eq(final_checkpoint)].copy()
    print(f"\n=== Final 2025 Checkpoint Detail ({final_checkpoint}) ===")
    unresolved = unresolved_name_count(final_rows)
    if unresolved:
        print(f"Unresolved player names excluded from top-30 displays: {unresolved}")

    print_checkpoint_top30(final_rows, "Model E: 3-year prior + age", "firstDynamicPrior3AgeAdjusted")
    print_checkpoint_top30(final_rows, "No-prior Policy B: league-average prior fallback", "firstDynamicPrior3NoPriorLeagueFallback")
    print_checkpoint_top30(final_rows, "YoungE <=23 low-prior Age2", "firstYoungEUnder23LowPriorAge2")
    print_checkpoint_top30(final_rows, "YoungE with league-average no-prior fallback", "firstYoungEWithLeagueFallback")
    print_checkpoint_top30(final_rows, "No-prior Policy C: current-only fallback", "firstDynamicPrior3NoPriorCurrentOnlyFallback")
    print_checkpoint_top30(final_rows, "No-prior Policy D: hybrid rookie fallback", "firstDynamicPrior3NoPriorHybridFallback")
    if best_age_curve is not None:
        print_checkpoint_top30(final_rows, best_age_curve[0], best_age_curve[1])
    print_checkpoint_top30(final_rows, "dynamic reliability baseline", "firstDynamicBaseM150X150B060")

    ridge_final = pd.DataFrame()
    if ridge_rows is not None and not ridge_rows.empty:
        ridge_2025 = ridge_rows[ridge_rows["season"].eq(2025)].copy()
        if not ridge_2025.empty:
            ridge_final = ridge_2025[ridge_2025["checkpoint"].eq(final_checkpoint)].copy()
            print_checkpoint_top30(ridge_final, "ridge", "ridgePrediction")

    print("\n=== Sanity Players at Final 2025 Checkpoint ===")
    by_name = {normalize_name(row["player"]): row for _, row in final_rows.iterrows()}
    ridge_by_batter = {}
    if not ridge_final.empty:
        ridge_by_batter = {int(row["batter"]): row for _, row in ridge_final.iterrows()}
    seen: set[str] = set()
    for name in [
        "Aaron Judge",
        "Shohei Ohtani",
        "Kyle Schwarber",
        "Cal Raleigh",
        "Yordan Alvarez",
        "Yordan Álvarez",
        "James Wood",
        "Bobby Witt Jr.",
        "Isaac Paredes",
        "Ke'Bryan Hayes",
        "Nico Hoerner",
        "Junior Caminero",
        "Gunnar Henderson",
        "Jackson Merrill",
        "Julio Rodriguez",
        "Julio Rodríguez",
        "Elly De La Cruz",
        "Cam Smith",
    ]:
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        row = by_name.get(key)
        if row is None:
            print(f"{name}: not present in final 2025 checkpoint sample")
            continue
        ridge_score = ridge_by_batter.get(int(row["batter"]), {}).get("ridgePrediction") if ridge_by_batter else None
        ridge_text = "n/a" if ridge_score is None or pd.isna(ridge_score) else f"{float(ridge_score):.4f}"
        print(
            f"{row['player']}: age {row['firstAge']:.1f} | "
            f"xHR/PA {fmt_pct(row['firstAdjustedXhrPerPa'])} | "
            f"Brl/PA {fmt_pct(row['firstBarrelsPerPa'])} | "
            f"3yr xHR/PA {fmt_pct(row['firstPrior3AdjustedXhrPerPa'])} | "
            f"3yr Brl/PA {fmt_pct(row['firstPrior3BarrelsPerPa'])} | "
            f"Model E {row['firstDynamicPrior3AgeAdjusted']:.4f} | "
            f"PolicyB {row.get('firstDynamicPrior3NoPriorLeagueFallback', float('nan')):.4f} | "
            f"PolicyC {row.get('firstDynamicPrior3NoPriorCurrentOnlyFallback', float('nan')):.4f} | "
            f"PolicyD {row.get('firstDynamicPrior3NoPriorHybridFallback', float('nan')):.4f} | "
            f"YoungE {row.get('firstYoungEUnder23LowPriorAge2', float('nan')):.4f} | "
            f"YoungE fallback {row.get('firstYoungEWithLeagueFallback', float('nan')):.4f} | "
            f"Age1 {row.get('firstDynamicPrior3AgeCurveModerate', float('nan')):.4f} | "
            f"dynamic {row['firstDynamicBaseM150X150B060']:.4f} | "
            f"ridge {ridge_text} | "
            f"6wk future HR/PA {fmt_pct(row['futureHrPerPa'])} | "
            f"ROS future HR/PA {fmt_pct(row['restFutureHrPerPa'])}"
        )


def print_final_validation_interpretation(six_week: pd.DataFrame, rest_of_season: pd.DataFrame) -> None:
    six = summarize_validation(six_week).set_index("metric")
    rest = summarize_validation(rest_of_season).set_index("metric")

    def get(frame: pd.DataFrame, metric: str, column: str) -> float:
        return float(frame.loc[metric, column]) if metric in frame.index and pd.notna(frame.loc[metric, column]) else float("nan")

    model_e_six = get(six, "Model E: 3-year prior + age", "avgPearson")
    dynamic_six = get(six, "dynamic reliability baseline", "avgPearson")
    model_e_rest = get(rest, "Model E: 3-year prior + age", "avgPearson")
    dynamic_rest = get(rest, "dynamic reliability baseline", "avgPearson")
    ridge_six = get(six, "ridge_model_if_available", "avgPearson")
    ridge_rest = get(rest, "ridge_model_if_available", "avgPearson")
    age_curve_metrics = [
        "Age1 moderate age-adjusted priors",
        "Age2 conservative age-adjusted priors",
        "Age3 aggressive age-adjusted priors",
    ]
    best_age_metric = max(age_curve_metrics, key=lambda metric: get(six, metric, "avgPearson"))
    best_age_six = get(six, best_age_metric, "avgPearson")
    best_age_rest = get(rest, best_age_metric, "avgPearson")

    print("\n=== Final Validation Recommendation ===")
    print(f"Six-week: Model E {model_e_six:.3f} vs dynamic baseline {dynamic_six:.3f} vs ridge {ridge_six:.3f}.")
    print(f"Rest-of-season: Model E {model_e_rest:.3f} vs dynamic baseline {dynamic_rest:.3f} vs ridge {ridge_rest:.3f}.")
    print(f"Best explicit age-curve variant: {best_age_metric} ({best_age_six:.3f} six-week, {best_age_rest:.3f} rest-of-season).")
    clears_055 = model_e_six >= 0.55 or model_e_rest >= 0.55
    if clears_055:
        print("Model E clears 0.55 Pearson on at least one target.")
    else:
        print("Model E does not clear 0.55 Pearson on either target.")
    if model_e_six > dynamic_six and model_e_rest > dynamic_rest:
        print("Model E remains better than the dynamic baseline on both target windows.")
    else:
        print("Model E does not beat the dynamic baseline on both target windows.")
    if best_age_six > model_e_six + 0.005:
        print("Explicit age curve meaningfully improves six-week Pearson over current Model E.")
    elif best_age_six > model_e_six:
        print("Explicit age curve improves six-week Pearson only marginally over current Model E.")
    else:
        print("Explicit age curve does not improve six-week Pearson over current Model E.")
    if model_e_rest >= model_e_six - 0.01:
        print("Rest-of-season validation supports the six-week result.")
    else:
        print("Rest-of-season validation weakens the six-week result.")

    if model_e_six > dynamic_six and model_e_rest > dynamic_rest and (clears_055 or model_e_rest >= 0.535):
        print("Recommendation: B. prepare Longball Threat beta, but keep it clearly labeled as beta.")
    elif model_e_six > dynamic_six or model_e_rest > dynamic_rest:
        print("Recommendation: C. continue diagnostics before publishing.")
    else:
        print("Recommendation: A. keep Longball Threat internal.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prototype Longball Threat v0.2 without publishing it.")
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--seasons", nargs="+", type=int, help="Run backtests for multiple seasons.")
    parser.add_argument("--lbi-json", type=Path)
    parser.add_argument("--checkpoints", nargs="+", help="Checkpoint dates in YYYY-MM-DD format.")
    parser.add_argument("--next-weeks", type=int, default=DEFAULT_NEXT_WEEKS)
    parser.add_argument("--min-pa", type=int, default=75)
    parser.add_argument("--min-bbe", type=int, default=40)
    parser.add_argument("--backtest-min-first-pa", type=int, default=100)
    parser.add_argument("--backtest-min-future-pa", type=int, default=75)
    parser.add_argument("--backtest-min-first-bbe", type=int, default=50)
    return parser.parse_args()


def load_season_context(season: int, lbi_json: Path | None = None) -> tuple[pd.DataFrame, dict[int, str], pd.DataFrame, pd.DataFrame, Path, str, str]:
    lbi_path = lbi_json or season_lbi_path(season)
    players, names = load_lbi_players(lbi_path)
    pitch_paths = pitch_cache_paths(season)
    pitches, pitch_note = load_pitch_frames(pitch_paths)
    details = load_hrt_details(hrt_detail_path(season))
    return players, names, pitches, details, lbi_path, pitch_note, str(hrt_detail_path(season))


def run_season(args: argparse.Namespace, season: int, print_details: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    players, names, pitches, details, lbi_path, pitch_note, hrt_note = load_season_context(
        season,
        args.lbi_json if season == args.season else None,
    )
    season_start = min(pitches["game_date"])
    season_end = max(pitches["game_date"])
    prior_rates = load_prior_season_rates(season)
    multi_prior_rates = load_multi_year_prior_rates(season)
    player_ids = set(int(value) for value in players["batter"].dropna().astype(int).tolist())
    age_lookup = ensure_age_cache(player_ids)
    full = calculate_full_season(
        players=players,
        pitches=pitches,
        details=details,
        season=season,
        min_pa=args.min_pa,
        min_bbe=args.min_bbe,
    )

    checkpoints = [parse_date(value) for value in args.checkpoints] if args.checkpoints else default_checkpoints_for_season(season)
    backtests = [
        prepare_checkpoint(
            pitches=pitches,
            details=details,
            names=names,
            players=players,
            prior_rates=prior_rates,
            multi_prior_rates=multi_prior_rates,
            age_lookup=age_lookup,
            season_start=season_start,
            checkpoint=checkpoint,
            next_weeks=args.next_weeks,
            min_first_pa=args.backtest_min_first_pa,
            min_future_pa=args.backtest_min_future_pa,
            min_first_bbe=args.backtest_min_first_bbe,
        )
        for checkpoint in checkpoints
    ]
    if print_details:
        print("=== Longball Threat v0.2 Diagnostic ===")
        print("Goal: canonical predictive HR/PA benchmark before testing more formulas.")
        print("Canonical harness: monthly checkpoints May 1, June 1, July 1, August 1; future window 6 weeks.")
        print("Target: future actual HR/PA.")
        print(
            "Eligibility: "
            f"first-window PA >= {args.backtest_min_first_pa}, "
            f"future-window PA >= {args.backtest_min_future_pa}, "
            f"first-window BBE >= {args.backtest_min_first_bbe}."
        )
        print("Stable model labels: barrel_pa, hrt_event_ct30_proxy_pa, threat_c_raw_75_xhr_25_barrel,")
        print("prior_stabilized_current_prior_xhr_barrel, contact_xiso_proxy, pull_air_ev_interaction.")
        print("Contact xISO proxy = mean(estimated_slg_using_speedangle) - mean(estimated_ba_using_speedangle) on BBE.")
        print("Air BBE = launch angle 15-45 degrees. Hard-hit = launch_speed >= 95 mph.")
        print("Pull classification uses batter handedness and Statcast hc_x: RHH pull to lower hc_x, LHH pull to higher hc_x.")
        print("Scale: 100 = league-average qualified hitter; 90th percentile component score ~= 150; scores uncapped.")
        print(f"Season: {season}")
        print(f"LBI JSON: {lbi_path}")
        print(f"Pitch cache: {pitch_note}")
        print(f"Date range in pitch cache: {season_start} through {season_end}")
        print(f"Home Run Tracker details: {hrt_note}")
        print("Expected stats source: contact xISO/xSLG calculated mechanically from Statcast estimated_ba/estimated_slg on BBE.")
        print(
            "Age source: "
            + (
                "data/cache/longball-threat-backtest/player-people-cache.json"
                if age_lookup
                else "unavailable; age-adjusted diagnostic models will have no valid rows"
            )
        )
        print(f"Full-season eligibility: PA >= {args.min_pa}, BBE >= {args.min_bbe}")
        print(f"Qualified players: {len(full)} of {len(players)} LBI players")
        print(
            "Distribution: "
            f"plusC median={full['threat_c_plus_scaled_75_xhr_25_barrel'].median():.1f}, "
            f"mean={full['threat_c_plus_scaled_75_xhr_25_barrel'].mean():.1f}, "
            f"max={full['threat_c_plus_scaled_75_xhr_25_barrel'].max():.1f}, "
            f"min={full['threat_c_plus_scaled_75_xhr_25_barrel'].min():.1f}"
        )

        for variant_key in THREAT_VARIANTS:
            print_top_threat(full, 30, variant_key)
        print_sanity(full)
        print_rank_gaps(full)

    print_xhr_source_diagnostics(backtests, season)
    print_age_prior_diagnostics(backtests, season)
    table = print_backtest(backtests, season)
    if print_details:
        threat_rows = table[table["metric"].astype(str).str.startswith("Threat ")].dropna(subset=["pearson"])
        if threat_rows.empty:
            threat_rows = table[
                table["metric"].astype(str).str.startswith(("Baseline C", "Candidate "))
            ].dropna(subset=["pearson"])
        best_metric = threat_rows.sort_values("pearson", ascending=False).iloc[0]["metric"] if not threat_rows.empty else "Baseline C"
        best_variant_key = next((key for key in THREAT_VARIANTS if f"{key}:" in best_metric or f"{key} " in best_metric), "C")
        if best_variant_key in THREAT_VARIANTS:
            print_top_threat(full, 20, best_variant_key)
        print_sanity(full)

    print("\n=== Publication Gate ===")
    print("Do not publish Longball Threat unless it beats or clearly complements Barrel/PA in broader backtests.")
    return full, table.assign(season=season), pd.concat(
        [checkpoint.rows.assign(checkpoint=checkpoint.checkpoint, season=season) for checkpoint in backtests],
        ignore_index=True,
    )


def print_multi_season_summary(tables: list[pd.DataFrame]) -> None:
    combined = pd.concat(tables, ignore_index=True)
    print("\n=== Multi-Season Aggregate Summary ===")
    summary = (
        combined.groupby("metric", as_index=False)
        .agg(
            avgPearson=("pearson", "mean"),
            avgSpearman=("spearman", "mean"),
            avgTopDecileLift=("topDecileLift", "mean"),
            avgTop25FutureHrPa=("top25FutureHrPa", "mean"),
            seasons=("season", "nunique"),
        )
        .sort_values("avgPearson", ascending=False)
    )
    for _, row in summary.iterrows():
        print(
            f"- {row['metric']}: avg Pearson {row['avgPearson']:.3f}, "
            f"avg Spearman {row['avgSpearman']:.3f}, "
            f"avg top-decile lift {row['avgTopDecileLift'] * 100:+.1f}%, "
            f"avg top-25 HR/PA {row['avgTop25FutureHrPa'] * 100:.2f}%, "
            f"seasons {int(row['seasons'])}"
        )

    wins = []
    for season, season_table in combined.dropna(subset=["pearson"]).groupby("season"):
        winner = season_table.sort_values("pearson", ascending=False).iloc[0]
        wins.append((season, winner["metric"], winner["pearson"]))
    print("\nSeason winners")
    for season, metric, pearson in wins:
        print(f"- {season}: {metric} ({pearson:.3f})")

    threat_metrics = [
        metric
        for metric in combined["metric"].unique()
        if str(metric).startswith("Baseline C") or str(metric).startswith("Candidate ")
    ]
    threat_wins = {metric: sum(winner == metric for _, winner, _ in wins) for metric in threat_metrics}
    print("\nBaseline/Candidate wins")
    for metric, count in sorted(threat_wins.items()):
        print(f"- {metric}: {count}")

    mean_lookup = summary.set_index("metric")["avgPearson"].to_dict()
    print("\nInterpretation")
    barrel = mean_lookup.get("Baseline A: Barrel/PA", float("nan"))
    if pd.isna(barrel):
        barrel = mean_lookup.get("barrel_pa", float("nan"))
    xhr = mean_lookup.get("hrt_event_ct30_proxy_pa", float("nan"))
    threat_c = mean_lookup.get("threat_c_raw_75_xhr_25_barrel", float("nan"))
    best_row = summary.sort_values("avgPearson", ascending=False).iloc[0]
    print(
        f"Canonical raw baselines: barrel_pa {barrel:.3f}, hrt_event_ct30_proxy_pa {xhr:.3f}, "
        f"threat_c_raw_75_xhr_25_barrel {threat_c:.3f}."
    )
    print(
        f"Best average Pearson: {best_row['metric']} at {best_row['avgPearson']:.3f}; "
        f"top-decile lift {best_row['avgTopDecileLift'] * 100:+.1f}%."
    )
    publishable = (
        pd.notna(best_row["avgPearson"])
        and pd.notna(barrel)
        and pd.notna(threat_c)
        and best_row["avgPearson"] >= barrel + 0.015
        and best_row["avgPearson"] >= threat_c - 0.001
        and threat_wins.get(best_row["metric"], 0) >= 3
    )
    if publishable:
        print("Publication gate: candidate clears the rough diagnostic threshold, pending baseball smell test.")
    else:
        print(
            "Publication gate: do not publish yet unless top-decile lift or later tests make the case stronger. "
            "Require ~0.015 avg Pearson over Barrel/PA, tying/beating Threat C in most seasons, and no one-season fluke."
        )

    print("\nRECONCILIATION")
    print("Prior reported Threat C: 0.535.")
    print(f"Current canonical raw Threat C avg Pearson: {threat_c:.3f}.")
    print(f"Current canonical plus-scaled Threat C avg Pearson: {mean_lookup.get('threat_c_plus_scaled_75_xhr_25_barrel', float('nan')):.3f}.")
    print("Current All-Star split check from scripts/backtest_longball_threat.py should be treated as an alternate harness.")
    print("Likely reason prior value differed: transient/non-canonical harness plus raw-vs-plus scaling and split/window differences.")


def main() -> None:
    args = parse_args()
    seasons = args.seasons or [args.season]
    if args.lbi_json and len(seasons) > 1:
        raise RuntimeError("--lbi-json can only be used with a single --season run.")

    tables: list[pd.DataFrame] = []
    checkpoint_rows: list[pd.DataFrame] = []
    for index, season in enumerate(seasons):
        _, table, rows = run_season(args, season, print_details=(len(seasons) == 1))
        tables.append(table)
        checkpoint_rows.append(rows)
        if len(seasons) > 1:
            best = table.dropna(subset=["pearson"]).sort_values("pearson", ascending=False).iloc[0]
            print(f"{season}: best {best['metric']} Pearson {best['pearson']:.3f}, Spearman {best['spearman']:.3f}")

    if len(seasons) > 1:
        all_checkpoint_rows = pd.concat(checkpoint_rows, ignore_index=True)
        dynamic = dynamic_threat_grid_evaluation(all_checkpoint_rows)
        dynamic_summary = print_dynamic_grid(dynamic)
        if not dynamic_summary.empty:
            best_dynamic_metric = dynamic_summary.sort_values("avgPearson", ascending=False).iloc[0]["metric"]
            best_dynamic_rows = dynamic[dynamic["metric"].eq(best_dynamic_metric)].copy()
            best_dynamic_rows["metric"] = "dynamic_reliability_best_pearson"
            tables.append(best_dynamic_rows)
        ridge = ridge_evaluation(all_checkpoint_rows)
        if not ridge.empty:
            print("\n=== Candidate G Ridge Model, Leave-One-Season-Out ===")
            for _, row in ridge.sort_values("season").iterrows():
                pearson = "n/a" if pd.isna(row["pearson"]) else f"{row['pearson']:.3f}"
                spearman = "n/a" if pd.isna(row["spearman"]) else f"{row['spearman']:.3f}"
                lift = "n/a" if pd.isna(row["topDecileLift"]) else f"{row['topDecileLift'] * 100:+.1f}%"
                print(
                    f"{int(row['season'])}: Pearson {pearson}, Spearman {spearman}, "
                    f"top-decile lift {lift}, n={int(row['n'])}"
                )
            tables.append(ridge)
        ridge_six_week_rows = ridge_scored_rows(all_checkpoint_rows, "future")
        ridge_rest_rows = ridge_scored_rows(all_checkpoint_rows, "restFuture")
        six_week_validation = validation_table(all_checkpoint_rows, "future", ridge_six_week_rows)
        rest_validation = validation_table(all_checkpoint_rows, "restFuture", ridge_rest_rows)
        print_validation_report(six_week_validation, "Canonical six-week future HR/PA")
        print_validation_report(rest_validation, "Rest-of-season future HR/PA")
        print_pull_air_juice_definition_report(all_checkpoint_rows)
        print_blast_pa_modern_era_report(all_checkpoint_rows)
        six_summary = summarize_validation(six_week_validation).set_index("metric")
        best_age_curve_metric = None
        best_age_curve_column = None
        age_curve_columns = {
            "Age1 moderate age-adjusted priors": "firstDynamicPrior3AgeCurveModerate",
            "Age2 conservative age-adjusted priors": "firstDynamicPrior3AgeCurveConservative",
            "Age3 aggressive age-adjusted priors": "firstDynamicPrior3AgeCurveAggressive",
        }
        available_age_curves = six_summary.loc[six_summary.index.intersection(age_curve_columns.keys())]
        if not available_age_curves.empty:
            best_age_curve_metric = str(available_age_curves.sort_values("avgPearson", ascending=False).index[0])
            best_age_curve_column = age_curve_columns[best_age_curve_metric]
        print_prior_and_age_policy_audit(all_checkpoint_rows)
        print_no_prior_policy_impact(all_checkpoint_rows, "future")
        print_no_prior_policy_impact(all_checkpoint_rows, "restFuture")
        print_age_bucket_validation(all_checkpoint_rows, "future")
        print_age_bucket_validation(all_checkpoint_rows, "restFuture")
        print_young_player_diagnostics(all_checkpoint_rows, "future")
        print_young_player_diagnostics(all_checkpoint_rows, "restFuture")
        print_younge_apples_to_apples(all_checkpoint_rows, "future")
        print_younge_apples_to_apples(all_checkpoint_rows, "restFuture")
        print_younge_prior_bucket_diagnostics(all_checkpoint_rows, "future")
        print_younge_prior_bucket_diagnostics(all_checkpoint_rows, "restFuture")
        print_younge_contributors(all_checkpoint_rows, "future")
        print_younge_contributors(all_checkpoint_rows, "restFuture")
        print_ridge_editorial_diagnostic(all_checkpoint_rows, ridge_six_week_rows)
        print_final_2025_details(
            all_checkpoint_rows,
            ridge_six_week_rows,
            (best_age_curve_metric, best_age_curve_column) if best_age_curve_metric and best_age_curve_column else None,
        )
        print_final_validation_interpretation(six_week_validation, rest_validation)
        print_multi_season_summary(tables)


if __name__ == "__main__":
    main()
