#!/usr/bin/env python3
"""Prototype Longball Threat, a predictive park-neutral HR/PA diagnostic.

This script is internal tooling only. It does not write frontend data, alter
the public Longball Index, or publish Longball Threat. The goal is to test
whether a PA-level predictive stat meaningfully beats or complements simpler
inputs, especially Barrel/PA.
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
    "A": {
        "label": "Variant A: no LBI baseline",
        "scoreColumn": "longballThreatA",
        "rankColumn": "threatRankA",
        "weights": {
            "barrelsPerPa": 0.40,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "expectedPowerQuality": 0.10,
        },
    },
    "B": {
        "label": "Variant B: LBI as Expected Power Quality",
        "scoreColumn": "longballThreatB",
        "rankColumn": "threatRankB",
        "weights": {
            "barrelsPerPa": 0.40,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "lbiQuality": 0.10,
        },
    },
    "C": {
        "label": "Variant C: slightly more LBI",
        "scoreColumn": "longballThreatC",
        "rankColumn": "threatRankC",
        "weights": {
            "barrelsPerPa": 0.35,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "lbiQuality": 0.15,
        },
    },
    "D": {
        "label": "Variant D: contact xISO proxy",
        "scoreColumn": "longballThreatD",
        "rankColumn": "threatRankD",
        "weights": {
            "barrelsPerPa": 0.40,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "contactXisoProxy": 0.10,
        },
    },
    "E": {
        "label": "Variant E: contact xSLG",
        "scoreColumn": "longballThreatE",
        "rankColumn": "threatRankE",
        "weights": {
            "barrelsPerPa": 0.40,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "contactXslg": 0.10,
        },
    },
    "F": {
        "label": "Variant F: split LBI/contact xISO",
        "scoreColumn": "longballThreatF",
        "rankColumn": "threatRankF",
        "weights": {
            "barrelsPerPa": 0.40,
            "adjustedXhrPerPa": 0.35,
            "hardHitAirBbePerPa": 0.15,
            "lbiQuality": 0.05,
            "contactXisoProxy": 0.05,
        },
    },
}

LBI_PROXY_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "avgDistanceOnBarrels": 0.125,
    "hardHitRate": 0.075,
}


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
    bbe["isHardHitAir"] = bbe["launch_speed"].ge(95) & bbe["launch_angle"].between(15, 40, inclusive="both")
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
    frame[f"{prefix}BarrelsPerPa"] = frame[f"{prefix}Barrels"] / pa
    frame[f"{prefix}HardHitAirBbePerPa"] = frame[f"{prefix}HardHitAirBbe"] / pa
    frame[f"{prefix}ActualHrPerPa"] = frame[f"{prefix}Hr"] / pa
    frame[f"{prefix}XhrPerBbe"] = frame[f"{prefix}AdjustedXhr"] / bbe
    frame[f"{prefix}BarrelRate"] = frame[f"{prefix}Barrels"] / bbe
    frame[f"{prefix}HardHitRate"] = frame[f"{prefix}HardHitBbe"] / bbe
    frame[f"{prefix}ExpectedPowerQuality"] = frame[f"{prefix}AvgDistanceOnBarrels"]
    frame[f"{prefix}ContactXba"] = to_numeric(frame.get(f"{prefix}ContactXba", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}ContactXslg"] = to_numeric(frame.get(f"{prefix}ContactXslg", pd.Series(index=frame.index, dtype="float64")))
    frame[f"{prefix}ContactXisoProxy"] = frame[f"{prefix}ContactXslg"] - frame[f"{prefix}ContactXba"]
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
    for column in ["Pa", "Bbe", "Hr", "Barrels", "HardHitBbe", "HardHitAirBbe", "AdjustedXhr"]:
        frame[column] = to_numeric(frame[column]).fillna(0)
    frame = add_rate_columns(frame, "")

    qualified = frame[frame["Pa"].ge(min_pa) & frame["Bbe"].ge(min_bbe)].copy()
    qualified = add_threat_variants(qualified, "")
    qualified["longballThreat"] = qualified["longballThreatA"]
    qualified["lbiRank"] = qualified["longballIndex"].rank(method="first", ascending=False).astype(int)
    for variant in THREAT_VARIANTS.values():
        qualified[variant["rankColumn"]] = qualified[variant["scoreColumn"]].rank(method="first", ascending=False).astype(int)
    qualified = qualified.sort_values(["longballThreatA", "AdjustedXhrPerPa"], ascending=[False, False])
    qualified["threatRank"] = qualified["threatRankA"]
    qualified["rankDeltaThreatMinusLbi"] = qualified["threatRankA"] - qualified["lbiRank"]

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
    for column in [
        "firstPa",
        "firstBbe",
        "firstHr",
        "firstBarrels",
        "firstHardHitBbe",
        "firstHardHitAirBbe",
        "firstAdjustedXhr",
        "futurePa",
        "futureBbe",
        "futureHr",
    ]:
        rows[column] = to_numeric(rows[column]).fillna(0)
    rows = add_rate_columns(rows, "first")
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
    qualified["longballThreat"] = qualified["longballThreatA"]
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
            f"HH Air/PA {fmt_pct(row['HardHitAirBbePerPa'])} | cXISO {row['ContactXisoProxy']:.3f} | LBI {row['longballIndex']:.1f}"
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
            f"A {row['longballThreatA']:.1f} | B {row['longballThreatB']:.1f} | C {row['longballThreatC']:.1f} | "
            f"D {row['longballThreatD']:.1f} | E {row['longballThreatE']:.1f} | F {row['longballThreatF']:.1f} | "
            f"HR/600 {row['projectedHrPer600']:.1f} | LBI {row['longballIndex']:.1f}"
        )
        print(
            f"  Brl/PA {fmt_pct(row['BarrelsPerPa'])} | xHR/PA {fmt_pct(row['AdjustedXhrPerPa'])} | "
            f"HH Air/PA {fmt_pct(row['HardHitAirBbePerPa'])} | cXISO {row['ContactXisoProxy']:.3f} | cXSLG {row['ContactXslg']:.3f} | "
            f"Expected quality {row['ExpectedPowerQuality']}"
        )


def print_rank_gaps(rows: pd.DataFrame) -> None:
    print("\n=== Much Higher in Threat A than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi").head(12).iterrows():
        print(
            f"{row['player']} ({row.get('team', '---')}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta {int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT A {row['longballThreatA']:.1f}, LBI {row['longballIndex']:.1f}"
        )

    print("\n=== Much Lower in Threat A than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi", ascending=False).head(12).iterrows():
        print(
            f"{row['player']} ({row.get('team', '---')}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta +{int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT A {row['longballThreatA']:.1f}, LBI {row['longballIndex']:.1f}"
        )


def correlation_table(checkpoints: list[BacktestCheckpoint]) -> pd.DataFrame:
    rows = pd.concat([checkpoint.rows.assign(checkpoint=checkpoint.checkpoint) for checkpoint in checkpoints], ignore_index=True)
    metric_columns = {
        "Threat A no LBI": "longballThreatA",
        "Threat B LBI 10%": "longballThreatB",
        "Threat C LBI 15%": "longballThreatC",
        "Threat D contact xISO": "longballThreatD",
        "Threat E contact xSLG": "longballThreatE",
        "Threat F LBI/contact xISO": "longballThreatF",
        "Barrel/PA": "firstBarrelsPerPa",
        "Adjusted xHR/PA": "firstAdjustedXhrPerPa",
        "Actual HR/PA to date": "firstActualHrPerPa",
        "LBI proxy": "firstLbiProxy",
        "Hard-Hit Air/PA": "firstHardHitAirBbePerPa",
        "Avg Barrel Distance": "firstExpectedPowerQuality",
        "Contact xISO proxy": "firstContactXisoProxy",
        "Contact xSLG": "firstContactXslg",
    }
    output = []
    for label, column in metric_columns.items():
        sample = rows[[column, "futureHrPerPa"]].dropna()
        if len(sample) < 3:
            pearson = None
            spearman = None
        else:
            pearson = sample[column].corr(sample["futureHrPerPa"], method="pearson")
            spearman = sample[column].corr(sample["futureHrPerPa"], method="spearman")
        output.append(
            {
                "metric": label,
                "n": len(sample),
                "pearson": pearson,
                "spearman": spearman,
            }
        )
    return pd.DataFrame(output).sort_values("pearson", ascending=False)


def print_backtest(checkpoints: list[BacktestCheckpoint], season: int) -> pd.DataFrame:
    print(f"\n=== {season} Monthly Checkpoint Backtest ===")
    for checkpoint in checkpoints:
        rate = checkpoint.rows["futureHr"].sum() / checkpoint.rows["futurePa"].sum()
        print(
            f"{checkpoint.checkpoint} -> {checkpoint.period_end}: "
            f"{len(checkpoint.rows)} hitters | future HR/PA {rate * 100:.2f}%"
        )

    table = correlation_table(checkpoints)
    print("\nCorrelation with next-period HR/PA")
    for _, row in table.iterrows():
        pearson = "n/a" if pd.isna(row["pearson"]) else f"{row['pearson']:.3f}"
        spearman = "n/a" if pd.isna(row["spearman"]) else f"{row['spearman']:.3f}"
        print(f"- {row['metric']}: Pearson {pearson}, Spearman {spearman}, n={int(row['n'])}")

    threat_values = {
        "A": table[table["metric"].eq("Threat A no LBI")]["pearson"].iloc[0],
        "B": table[table["metric"].eq("Threat B LBI 10%")]["pearson"].iloc[0],
        "C": table[table["metric"].eq("Threat C LBI 15%")]["pearson"].iloc[0],
        "D": table[table["metric"].eq("Threat D contact xISO")]["pearson"].iloc[0],
        "E": table[table["metric"].eq("Threat E contact xSLG")]["pearson"].iloc[0],
        "F": table[table["metric"].eq("Threat F LBI/contact xISO")]["pearson"].iloc[0],
    }
    barrel = table[table["metric"].eq("Barrel/PA")]["pearson"].iloc[0]
    print("\nBacktest readout")
    best_variant = max(threat_values.items(), key=lambda item: item[1] if pd.notna(item[1]) else -999)
    if pd.notna(best_variant[1]) and pd.notna(barrel) and best_variant[1] > barrel:
        print(f"Best Threat variant {best_variant[0]} beats Barrel/PA alone by Pearson correlation ({best_variant[1]:.3f} vs {barrel:.3f}).")
    elif pd.notna(best_variant[1]) and pd.notna(barrel):
        print(f"Barrel/PA alone is stronger than all Threat variants here ({barrel:.3f} vs best {best_variant[1]:.3f}). Do not publish yet.")
    else:
        print("Not enough data to compare Longball Threat against Barrel/PA.")
    if all(pd.notna(value) for value in threat_values.values()):
        print(
            "LBI effect: "
            f"A no-LBI {threat_values['A']:.3f}, B 10% LBI {threat_values['B']:.3f}, C 15% LBI {threat_values['C']:.3f}."
        )
        print(
            "Contact effect: "
            f"D contact xISO {threat_values['D']:.3f}, E contact xSLG {threat_values['E']:.3f}, "
            f"F split {threat_values['F']:.3f}."
        )
        if threat_values["B"] > threat_values["A"] or threat_values["C"] > threat_values["A"]:
            print("Including LBI improved this test, but the gain should be validated across more seasons.")
        else:
            print("Including LBI did not improve this test; keep LBI as context/display unless broader testing changes that.")
        if threat_values["D"] > threat_values["B"] or threat_values["D"] > threat_values["C"]:
            print("Contact xISO improved over at least one LBI variant in this test.")
        else:
            print("Contact xISO did not improve over the LBI variants in this test.")
    return table


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
        print("Goal: park-neutral future home-run danger per plate appearance.")
        print("Variants:")
        print("- A: 40% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 10% Avg Barrel Distance")
        print("- B: 40% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 10% LBI")
        print("- C: 35% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 15% LBI")
        print("- D: 40% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 10% contact xISO proxy")
        print("- E: 40% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 10% contact xSLG")
        print("- F: 40% Barrel/PA, 35% Adjusted xHR/PA, 15% Hard-Hit Air BBE/PA, 5% LBI, 5% contact xISO proxy")
        print("Contact xISO proxy = mean(estimated_slg_using_speedangle) - mean(estimated_ba_using_speedangle) on BBE.")
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
            f"A median={full['longballThreatA'].median():.1f}, mean={full['longballThreatA'].mean():.1f}, "
            f"max={full['longballThreatA'].max():.1f}, min={full['longballThreatA'].min():.1f}"
        )

        for variant_key in THREAT_VARIANTS:
            print_top_threat(full, 30, variant_key)
        print_sanity(full)
        print_rank_gaps(full)

    table = print_backtest(backtests, season)
    if print_details:
        threat_rows = table[table["metric"].astype(str).str.startswith("Threat ")].dropna(subset=["pearson"])
        best_metric = threat_rows.sort_values("pearson", ascending=False).iloc[0]["metric"] if not threat_rows.empty else "Threat A no LBI"
        best_variant_key = best_metric.split()[1]
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
            seasons=("season", "nunique"),
        )
        .sort_values("avgPearson", ascending=False)
    )
    for _, row in summary.iterrows():
        print(
            f"- {row['metric']}: avg Pearson {row['avgPearson']:.3f}, "
            f"avg Spearman {row['avgSpearman']:.3f}, seasons {int(row['seasons'])}"
        )

    wins = []
    for season, season_table in combined.dropna(subset=["pearson"]).groupby("season"):
        winner = season_table.sort_values("pearson", ascending=False).iloc[0]
        wins.append((season, winner["metric"], winner["pearson"]))
    print("\nSeason winners")
    for season, metric, pearson in wins:
        print(f"- {season}: {metric} ({pearson:.3f})")

    threat_metrics = [metric for metric in combined["metric"].unique() if str(metric).startswith("Threat ")]
    threat_wins = {metric: sum(winner == metric for _, winner, _ in wins) for metric in threat_metrics}
    print("\nThreat variant wins")
    for metric, count in sorted(threat_wins.items()):
        print(f"- {metric}: {count}")

    mean_lookup = summary.set_index("metric")["avgPearson"].to_dict()
    print("\nInterpretation")
    print(
        f"LBI variants vs A: B {mean_lookup.get('Threat B LBI 10%', float('nan')):.3f}, "
        f"C {mean_lookup.get('Threat C LBI 15%', float('nan')):.3f}, "
        f"A {mean_lookup.get('Threat A no LBI', float('nan')):.3f}."
    )
    print(
        f"Contact xISO vs LBI: D {mean_lookup.get('Threat D contact xISO', float('nan')):.3f}, "
        f"F {mean_lookup.get('Threat F LBI/contact xISO', float('nan')):.3f}, "
        f"B {mean_lookup.get('Threat B LBI 10%', float('nan')):.3f}, "
        f"C {mean_lookup.get('Threat C LBI 15%', float('nan')):.3f}."
    )
    print(
        f"Barrel/PA baseline: {mean_lookup.get('Barrel/PA', float('nan')):.3f}. "
        "A variant should beat this consistently before publication."
    )


def main() -> None:
    args = parse_args()
    seasons = args.seasons or [args.season]
    if args.lbi_json and len(seasons) > 1:
        raise RuntimeError("--lbi-json can only be used with a single --season run.")

    tables: list[pd.DataFrame] = []
    for index, season in enumerate(seasons):
        _, table, _ = run_season(args, season, print_details=(len(seasons) == 1))
        tables.append(table)
        if len(seasons) > 1:
            best = table.dropna(subset=["pearson"]).sort_values("pearson", ascending=False).iloc[0]
            print(f"{season}: best {best['metric']} Pearson {best['pearson']:.3f}, Spearman {best['spearman']:.3f}")

    if len(seasons) > 1:
        print_multi_season_summary(tables)


if __name__ == "__main__":
    main()
