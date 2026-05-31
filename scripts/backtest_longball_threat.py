#!/usr/bin/env python3
"""Backtest Longball Threat against future HR/PA.

This is a diagnostic script only. It does not write frontend JSON or alter the
published Longball Index / Hot Dog Index data. It pulls/caches historical
Statcast pitch rows, derives first-half inputs, and tests how well Longball
Threat variants predict second-half HR/PA.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))

from data_integrity import validate_hrt_detail_completeness  # noqa: E402
from generate_hr_distance import (  # noqa: E402
    HOME_RUN_TRACKER_CAT,
    fetch_home_run_tracker,
    fetch_home_run_tracker_detail_rows,
    join_home_run_tracker_details,
    lookup_player_names,
    normalize_event_frame,
)
from pybaseball import statcast  # noqa: E402


CACHE_DIR = Path("data/cache/longball-threat-backtest")
FETCH_CHUNK_DAYS = 7
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]

SPLITS = {
    # Regular-season dates around the All-Star break. First half ends on the
    # final pre-break game date; second half starts on the first post-break game date.
    2021: ("2021-03-31", "2021-07-11", "2021-07-15", "2021-10-03"),
    2022: ("2022-04-07", "2022-07-17", "2022-07-21", "2022-10-05"),
    2023: ("2023-03-30", "2023-07-09", "2023-07-14", "2023-10-01"),
    2024: ("2024-03-28", "2024-07-14", "2024-07-19", "2024-09-30"),
    2025: ("2025-03-27", "2025-07-13", "2025-07-18", "2025-09-28"),
}

VARIANTS = {
    "A_v0.1": {
        "adjustedXhrPerPa": 0.55,
        "barrelsPerPa": 0.25,
        "hardHitAirBbePerPa": 0.10,
        "avgDistanceOnBarrels": 0.10,
    },
    "B_xhr_heavy": {
        "adjustedXhrPerPa": 0.70,
        "barrelsPerPa": 0.15,
        "hardHitAirBbePerPa": 0.10,
        "avgDistanceOnBarrels": 0.05,
    },
    "C_two_factor": {
        "adjustedXhrPerPa": 0.75,
        "barrelsPerPa": 0.25,
    },
    "D_xhr_only": {
        "adjustedXhrPerPa": 1.00,
    },
}


@dataclass(frozen=True)
class SeasonSplit:
    season: int
    first_start: date
    first_end: date
    second_start: date
    second_end: date


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def season_split(season: int) -> SeasonSplit:
    if season not in SPLITS:
        raise ValueError(f"No All-Star split configured for {season}")
    first_start, first_end, second_start, second_end = [parse_date(value) for value in SPLITS[season]]
    return SeasonSplit(season, first_start, first_end, second_start, second_end)


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def display_name_from_savant(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def fetch_statcast_range(start: date, end: date, cache_path: Path, refresh: bool = False) -> pd.DataFrame:
    if cache_path.exists() and not refresh:
        print(f"Using cached Statcast pitches: {cache_path}")
        return pd.read_csv(cache_path)

    chunks: list[pd.DataFrame] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=FETCH_CHUNK_DAYS - 1), end)
        print(f"Fetching Statcast pitches {current} through {chunk_end}")
        chunk = statcast(start_dt=current.isoformat(), end_dt=chunk_end.isoformat())
        if chunk is not None and not chunk.empty:
            chunks.append(chunk)
        current = chunk_end + timedelta(days=1)

    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(cache_path, index=False)
    return frame


def slim_pitch_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "game_date",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "batter",
        "player_name",
        "events",
        "type",
        "hit_distance_sc",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "bb_type",
        "pitcher",
        "home_team",
        "away_team",
        "inning_topbot",
        "des",
    ]
    slim = frame.copy()
    for column in columns:
        if column not in slim.columns:
            slim[column] = pd.NA
    for column in ["game_pk", "at_bat_number", "pitch_number", "batter", "pitcher"]:
        slim[column] = to_numeric(slim[column])
    for column in ["hit_distance_sc", "launch_speed", "launch_angle", "launch_speed_angle"]:
        slim[column] = to_numeric(slim[column])
    return slim[columns]


def bbe_events_from_pitches(frame: pd.DataFrame) -> pd.DataFrame:
    slim = slim_pitch_frame(frame)
    bbe = slim[slim["batter"].notna() & slim["launch_speed"].notna() & slim["launch_angle"].notna()].copy()
    return normalize_event_frame(bbe)


def half_stats(frame: pd.DataFrame) -> pd.DataFrame:
    slim = slim_pitch_frame(frame)
    slim = slim[slim["batter"].notna()].copy()
    terminal = slim[slim["events"].notna() & slim["events"].astype("string").str.strip().ne("")]
    pa = (
        terminal.drop_duplicates(["game_pk", "at_bat_number", "batter"])
        .groupby("batter", as_index=False)
        .size()
        .rename(columns={"size": "pa"})
    )

    bbe = slim[slim["launch_speed"].notna() & slim["launch_angle"].notna()].copy()
    bbe["isBarrel"] = bbe["launch_speed_angle"].eq(6)
    bbe["isHardHit"] = bbe["launch_speed"].ge(95)
    bbe["isHardHitAir"] = bbe["launch_speed"].ge(95) & bbe["launch_angle"].between(15, 40, inclusive="both")
    bbe["isHr"] = bbe["events"].astype("string").str.lower().eq("home_run")
    bbe["barrelDistance"] = bbe["hit_distance_sc"].where(bbe["isBarrel"])
    stats = (
        bbe.groupby("batter", as_index=False)
        .agg(
            bbe=("batter", "size"),
            hr=("isHr", "sum"),
            barrels=("isBarrel", "sum"),
            hardHitBbe=("isHardHit", "sum"),
            hardHitAirBbe=("isHardHitAir", "sum"),
            avgDistanceOnBarrels=("barrelDistance", "mean"),
        )
    )
    return pa.merge(stats, on="batter", how="outer").fillna(
        {"pa": 0, "bbe": 0, "hr": 0, "barrels": 0, "hardHitBbe": 0, "hardHitAirBbe": 0}
    )


def cached_home_run_tracker_details(season: int, tracker_rows: pd.DataFrame, refresh: bool = False) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"hrt-details-{season}-{HOME_RUN_TRACKER_CAT}.csv"
    if cache_path.exists() and not refresh:
        print(f"Using cached Home Run Tracker details: {cache_path}")
        details = pd.read_csv(cache_path)
        validate_hrt_detail_completeness(details, season, label=str(cache_path))
        return details
    details = fetch_home_run_tracker_detail_rows(tracker_rows, season)
    validate_hrt_detail_completeness(details, season, label=str(cache_path))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(cache_path, index=False)
    return details


def detail_xhr_column(details: pd.DataFrame) -> str | None:
    for column in ["xhr", "xHR", "adj_xhr", "adjusted_xhr", "expected_hr", "x_hr"]:
        if column in details.columns:
            return column
    return None


def xhr_source_label(column: str | None) -> str:
    if column:
        return f"direct-detail-column:{column}"
    return "adjusted-home-run-tracker-ct-over-30"


def add_adjusted_xhr(
    season: int,
    candidates: pd.DataFrame,
    first_bbe: pd.DataFrame,
    refresh_hrt: bool,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    tracker = fetch_home_run_tracker(season)
    details = cached_home_run_tracker_details(season, tracker, refresh_hrt)
    if details.empty:
        result = candidates.copy()
        result["adjustedXhr"] = 0.0
        result["adjustedXhrSource"] = "missing"
        return result, "missing", {"detailRows": 0, "joinedRows": 0, "joinRate": 0}

    joined = join_home_run_tracker_details(details, first_bbe)
    xhr_column = detail_xhr_column(joined)
    source = xhr_source_label(xhr_column)
    if xhr_column:
        joined["detailXhr"] = to_numeric(joined[xhr_column]).fillna(0)
    else:
        joined["detailXhr"] = to_numeric(joined.get("ct", pd.Series(0, index=joined.index))).fillna(0).clip(0, 30) / 30

    grouped = joined.groupby("batter_id", as_index=False).agg(adjustedXhr=("detailXhr", "sum"))
    result = candidates.merge(grouped, left_on="batter", right_on="batter_id", how="left")
    result["adjustedXhr"] = result["adjustedXhr"].fillna(0)
    result["adjustedXhrSource"] = source
    diagnostics = {
        "detailRows": int(len(details)),
        "joinedRows": int(len(joined)),
        "joinRate": round(float(len(joined) / len(details)), 4) if len(details) else 0,
    }
    return result.drop(columns=[column for column in ["batter_id"] if column in result.columns]), source, diagnostics


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
    for index, row in frame.iterrows():
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


def add_component_rates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["adjustedXhrPerPa"] = out["adjustedXhr"] / out["firstPa"].where(out["firstPa"].gt(0))
    out["barrelsPerPa"] = out["firstBarrels"] / out["firstPa"].where(out["firstPa"].gt(0))
    out["hardHitAirBbePerPa"] = out["firstHardHitAirBbe"] / out["firstPa"].where(out["firstPa"].gt(0))
    out["actualHrPerPa"] = out["firstHr"] / out["firstPa"].where(out["firstPa"].gt(0))
    out["secondHrPerPa"] = out["secondHr"] / out["secondPa"].where(out["secondPa"].gt(0))
    out["xhrPerBbe"] = out["adjustedXhr"] / out["firstBbe"].where(out["firstBbe"].gt(0))
    out["barrelRate"] = out["firstBarrels"] / out["firstBbe"].where(out["firstBbe"].gt(0))
    out["hardHitRate"] = out["firstHardHitBbe"] / out["firstBbe"].where(out["firstBbe"].gt(0))
    return out


def add_lbi_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    lbi_weights = {
        "xhrPerBbe": 0.60,
        "barrelRate": 0.20,
        "avgDistanceOnBarrels": 0.125,
        "hardHitRate": 0.075,
    }
    out["lbiProxy"] = weighted_scores(out, lbi_weights)
    return out


def add_threat_variants(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for name, weights in VARIANTS.items():
        out[f"threat_{name}"] = weighted_scores(out, weights)
    out["longballThreat"] = out["threat_A_v0.1"]
    return out


def add_projected_rates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    league_xhr_per_barrel = out["adjustedXhr"].sum() / out["firstBarrels"].sum() if out["firstBarrels"].sum() else 0
    league_xhr_per_hard_air = out["adjustedXhr"].sum() / out["firstHardHitAirBbe"].sum() if out["firstHardHitAirBbe"].sum() else 0
    league_xhr_per_pa = out["adjustedXhr"].sum() / out["firstPa"].sum() if out["firstPa"].sum() else 0
    distance_score = percentile_scores(out["avgDistanceOnBarrels"]).fillna(100) / 100

    for name, weights in VARIANTS.items():
        rate = pd.Series(0.0, index=out.index)
        if "adjustedXhrPerPa" in weights:
            rate += weights["adjustedXhrPerPa"] * out["adjustedXhrPerPa"].fillna(0)
        if "barrelsPerPa" in weights:
            rate += weights["barrelsPerPa"] * out["barrelsPerPa"].fillna(0) * league_xhr_per_barrel
        if "hardHitAirBbePerPa" in weights:
            rate += weights["hardHitAirBbePerPa"] * out["hardHitAirBbePerPa"].fillna(0) * league_xhr_per_hard_air
        if "avgDistanceOnBarrels" in weights:
            rate += weights["avgDistanceOnBarrels"] * league_xhr_per_pa * distance_score
        out[f"projectedHrPer600_{name}"] = rate * 600

    out["targetHrPer600"] = out["secondHrPerPa"] * 600
    return out


def prepare_season(season: int, refresh_statcast: bool, refresh_hrt: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    split = season_split(season)
    first_cache = CACHE_DIR / f"statcast-pitches-{season}-first.csv"
    second_cache = CACHE_DIR / f"statcast-pitches-{season}-second.csv"
    first_pitches = fetch_statcast_range(split.first_start, split.first_end, first_cache, refresh_statcast)
    second_pitches = fetch_statcast_range(split.second_start, split.second_end, second_cache, refresh_statcast)

    first = half_stats(first_pitches).rename(
        columns={
            "pa": "firstPa",
            "bbe": "firstBbe",
            "hr": "firstHr",
            "barrels": "firstBarrels",
            "hardHitBbe": "firstHardHitBbe",
            "hardHitAirBbe": "firstHardHitAirBbe",
        }
    )
    second = half_stats(second_pitches).rename(columns={"pa": "secondPa", "hr": "secondHr"})
    first_bbe = bbe_events_from_pitches(first_pitches)
    combined = first.merge(second[["batter", "secondPa", "secondHr"]], on="batter", how="inner")
    eligible = combined[
        combined["firstPa"].ge(100)
        & combined["secondPa"].ge(75)
        & combined["firstBbe"].ge(50)
    ].copy()

    with_xhr, source, hrt_diag = add_adjusted_xhr(season, eligible, first_bbe, refresh_hrt)
    rows = add_projected_rates(add_threat_variants(add_lbi_proxy(add_component_rates(with_xhr))))
    rows["season"] = season
    names = lookup_player_names(rows["batter"].dropna().astype(int).tolist())
    rows["player"] = rows["batter"].map(names)
    missing_names = rows["player"].isna() | rows["player"].astype("string").str.strip().eq("")
    rows["player"] = rows["player"].fillna("MLBAM " + rows["batter"].astype("Int64").astype(str))
    rows["threatRank"] = rows["longballThreat"].rank(method="first", ascending=False).astype(int)
    rows["targetRank"] = rows["secondHrPerPa"].rank(method="first", ascending=False).astype(int)

    diagnostics = {
        "season": season,
        "split": split,
        "eligiblePlayers": int(len(rows)),
        "xhrSource": source,
        **hrt_diag,
    }
    return rows.sort_values("longballThreat", ascending=False), diagnostics


def rmse(predicted: pd.Series, actual: pd.Series) -> float:
    diff = predicted - actual
    return math.sqrt(float((diff.dropna() ** 2).mean()))


def mae(predicted: pd.Series, actual: pd.Series) -> float:
    return float((predicted - actual).abs().dropna().mean())


def metric_report(rows: pd.DataFrame) -> pd.DataFrame:
    metrics = {
        "Longball Threat A": ("longballThreat", "projectedHrPer600_A_v0.1"),
        "Threat B xHR-heavy": ("threat_B_xhr_heavy", "projectedHrPer600_B_xhr_heavy"),
        "Threat C two-factor": ("threat_C_two_factor", "projectedHrPer600_C_two_factor"),
        "Threat D xHR-only": ("threat_D_xhr_only", "projectedHrPer600_D_xhr_only"),
        "Adjusted xHR/PA": ("adjustedXhrPerPa", "projectedHrPer600_D_xhr_only"),
        "Barrels/PA": ("barrelsPerPa", None),
        "LBI proxy": ("lbiProxy", None),
        "Actual first-half HR/PA": ("actualHrPerPa", None),
        "Hard-hit air BBE/PA": ("hardHitAirBbePerPa", None),
        "Avg Distance on Barrels": ("avgDistanceOnBarrels", None),
    }
    report = []
    for label, (column, projection_column) in metrics.items():
        data = rows[[column, "secondHrPerPa", "targetHrPer600"]].dropna()
        if data.empty:
            continue
        item = {
            "metric": label,
            "pearson": data[column].corr(data["secondHrPerPa"], method="pearson"),
            "spearman": data[column].corr(data["secondHrPerPa"], method="spearman"),
            "rmseHr600": None,
            "maeHr600": None,
        }
        if projection_column:
            projected = rows[projection_column]
            item["rmseHr600"] = rmse(projected, rows["targetHrPer600"])
            item["maeHr600"] = mae(projected, rows["targetHrPer600"])
        report.append(item)
    return pd.DataFrame(report)


def print_metric_report(title: str, report: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    for _, row in report.sort_values("pearson", ascending=False).iterrows():
        rmse_text = "n/a" if pd.isna(row["rmseHr600"]) else f"{row['rmseHr600']:.2f}"
        mae_text = "n/a" if pd.isna(row["maeHr600"]) else f"{row['maeHr600']:.2f}"
        print(
            f"{row['metric']:<28} pearson {row['pearson']:.3f} | "
            f"spearman {row['spearman']:.3f} | RMSE/600 {rmse_text} | MAE/600 {mae_text}"
        )


def print_top_players(rows: pd.DataFrame, season: int, limit: int = 20) -> None:
    print(f"\n=== {season} Top {limit} Longball Threat A ===")
    for _, row in rows.sort_values("longballThreat", ascending=False).head(limit).iterrows():
        print(
            f"{int(row['threatRank']):2}. {row['player']} | "
            f"LBT {row['longballThreat']:.1f} | 2H HR/600 {row['targetHrPer600']:.1f} | "
            f"xHR/PA {row['adjustedXhrPerPa'] * 100:.2f}% | Brl/PA {row['barrelsPerPa'] * 100:.2f}%"
        )


def print_misses(rows: pd.DataFrame, title: str, high_predicted: bool, limit: int = 15) -> None:
    data = rows.copy()
    data["missResidual"] = data["projectedHrPer600_A_v0.1"] - data["targetHrPer600"]
    if high_predicted:
        pool = data[data["longballThreat"].ge(data["longballThreat"].quantile(0.75))]
        pool = pool.sort_values("missResidual", ascending=False)
    else:
        pool = data[data["longballThreat"].le(data["longballThreat"].quantile(0.35))]
        pool = pool.sort_values("missResidual", ascending=True)
    print(f"\n=== {title} ===")
    for _, row in pool.head(limit).iterrows():
        print(
            f"{row['season']} {row['player']} | LBT {row['longballThreat']:.1f} | "
            f"pred HR/600 {row['projectedHrPer600_A_v0.1']:.1f} | actual 2H HR/600 {row['targetHrPer600']:.1f} | "
            f"resid {row['missResidual']:+.1f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Longball Threat v0.1 against second-half HR/PA.")
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--refresh-statcast", action="store_true", help="Ignore cached diagnostic Statcast pitch pulls.")
    parser.add_argument("--refresh-hrt", action="store_true", help="Ignore cached Home Run Tracker detail pulls.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    all_rows: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    print("=== Longball Threat First-Half to Second-Half Backtest ===")
    print("Split: configured All-Star break dates, excluding the break itself.")
    print("Eligibility: first-half PA >= 100, second-half PA >= 75, first-half BBE >= 50.")
    print("Target: second-half actual HR/PA.")
    print("Adjusted xHR note: if Home Run Tracker details lack a direct xHR column, the script uses adjusted-mode ct / 30.")

    for season in args.seasons:
        rows, diag = prepare_season(season, args.refresh_statcast, args.refresh_hrt)
        all_rows.append(rows)
        diagnostics.append(diag)
        split = diag["split"]
        print(
            f"\n{season}: {split.first_start} through {split.first_end} vs "
            f"{split.second_start} through {split.second_end}"
        )
        print(
            f"Eligible players: {diag['eligiblePlayers']} | xHR source: {diag['xhrSource']} | "
            f"first-half HRT matches {diag['joinedRows']}/{diag['detailRows']} detail rows ({diag['joinRate']:.1%})"
        )
        print_metric_report(f"{season} Correlations", metric_report(rows))
        print_top_players(rows, season, 20)

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if combined.empty:
        raise RuntimeError("No eligible player seasons were produced.")

    print_metric_report("Pooled 2021-2025 Correlations", metric_report(combined))
    print_misses(combined, "Biggest Misses: High Threat, Low Second-Half HR/PA", high_predicted=True)
    print_misses(combined, "Biggest Misses: Low Threat, High Second-Half HR/PA", high_predicted=False)

    pooled = metric_report(combined).set_index("metric")
    threat = pooled.loc["Longball Threat A"]
    xhr = pooled.loc["Adjusted xHR/PA"]
    print("\n=== Readout ===")
    print(
        "Longball Threat A vs adjusted xHR/PA alone: "
        f"pearson {threat['pearson']:.3f} vs {xhr['pearson']:.3f}; "
        f"spearman {threat['spearman']:.3f} vs {xhr['spearman']:.3f}; "
        f"RMSE/600 {threat['rmseHr600']:.2f} vs {xhr['rmseHr600']:.2f}."
    )
    if threat["pearson"] > xhr["pearson"] and threat["rmseHr600"] <= xhr["rmseHr600"]:
        print("Result: Longball Threat A beats adjusted xHR/PA alone on the pooled headline checks.")
    else:
        print("Result: adjusted xHR/PA alone remains the benchmark to beat; inspect variants before productizing.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
