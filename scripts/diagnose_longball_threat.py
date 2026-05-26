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

Current best diagnostic candidate:
``prior_stabilized_current_prior_xhr_barrel``.
"""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

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
    "firstHardHitAirBbePerPa",
    "firstHardHitPulledAirBbePerPa",
    "firstEv90",
    "firstPullAirEvInteraction",
    "firstLbiProxy",
    "firstContactXisoProxy",
]


@dataclass(frozen=True)
class BacktestCheckpoint:
    checkpoint: date
    period_end: date
    rows: pd.DataFrame


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
    bbe["barrelDistance"] = bbe["hit_distance_sc"].where(bbe["isBarrel"])
    bbe["estimatedBa"] = to_numeric(bbe.get("estimated_ba_using_speedangle", pd.Series(index=bbe.index, dtype="float64")))
    bbe["estimatedSlg"] = to_numeric(bbe.get("estimated_slg_using_speedangle", pd.Series(index=bbe.index, dtype="float64")))
    stats = (
        bbe.groupby("batter", as_index=False)
        .agg(
            bbe=("batter", "size"),
            hr=("isHr", "sum"),
            barrels=("isBarrel", "sum"),
            hardHitBbe=("isHardHit", "sum"),
            hardHitAirBbe=("isHardHitAir", "sum"),
            pulledAirBbe=("isPulledAir", "sum"),
            pulledHardHitAirBbe=("isPulledHardHitAir", "sum"),
            hardHitPulledAirBbe=("isHardHitPulledAir", "sum"),
            ev90=("launch_speed", lambda values: values.dropna().quantile(0.90) if values.notna().any() else pd.NA),
            maxEv=("launch_speed", "max"),
            avgDistanceOnBarrels=("barrelDistance", "mean"),
            contactXba=("estimatedBa", "mean"),
            contactXslg=("estimatedSlg", "mean"),
        )
        .rename(
            columns={
                "bbe": f"{prefix}Bbe",
                "hr": f"{prefix}Hr",
                "barrels": f"{prefix}Barrels",
                "hardHitBbe": f"{prefix}HardHitBbe",
                "hardHitAirBbe": f"{prefix}HardHitAirBbe",
                "pulledAirBbe": f"{prefix}PulledAirBbe",
                "pulledHardHitAirBbe": f"{prefix}PulledHardHitAirBbe",
                "hardHitPulledAirBbe": f"{prefix}HardHitPulledAirBbe",
                "ev90": f"{prefix}Ev90",
                "maxEv": f"{prefix}MaxEv",
                "avgDistanceOnBarrels": f"{prefix}AvgDistanceOnBarrels",
                "contactXba": f"{prefix}ContactXba",
                "contactXslg": f"{prefix}ContactXslg",
            }
        )
    )
    merged = pa.merge(stats, on="batter", how="outer").fillna(0)
    for column in [
        f"{prefix}Bbe",
        f"{prefix}Hr",
        f"{prefix}Barrels",
        f"{prefix}HardHitBbe",
        f"{prefix}HardHitAirBbe",
        f"{prefix}PulledAirBbe",
        f"{prefix}PulledHardHitAirBbe",
        f"{prefix}HardHitPulledAirBbe",
        f"{prefix}Ev90",
        f"{prefix}MaxEv",
        f"{prefix}AvgDistanceOnBarrels",
        f"{prefix}ContactXba",
        f"{prefix}ContactXslg",
    ]:
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
    frame[f"{prefix}ActualHrPerPa"] = frame[f"{prefix}Hr"] / pa
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
    frame[f"{prefix}PullAirEvInteraction"] = frame[f"{prefix}HardHitPulledAirBbePerPa"] * (frame[f"{prefix}Ev90"] / 100)
    frame[f"{prefix}RawThreatC"] = 0.75 * frame[f"{prefix}AdjustedXhrPerPa"] + 0.25 * frame[f"{prefix}BarrelsPerPa"]
    frame[f"{prefix}ContactXisoProxy"] = to_numeric(frame[f"{prefix}ContactXisoProxy"])
    return frame


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
        "Ev90",
        "MaxEv",
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
    season_start: date,
    checkpoint: date,
    next_weeks: int,
    min_first_pa: int,
    min_future_pa: int,
    min_first_bbe: int,
) -> BacktestCheckpoint:
    period_start = checkpoint + timedelta(days=1)
    period_end = checkpoint + timedelta(weeks=next_weeks)
    first = pitch_window_stats(pitches, season_start, checkpoint, "first")
    future = pitch_window_stats(pitches, period_start, period_end, "future")
    xhr = adjusted_xhr(details, season_start, checkpoint, "first")
    rows = first.merge(xhr, on="batter", how="left").merge(
        future[["batter", "futurePa", "futureBbe", "futureHr"]],
        on="batter",
        how="left",
    )
    rows = rows.merge(aggregate_xhr_frame(players, "first"), on="batter", how="left")
    if not prior_rates.empty:
        rows = rows.merge(prior_rates, on="batter", how="left")
    else:
        rows["priorAdjustedXhrPerPa"] = pd.NA
        rows["priorBarrelsPerPa"] = pd.NA
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
        "firstEv90",
        "firstMaxEv",
        "firstAdjustedXhr",
        "firstHrtAggregateAdjustedXhr",
        "futurePa",
        "futureBbe",
        "futureHr",
    ]:
        if column not in rows.columns:
            rows[column] = 0
        rows[column] = to_numeric(rows[column]).fillna(0)
    rows = add_rate_columns(rows, "first")
    rows["firstPriorAdjustedXhrPerPa"] = to_numeric(rows["priorAdjustedXhrPerPa"])
    rows["firstPriorBarrelsPerPa"] = to_numeric(rows["priorBarrelsPerPa"])
    rows["firstPriorStabilized"] = (
        0.55 * rows["firstAdjustedXhrPerPa"]
        + 0.20 * rows["firstBarrelsPerPa"]
        + 0.15 * rows["firstPriorAdjustedXhrPerPa"]
        + 0.10 * rows["firstPriorBarrelsPerPa"]
    )
    rows["futureHrPerPa"] = rows["futureHr"] / rows["futurePa"].where(rows["futurePa"].gt(0))
    rows["futureHrPerBbe"] = rows["futureHr"] / rows["futureBbe"].where(rows["futureBbe"].gt(0))
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


def metric_summary_from_rows(rows: pd.DataFrame, metric_label: str, column: str) -> dict[str, Any]:
    sample = rows[[column, "futureHrPerPa"]].dropna()
    all_future_rate = rows["futureHr"].sum() / rows["futurePa"].sum() if rows["futurePa"].sum() else None
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
    return {
        "metric": metric_label,
        "n": len(sample),
        "pearson": pearson,
        "spearman": spearman,
        "topDecileFutureHrPa": top_decile_rate,
        "topDecileLift": top_decile_lift,
        "top25FutureHrPa": top25_rate,
    }


def ridge_evaluation(checkpoint_rows: pd.DataFrame) -> pd.DataFrame:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import RidgeCV
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        print(f"\nCandidate G ridge model skipped: sklearn unavailable ({exc}).")
        return pd.DataFrame()

    rows = checkpoint_rows.copy()
    for column in RIDGE_FEATURE_COLUMNS + ["futureHrPerPa"]:
        if column not in rows.columns:
            rows[column] = pd.NA
        rows[column] = to_numeric(rows[column])

    predictions: list[pd.DataFrame] = []
    for season in sorted(rows["season"].dropna().unique()):
        train = rows[rows["season"].ne(season)].dropna(subset=["futureHrPerPa"])
        test = rows[rows["season"].eq(season)].dropna(subset=["futureHrPerPa"])
        if len(train) < 50 or len(test) < 10:
            continue
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            RidgeCV(alphas=[0.01, 0.1, 1.0, 3.0, 10.0, 30.0]),
        )
        model.fit(train[RIDGE_FEATURE_COLUMNS], train["futureHrPerPa"])
        scored = test.copy()
        scored["ridgePrediction"] = model.predict(test[RIDGE_FEATURE_COLUMNS])
        predictions.append(scored)

    if not predictions:
        return pd.DataFrame()

    scored_rows = pd.concat(predictions, ignore_index=True)
    output = []
    for season, season_rows in scored_rows.groupby("season"):
        summary = metric_summary_from_rows(season_rows, "Candidate G: ridge model", "ridgePrediction")
        summary["season"] = season
        output.append(summary)
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
    for category in ["RAW PREDICTIVE RESULTS", "PLUS-SCALED DISPLAY RESULTS"]:
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
        ridge = ridge_evaluation(pd.concat(checkpoint_rows, ignore_index=True))
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
        print_multi_season_summary(tables)


if __name__ == "__main__":
    main()
