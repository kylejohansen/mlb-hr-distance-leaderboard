#!/usr/bin/env python3
"""Diagnostic backtest for a possible Power Due content section.

This script is intentionally not part of the public data pipeline. It tests
whether hitters with strong longball quality but lagging actual HR output later
produce more HR per batted ball than comparison groups.

The first version uses 2025 monthly checkpoints and local caches only. Because
the historical archives do not expose plate appearances at monthly checkpoints,
the outcome is next-period HR/BBE, not HR/PA.

Validation note: v0.1 was noisy. The v0.2 definitions C and D showed some
signal versus all-qualified and similar-HR comparison groups, but still trailed
the high-quality-not-due group. Until stronger validation exists, any public
copy should use "Power Gap" rather than "Power Due"; this remains an internal
diagnostic tool only.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd


NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
DEFAULT_SEASON = 2025
DEFAULT_CHECKPOINTS = ["2025-05-01", "2025-06-01", "2025-07-01", "2025-08-01"]
DEFAULT_NEXT_WEEKS = 6
DEFAULT_MIN_FIRST_BBE = 50
DEFAULT_MIN_NEXT_BBE = 25
LBI_PROXY_WEIGHTS = {
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "avgDistanceOnBarrels": 0.125,
    "hardHitRate": 0.075,
}


@dataclass(frozen=True)
class CheckpointResult:
    checkpoint: date
    period_end: date
    qualified: pd.DataFrame


@dataclass(frozen=True)
class DefinitionCheckpoint:
    key: str
    label: str
    checkpoint: date
    period_end: date
    eligible: pd.DataFrame
    candidates: pd.DataFrame
    high_quality_not_due: pd.DataFrame
    similar_hr: pd.DataFrame
    qualified_rate: float | None


DEFINITIONS = {
    "A": {
        "label": "A: v0.1 baseline",
        "min_first_bbe": 50,
        "min_next_bbe": 25,
        "description": [
            "Strong quality: LBI proxy >= 120 OR xHR/BBE in the checkpoint top quartile",
            "Underproducing: adjusted xHR proxy - actual HR >= 2 OR actual HR / adjusted xHR proxy <= 0.75",
        ],
    },
    "B": {
        "label": "B: stricter quality gap",
        "min_first_bbe": 75,
        "min_next_bbe": 40,
        "description": [
            "LBI proxy >= 125",
            "xHR/BBE in the checkpoint top 30%",
            "adjusted xHR proxy - actual HR >= 2",
            "actual HR / adjusted xHR proxy <= 0.80",
        ],
    },
    "C": {
        "label": "C: barrel-supported power gap",
        "min_first_bbe": 75,
        "min_next_bbe": 40,
        "description": [
            "xHR/BBE in the checkpoint top 35%",
            "Barrel% above checkpoint league average",
            "Hard Hit% above checkpoint league average",
            "adjusted xHR proxy - actual HR >= 2",
        ],
    },
    "D": {
        "label": "D: high-quality, low-results",
        "min_first_bbe": 75,
        "min_next_bbe": 40,
        "description": [
            "LBI proxy in the checkpoint top quartile",
            "Actual HR total below checkpoint median among eligible hitters",
            "xHR/BBE in the checkpoint top quartile",
        ],
    },
}


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


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


def cache_path_for_season(season: int) -> Path:
    return Path(f"data/raw/statcast-bbe-events-{season}.csv")


def hrt_detail_path_for_season(season: int) -> Path:
    return Path(f"data/cache/longball-threat-backtest/hrt-details-{season}-adj_xhr.csv")


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
        raise RuntimeError(f"Missing local Statcast cache: {path}")
    frame = pd.read_csv(path)
    required = ["game_date", "batter", "events", "launch_speed", "launch_angle", "launch_speed_angle", "hit_distance_sc"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} is missing required columns: {', '.join(missing)}")
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce").dt.date
    for column in ["batter", "launch_speed", "launch_angle", "launch_speed_angle", "hit_distance_sc"]:
        frame[column] = to_numeric(frame[column])
    return frame.dropna(subset=["game_date", "batter"]).copy()


def load_hrt_details(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(
            f"Missing Home Run Tracker detail cache: {path}\n"
            "Run the Longball Threat backtest or Home Run Tracker diagnostic first, then rerun this script."
        )
    details = pd.read_csv(path)
    required = ["game_date", "batter_id", "ct"]
    missing = [column for column in required if column not in details.columns]
    if missing:
        raise RuntimeError(f"{path} is missing required columns: {', '.join(missing)}")
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


def bbe_stats(frame: pd.DataFrame, start: date, end: date, prefix: str) -> pd.DataFrame:
    window = frame[(frame["game_date"] >= start) & (frame["game_date"] <= end)].copy()
    bbe = window[window["launch_speed"].notna() & window["launch_angle"].notna()].copy()
    if bbe.empty:
        return pd.DataFrame(columns=["batter"])

    bbe["isHr"] = bbe["events"].astype("string").str.lower().eq("home_run")
    bbe["isBarrel"] = bbe["launch_speed_angle"].eq(6)
    bbe["isHardHit"] = bbe["launch_speed"].ge(95)
    bbe["barrelDistance"] = bbe["hit_distance_sc"].where(bbe["isBarrel"])
    grouped = (
        bbe.groupby("batter", as_index=False)
        .agg(
            bbe=("batter", "size"),
            hr=("isHr", "sum"),
            barrels=("isBarrel", "sum"),
            hardHitBbe=("isHardHit", "sum"),
            avgDistanceOnBarrels=("barrelDistance", "mean"),
        )
        .rename(
            columns={
                "bbe": f"{prefix}Bbe",
                "hr": f"{prefix}Hr",
                "barrels": f"{prefix}Barrels",
                "hardHitBbe": f"{prefix}HardHitBbe",
                "avgDistanceOnBarrels": f"{prefix}AvgDistanceOnBarrels",
            }
        )
    )
    return grouped


def adjusted_xhr_stats(details: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    window = details[(details["game_date"] >= start) & (details["game_date"] <= end)].copy()
    if window.empty:
        return pd.DataFrame(columns=["batter", "adjustedXhr"])
    # Diagnostic proxy used by prior Longball Threat backtest when no direct xHR
    # column is present: adjusted Home Run Tracker parks-cleared count / 30.
    window["detailXhr"] = window["ct"].fillna(0) / 30
    return (
        window.groupby("batter_id", as_index=False)
        .agg(adjustedXhr=("detailXhr", "sum"))
        .rename(columns={"batter_id": "batter"})
    )


def prepare_checkpoint(
    pitches: pd.DataFrame,
    details: pd.DataFrame,
    names: dict[int, str],
    season_start: date,
    checkpoint: date,
    next_weeks: int,
    min_first_bbe: int,
    min_next_bbe: int,
) -> CheckpointResult:
    period_start = checkpoint + timedelta(days=1)
    period_end = checkpoint + timedelta(weeks=next_weeks)
    first = bbe_stats(pitches, season_start, checkpoint, "first")
    future = bbe_stats(pitches, period_start, period_end, "next")
    xhr = adjusted_xhr_stats(details, season_start, checkpoint)
    rows = first.merge(xhr, on="batter", how="left").merge(
        future[["batter", "nextBbe", "nextHr"]],
        on="batter",
        how="left",
    )
    rows["adjustedXhr"] = rows["adjustedXhr"].fillna(0)
    rows["nextBbe"] = rows["nextBbe"].fillna(0)
    rows["nextHr"] = rows["nextHr"].fillna(0)
    rows["xhrPerBbe"] = rows["adjustedXhr"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["barrelRate"] = rows["firstBarrels"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["hardHitRate"] = rows["firstHardHitBbe"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["actualHrPerBbe"] = rows["firstHr"] / rows["firstBbe"].where(rows["firstBbe"].gt(0))
    rows["nextHrPerBbe"] = rows["nextHr"] / rows["nextBbe"].where(rows["nextBbe"].gt(0))
    rows["avgDistanceOnBarrels"] = rows["firstAvgDistanceOnBarrels"]
    rows["lbiProxy"] = weighted_scores(rows, LBI_PROXY_WEIGHTS)
    rows["player"] = rows["batter"].map(lambda value: names.get(int(value), f"MLBAM {int(value)}"))

    qualified = rows[rows["firstBbe"].ge(min_first_bbe) & rows["nextBbe"].ge(min_next_bbe)].copy()

    return CheckpointResult(
        checkpoint=checkpoint,
        period_end=period_end,
        qualified=qualified,
    )


def group_rate(frame: pd.DataFrame) -> float | None:
    if frame.empty or frame["nextBbe"].sum() <= 0:
        return None
    return float(frame["nextHr"].sum() / frame["nextBbe"].sum())


def format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}% HR/BBE"


def format_lift(candidate_rate: float | None, comparison_rate: float | None) -> str:
    if candidate_rate is None or comparison_rate is None:
        return "n/a"
    return f"{(candidate_rate - comparison_rate) * 100:+.2f} pct pts"


def actual_to_xhr_ratio(frame: pd.DataFrame) -> pd.Series:
    return frame["firstHr"] / frame["adjustedXhr"].where(frame["adjustedXhr"].gt(0))


def definition_frames(result: CheckpointResult, key: str) -> DefinitionCheckpoint:
    config = DEFINITIONS[key]
    eligible = result.qualified[
        result.qualified["firstBbe"].ge(config["min_first_bbe"])
        & result.qualified["nextBbe"].ge(config["min_next_bbe"])
    ].copy()
    if eligible.empty:
        empty = eligible.copy()
        return DefinitionCheckpoint(
            key=key,
            label=config["label"],
            checkpoint=result.checkpoint,
            period_end=result.period_end,
            eligible=eligible,
            candidates=empty,
            high_quality_not_due=empty,
            similar_hr=empty,
            qualified_rate=None,
        )

    xhr_top_quartile = eligible["xhrPerBbe"].quantile(0.75)
    xhr_top_30 = eligible["xhrPerBbe"].quantile(0.70)
    xhr_top_35 = eligible["xhrPerBbe"].quantile(0.65)
    lbi_top_quartile = eligible["lbiProxy"].quantile(0.75)
    median_hr = eligible["firstHr"].median()
    league_barrel_rate = eligible["barrelRate"].mean()
    league_hard_hit_rate = eligible["hardHitRate"].mean()
    xhr_gap = eligible["adjustedXhr"] - eligible["firstHr"]
    hr_xhr_ratio = actual_to_xhr_ratio(eligible)

    if key == "A":
        quality = eligible["lbiProxy"].ge(120) | eligible["xhrPerBbe"].ge(xhr_top_quartile)
        due = xhr_gap.ge(2) | hr_xhr_ratio.le(0.75)
    elif key == "B":
        quality = eligible["lbiProxy"].ge(125) & eligible["xhrPerBbe"].ge(xhr_top_30)
        due = xhr_gap.ge(2) & hr_xhr_ratio.le(0.80)
    elif key == "C":
        quality = (
            eligible["xhrPerBbe"].ge(xhr_top_35)
            & eligible["barrelRate"].gt(league_barrel_rate)
            & eligible["hardHitRate"].gt(league_hard_hit_rate)
        )
        due = xhr_gap.ge(2)
    elif key == "D":
        quality = (
            eligible["lbiProxy"].ge(lbi_top_quartile)
            & eligible["xhrPerBbe"].ge(xhr_top_quartile)
        )
        due = eligible["firstHr"].lt(median_hr)
    else:
        raise ValueError(f"Unknown definition key: {key}")

    candidates = eligible[quality & due].copy()
    high_quality_not_due = eligible[quality & ~due].copy()
    if candidates.empty:
        similar_hr = eligible.iloc[0:0].copy()
    else:
        candidate_hr_min = int(candidates["firstHr"].min())
        candidate_hr_max = int(candidates["firstHr"].max())
        similar_hr = eligible[
            ~eligible.index.isin(candidates.index)
            & eligible["firstHr"].between(max(0, candidate_hr_min - 1), candidate_hr_max + 1)
        ].copy()

    checkpoint_rate = group_rate(eligible)
    if checkpoint_rate is not None and not candidates.empty:
        candidates["beatsQualifiedRate"] = candidates["nextHrPerBbe"].gt(checkpoint_rate)
    else:
        candidates["beatsQualifiedRate"] = False

    return DefinitionCheckpoint(
        key=key,
        label=config["label"],
        checkpoint=result.checkpoint,
        period_end=result.period_end,
        eligible=eligible,
        candidates=candidates,
        high_quality_not_due=high_quality_not_due,
        similar_hr=similar_hr,
        qualified_rate=checkpoint_rate,
    )


def print_checkpoint_counts(evaluations: list[DefinitionCheckpoint]) -> None:
    if not evaluations:
        return
    checkpoint = evaluations[0].checkpoint
    period_end = evaluations[0].period_end
    qualified_count = len(evaluations[0].eligible)
    counts = " | ".join(f"{evaluation.key}: {len(evaluation.candidates)}" for evaluation in evaluations)
    print(f"\nCheckpoint {checkpoint} -> next period through {period_end}")
    print(f"Eligible hitters for Definition A: {qualified_count}")
    print(f"Candidate counts: {counts}")


def print_candidates(evaluation: DefinitionCheckpoint, limit: int) -> None:
    candidates = evaluation.candidates.sort_values(
        ["lbiProxy", "adjustedXhr", "firstHr"],
        ascending=[False, False, True],
    )
    print(f"\n{evaluation.label} candidates at {evaluation.checkpoint}: {len(candidates)}")
    if candidates.empty:
        return
    print("Candidate list:")
    for _, row in candidates.head(limit).iterrows():
        print(
            f"- {row['player']}: LBI proxy {row['lbiProxy']:.1f}, "
            f"xHR {row['adjustedXhr']:.1f}, HR {int(row['firstHr'])}, "
            f"xHR/BBE {row['xhrPerBbe'] * 100:.2f}%, "
            f"next {int(row['nextHr'])}/{int(row['nextBbe'])} HR/BBE ({row['nextHrPerBbe'] * 100:.2f}%)"
        )


def concat_frames(evaluations: list[DefinitionCheckpoint], attr: str) -> pd.DataFrame:
    frames = [getattr(evaluation, attr).assign(checkpoint=evaluation.checkpoint) for evaluation in evaluations]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def recommendation_for(
    candidate_rate: float | None,
    qualified_rate: float | None,
    similar_rate: float | None,
    candidate_count: int,
) -> str:
    if candidate_count < 10:
        return "too narrow"
    if candidate_rate is None or qualified_rate is None or similar_rate is None:
        return "needs refinement"
    lift_vs_all = candidate_rate - qualified_rate
    lift_vs_similar = candidate_rate - similar_rate
    if lift_vs_all >= 0.003 and lift_vs_similar >= 0.003:
        return "useful"
    if lift_vs_all <= 0 or lift_vs_similar <= 0:
        return "noisy"
    return "needs refinement"


def print_definition_summary(key: str, evaluations: list[DefinitionCheckpoint]) -> None:
    label = DEFINITIONS[key]["label"]
    print(f"\n=== {label} Summary ===")
    print("Definition:")
    for line in DEFINITIONS[key]["description"]:
        print(f"- {line}")
    all_candidates = concat_frames(evaluations, "candidates")
    all_qualified = concat_frames(evaluations, "eligible")
    all_high_quality_not_due = concat_frames(
        evaluations,
        "high_quality_not_due",
    )
    all_similar_hr = concat_frames(evaluations, "similar_hr")

    candidate_rate = group_rate(all_candidates)
    qualified_rate = group_rate(all_qualified)
    high_quality_rate = group_rate(all_high_quality_not_due)
    similar_rate = group_rate(all_similar_hr)
    hit_rate = None
    if not all_candidates.empty and "beatsQualifiedRate" in all_candidates.columns:
        hit_rate = float(all_candidates["beatsQualifiedRate"].mean())

    print(f"Candidate player-checkpoints: {len(all_candidates)}")
    print(f"Candidate future rate: {format_rate(candidate_rate)}")
    print(f"All qualified future rate: {format_rate(qualified_rate)}")
    print(f"Similar HR-total group rate: {format_rate(similar_rate)}")
    print(f"High-quality not-due group rate: {format_rate(high_quality_rate)}")
    print(f"Lift vs all qualified: {format_lift(candidate_rate, qualified_rate)}")
    print(f"Lift vs similar HR-total hitters: {format_lift(candidate_rate, similar_rate)}")
    print(f"Lift vs high-quality not-due hitters: {format_lift(candidate_rate, high_quality_rate)}")
    print(f"Hit rate vs checkpoint qualified rate: {hit_rate * 100:.1f}%" if hit_rate is not None else "Hit rate: n/a")

    if not all_candidates.empty:
        print("\nBiggest hits")
        for _, row in all_candidates.sort_values("nextHrPerBbe", ascending=False).head(8).iterrows():
            print(
                f"{row['checkpoint']} {row['player']}: next {int(row['nextHr'])}/{int(row['nextBbe'])} "
                f"({row['nextHrPerBbe'] * 100:.2f}% HR/BBE), checkpoint HR {int(row['firstHr'])}, xHR {row['adjustedXhr']:.1f}"
            )
        print("\nBiggest misses")
        for _, row in all_candidates.sort_values(["nextHr", "nextHrPerBbe"], ascending=[True, True]).head(8).iterrows():
            print(
                f"{row['checkpoint']} {row['player']}: next {int(row['nextHr'])}/{int(row['nextBbe'])} "
                f"({row['nextHrPerBbe'] * 100:.2f}% HR/BBE), checkpoint HR {int(row['firstHr'])}, xHR {row['adjustedXhr']:.1f}"
            )

    print(f"\nRecommendation: {recommendation_for(candidate_rate, qualified_rate, similar_rate, len(all_candidates))}")


def print_summary(definition_results: dict[str, list[DefinitionCheckpoint]]) -> None:
    print("\n=== Power Due Backtest Summary ===")
    print("Outcome metric: next-period HR/BBE, not HR/PA. PA is not available in monthly historical snapshots.")
    print("Adjusted xHR proxy: adjusted Home Run Tracker parks-cleared count / 30, summed through checkpoint.")
    print("Public naming note: until this signal is validated, public-facing copy should use 'Power Gap' instead of 'Power Due.'")
    for key, evaluations in definition_results.items():
        print_definition_summary(key, evaluations)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose whether a Power Due signal predicts future HR production.")
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--pitch-cache", type=Path)
    parser.add_argument("--hrt-details", type=Path)
    parser.add_argument("--checkpoints", nargs="+", help="Checkpoint dates in YYYY-MM-DD format.")
    parser.add_argument("--next-weeks", type=int, default=DEFAULT_NEXT_WEEKS)
    parser.add_argument("--min-first-bbe", type=int, default=DEFAULT_MIN_FIRST_BBE)
    parser.add_argument("--min-next-bbe", type=int, default=DEFAULT_MIN_NEXT_BBE)
    parser.add_argument("--limit", type=int, default=12, help="Candidate rows to print per checkpoint.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pitch_cache = args.pitch_cache or cache_path_for_season(args.season)
    hrt_details = args.hrt_details or hrt_detail_path_for_season(args.season)
    pitches = load_pitch_cache(pitch_cache)
    details = load_hrt_details(hrt_details)
    names = load_name_map(args.season, details)
    checkpoints = [parse_date(value) for value in (args.checkpoints or DEFAULT_CHECKPOINTS)]
    season_start = max(parse_date(f"{args.season}-03-01"), min(pitches["game_date"]))

    print("=== Power Due Diagnostic Backtest ===")
    print(f"Season: {args.season}")
    print(f"Pitch cache: {pitch_cache}")
    print(f"Home Run Tracker detail cache: {hrt_details}")
    print("Candidate definitions:")
    for key, config in DEFINITIONS.items():
        print(f"- {config['label']}: first-window BBE >= {config['min_first_bbe']}, next-period BBE >= {config['min_next_bbe']}")
        for line in config["description"]:
            print(f"  - {line}")
    print("Limitation: monthly PA is unavailable locally, so this diagnostic uses future HR/BBE instead of HR/PA.")
    print("Measurement window: " f"{args.next_weeks} weeks after each checkpoint")
    print("Public naming note: until this signal is validated, public-facing copy should use 'Power Gap' instead of 'Power Due.'")

    results = []
    definition_results: dict[str, list[DefinitionCheckpoint]] = {key: [] for key in DEFINITIONS}
    for checkpoint in checkpoints:
        result = prepare_checkpoint(
            pitches=pitches,
            details=details,
            names=names,
            season_start=season_start,
            checkpoint=checkpoint,
            next_weeks=args.next_weeks,
            min_first_bbe=args.min_first_bbe,
            min_next_bbe=args.min_next_bbe,
        )
        results.append(result)
        evaluations = [definition_frames(result, key) for key in DEFINITIONS]
        for evaluation in evaluations:
            definition_results[evaluation.key].append(evaluation)
        print_checkpoint_counts(evaluations)
        for evaluation in evaluations:
            print_candidates(evaluation, args.limit)

    print_summary(definition_results)


if __name__ == "__main__":
    main()
