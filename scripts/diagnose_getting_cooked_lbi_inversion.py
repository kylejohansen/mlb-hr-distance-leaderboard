#!/usr/bin/env python3
"""Research-only diagnostic for pitcher-side LBI v1.4 inversion.

This script asks whether Getting Cooked would be improved by becoming an
inverted LBI-style stat. It does not write production data.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_integrity import scope_to_regular_season
from lbi_v14 import add_lbi_v14_event_columns


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]
PITCH_TEMPLATE = ROOT / "data/cache/longball-threat-backtest/statcast-pitches-{season}-{half}.csv"
HRT_TEMPLATE = ROOT / "data/cache/longball-threat-backtest/hrt-details-{season}-xhr.csv"
HOT_DOG_TEMPLATE = ROOT / "public/data/hot-dog-index-{season}.json"
DEFAULT_OUTPUT_DIR = ROOT / "analysis"

MIN_BBE = 100
MIN_HALF_BBE = 50
MIN_LBI_EVENTS = 8
TOP_N = 25

PITCH_USECOLS = {
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "pitcher_name",
    "player_name",
    "batter",
    "events",
    "launch_speed",
    "launch_angle",
    "launch_speed_angle",
    "hit_distance_sc",
    "hc_x",
    "hc_y",
    "stand",
    "home_team",
    "away_team",
    "inning_topbot",
}

HRT_USECOLS = {
    "game_pk",
    "batter_id",
    "pitcher_id",
    "result",
    "game_date",
    "ct",
    "exit_velocity",
    "launch_angle",
    "hr_distance",
    "pitcher_name",
    "batter_name",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose inverted LBI v1.4 as a Getting Cooked candidate.")
    parser.add_argument("--seasons", type=int, nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--min-bbe", type=int, default=MIN_BBE)
    parser.add_argument("--min-half-bbe", type=int, default=MIN_HALF_BBE)
    parser.add_argument("--min-lbi-events", type=int, default=MIN_LBI_EVENTS)
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def to_numeric(values: Any) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def safe_corr(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    clean = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(clean) < 3 or clean[left].nunique() < 2 or clean[right].nunique() < 2:
        return {"n": len(clean), "pearson": math.nan, "spearman": math.nan}
    return {
        "n": int(len(clean)),
        "pearson": float(clean[left].corr(clean[right], method="pearson")),
        "spearman": float(clean[left].corr(clean[right], method="spearman")),
    }


def plus_scale(values: pd.Series, league_value: float) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not league_value or pd.isna(league_value):
        return pd.Series(pd.NA, index=values.index)
    return 100 * numeric / league_value


def percentile_score(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return 100 * numeric.rank(method="average", pct=True)


def source_pitch_paths(season: int) -> list[Path]:
    return [Path(str(PITCH_TEMPLATE).format(season=season, half=half)) for half in ["first", "second"]]


def read_pitch_season(season: int) -> pd.DataFrame:
    frames = []
    for path in source_pitch_paths(season):
        if not path.exists():
            raise FileNotFoundError(f"Missing pitch cache: {path.relative_to(ROOT)}")
        frames.append(pd.read_csv(path, usecols=lambda column: column in PITCH_USECOLS))
    frame = pd.concat(frames, ignore_index=True)
    frame = scope_to_regular_season(frame, season)
    numeric_columns = [
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher",
        "batter",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "hit_distance_sc",
        "hc_x",
        "hc_y",
    ]
    for column in numeric_columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def read_hrt_details(season: int) -> pd.DataFrame:
    path = Path(str(HRT_TEMPLATE).format(season=season))
    if not path.exists():
        raise FileNotFoundError(f"Missing HRT detail cache: {path.relative_to(ROOT)}")
    frame = pd.read_csv(path, usecols=lambda column: column in HRT_USECOLS)
    frame = scope_to_regular_season(frame, season)
    for column in ["game_pk", "batter_id", "pitcher_id", "ct", "exit_velocity", "launch_angle", "hr_distance"]:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_hot_dog(season: int) -> pd.DataFrame:
    path = Path(str(HOT_DOG_TEMPLATE).format(season=season))
    if not path.exists():
        raise FileNotFoundError(f"Missing Hot Dog archive: {path.relative_to(ROOT)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("pitchers", []):
        current_getting_cooked = row.get("gettingCookedIndex", row.get("cookedPlus"))
        if current_getting_cooked is None:
            current_getting_cooked = row.get("hotDogIndex")
        rows.append(
            {
                "season": season,
                "pitcher_id": row.get("pitcherId"),
                "pitcher_hot_dog": row.get("pitcher"),
                "team_hot_dog": row.get("team"),
                "current_getting_cooked_plus": current_getting_cooked,
                "hot_dog_damage_allowed": row.get("hotDogDamageAllowed", row.get("hotDogIndex")),
                "adjusted_xhr_per_bbe_allowed": row.get("adjustedXhrPerBbeAllowed"),
                "hot_dog_hr_capable_rate": row.get("hrCapableBbeRateAllowed"),
                "hot_dog_hr_capable_bbe": row.get("hrCapableBbeAllowed"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher_id"], errors="coerce").astype("Int64")
    for column in [
        "current_getting_cooked_plus",
        "hot_dog_damage_allowed",
        "adjusted_xhr_per_bbe_allowed",
        "hot_dog_hr_capable_rate",
        "hot_dog_hr_capable_bbe",
    ]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def terminal_bbe_from_pitches(pitches: pd.DataFrame) -> pd.DataFrame:
    frame = pitches.copy()
    events = frame.get("events", pd.Series("", index=frame.index)).astype("string").str.strip()
    frame = frame[events.notna() & events.ne("")].copy()
    frame = frame[frame["pitcher"].notna() & frame["batter"].notna()].copy()
    frame = frame[frame["launch_speed"].notna() & frame["launch_angle"].notna()].copy()
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["batter_id"] = pd.to_numeric(frame["batter"], errors="coerce").astype("Int64")
    frame = frame.sort_values(["game_pk", "at_bat_number", "pitch_number"])
    frame = frame.drop_duplicates(["game_pk", "at_bat_number", "pitcher_id"], keep="last")
    frame["is_hr"] = frame["events"].astype("string").str.lower().eq("home_run")
    frame["is_barrel"] = pd.to_numeric(frame["launch_speed_angle"], errors="coerce").eq(6)
    frame["is_hr_window_thunder"] = frame["launch_speed"].ge(105) & frame["launch_angle"].between(25, 40, inclusive="both")
    return frame


def build_role_context(pitches: pd.DataFrame) -> pd.DataFrame:
    frame = pitches.dropna(subset=["game_pk", "pitcher"]).copy()
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["game_pk"] = pd.to_numeric(frame["game_pk"], errors="coerce").astype("Int64")
    frame["at_bat_number"] = pd.to_numeric(frame["at_bat_number"], errors="coerce")
    frame["pitch_number"] = pd.to_numeric(frame["pitch_number"], errors="coerce")
    frame["inning_topbot"] = frame["inning_topbot"].astype("string").str.lower()
    frame["pitching_team"] = pd.NA
    frame.loc[frame["inning_topbot"].eq("top"), "pitching_team"] = frame.loc[frame["inning_topbot"].eq("top"), "home_team"]
    frame.loc[frame["inning_topbot"].eq("bot"), "pitching_team"] = frame.loc[frame["inning_topbot"].eq("bot"), "away_team"]
    frame = frame.dropna(subset=["pitcher_id", "game_pk", "pitching_team"])
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id", "role", "appearances", "games_started"])
    appearances = frame.groupby("pitcher_id")["game_pk"].nunique().rename("appearances")
    starters = (
        frame.sort_values(["game_pk", "pitching_team", "at_bat_number", "pitch_number"])
        .drop_duplicates(["game_pk", "pitching_team"], keep="first")
        .groupby("pitcher_id")
        .size()
        .rename("games_started")
    )
    roles = pd.concat([appearances, starters], axis=1).fillna(0).reset_index()
    roles["appearances"] = roles["appearances"].astype(int)
    roles["games_started"] = roles["games_started"].astype(int)
    roles["role"] = roles.apply(
        lambda row: "SP" if row["games_started"] >= max(1, row["appearances"] / 2) else "RP",
        axis=1,
    )
    return roles


def join_hrt_to_bbe(details: pd.DataFrame, bbe: pd.DataFrame) -> pd.DataFrame:
    if details.empty or bbe.empty:
        return pd.DataFrame()
    statcast = bbe.reset_index(names="bbe_id")[
        [
            "bbe_id",
            "game_date",
            "game_pk",
            "batter_id",
            "pitcher_id",
            "events",
            "hit_distance_sc",
            "launch_speed",
            "launch_angle",
            "hc_x",
            "hc_y",
            "stand",
        ]
    ].copy()
    left = details.reset_index(names="detail_id")
    merged = left.merge(
        statcast,
        on=["game_pk", "batter_id", "pitcher_id"],
        how="left",
        suffixes=("_detail", "_statcast"),
    )
    merged["distance_diff"] = (merged["hr_distance"] - merged["hit_distance_sc"]).abs()
    merged["ev_diff"] = (merged["exit_velocity"] - merged["launch_speed"]).abs()
    merged["la_diff"] = (merged["launch_angle_detail"] - merged["launch_angle_statcast"]).abs()
    candidates = merged[
        merged["distance_diff"].le(2)
        & merged["ev_diff"].le(0.6)
        & merged["la_diff"].le(1)
    ].copy()
    if candidates.empty:
        return candidates
    candidates["match_score"] = candidates["distance_diff"] + candidates["ev_diff"] + candidates["la_diff"]
    candidates = candidates.sort_values(["detail_id", "match_score"])
    candidates = candidates.drop_duplicates("detail_id", keep="first")
    candidates = candidates.drop_duplicates("bbe_id", keep="first")
    return candidates


def add_lbi_event_scores(joined: pd.DataFrame) -> pd.DataFrame:
    if joined.empty:
        return joined.copy()
    events, _cells = add_lbi_v14_event_columns(
        joined,
        standard_parks_col="ct",
        result_col="result",
        ev_col="exit_velocity",
        distance_col="hr_distance",
        launch_angle_col="launch_angle_detail",
        hc_x_col="hc_x",
        hc_y_col="hc_y",
        stand_col="stand",
    )
    if events.empty:
        return events
    thump_mean = float(events["thump_evt"].mean())
    improb_mean = float(events["improb_evt"].mean())
    events["lbi_thump_event_plus"] = plus_scale(events["thump_evt"], thump_mean)
    events["lbi_artistry_event_plus"] = plus_scale(events["improb_evt"], improb_mean)
    events["lbi_event_severity_plus"] = 0.5 * events["lbi_thump_event_plus"] + 0.5 * events["lbi_artistry_event_plus"]
    return events


def aggregate_bbe(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id"])
    grouped = frame.groupby("pitcher_id", observed=True).agg(
        **{
            f"{prefix}_bbe": ("pitcher_id", "size"),
            f"{prefix}_hr": ("is_hr", "sum"),
            f"{prefix}_barrels": ("is_barrel", "sum"),
            f"{prefix}_hr_window_thunder": ("is_hr_window_thunder", "sum"),
            f"{prefix}_avg_ev": ("launch_speed", "mean"),
        }
    )
    return grouped.reset_index()


def aggregate_lbi(events: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["pitcher_id"])
    grouped = events.groupby("pitcher_id", observed=True).agg(
        **{
            f"{prefix}_lbi_events": ("pitcher_id", "size"),
            f"{prefix}_lbi_actual_hr_events": ("result_norm", lambda values: int(values.astype("string").str.lower().eq("home_run").sum())),
            f"{prefix}_lbi_robbed_events": ("lbi_v14_eligibility_reason", lambda values: int((values == "non_hr_standard_parks_8_plus").sum())),
            f"{prefix}_lbi_severity_sum": ("lbi_event_severity_plus", "sum"),
            f"{prefix}_lbi_severity_mean": ("lbi_event_severity_plus", "mean"),
            f"{prefix}_lbi_thump_mean": ("lbi_thump_event_plus", "mean"),
            f"{prefix}_lbi_artistry_mean": ("lbi_artistry_event_plus", "mean"),
        }
    )
    return grouped.reset_index()


def add_rate_columns(rows: pd.DataFrame, prefix: str) -> pd.DataFrame:
    out = rows.copy()
    out[f"{prefix}_hr_per_bbe"] = out[f"{prefix}_hr"] / out[f"{prefix}_bbe"].where(out[f"{prefix}_bbe"].gt(0))
    out[f"{prefix}_barrel_rate"] = out[f"{prefix}_barrels"] / out[f"{prefix}_bbe"].where(out[f"{prefix}_bbe"].gt(0))
    out[f"{prefix}_thunder_rate"] = out[f"{prefix}_hr_window_thunder"] / out[f"{prefix}_bbe"].where(out[f"{prefix}_bbe"].gt(0))
    out[f"{prefix}_lbi_event_rate"] = out[f"{prefix}_lbi_events"] / out[f"{prefix}_bbe"].where(out[f"{prefix}_bbe"].gt(0))
    out[f"{prefix}_lbi_per_100_bbe"] = out[f"{prefix}_lbi_severity_sum"] / out[f"{prefix}_bbe"].where(out[f"{prefix}_bbe"].gt(0))
    return out


def add_season_relative_scores(rows: pd.DataFrame, min_lbi_events: int) -> pd.DataFrame:
    out = rows.copy()
    for season, index in out.groupby("season").groups.items():
        idx = list(index)
        season_rows = out.loc[idx]
        bbe_total = season_rows["full_bbe"].sum()
        hr_rate = season_rows["full_hr"].sum() / bbe_total if bbe_total else math.nan
        barrel_rate = season_rows["full_barrels"].sum() / bbe_total if bbe_total else math.nan
        thunder_rate = season_rows["full_hr_window_thunder"].sum() / bbe_total if bbe_total else math.nan
        lbi_event_rate = season_rows["full_lbi_events"].sum() / bbe_total if bbe_total else math.nan
        lbi_per_bbe = season_rows["full_lbi_severity_sum"].sum() / bbe_total if bbe_total else math.nan
        severity_pool = season_rows.loc[season_rows["full_lbi_events"].ge(min_lbi_events), "full_lbi_severity_mean"]
        severity_mean = float(severity_pool.mean()) if len(severity_pool.dropna()) else math.nan
        avg_ev_mean = float(season_rows["full_avg_ev"].dropna().mean()) if len(season_rows["full_avg_ev"].dropna()) else math.nan

        out.loc[idx, "actual_hr_per_bbe_plus"] = plus_scale(season_rows["full_hr_per_bbe"], hr_rate)
        out.loc[idx, "barrel_rate_plus"] = plus_scale(season_rows["full_barrel_rate"], barrel_rate)
        out.loc[idx, "thunder_rate_plus"] = plus_scale(season_rows["full_thunder_rate"], thunder_rate)
        out.loc[idx, "lbi_event_rate_plus"] = plus_scale(season_rows["full_lbi_event_rate"], lbi_event_rate)
        out.loc[idx, "lbi_per_bbe_plus"] = plus_scale(season_rows["full_lbi_per_100_bbe"], lbi_per_bbe)
        out.loc[idx, "lbi_severity_per_event_plus"] = plus_scale(season_rows["full_lbi_severity_mean"], severity_mean)
        out.loc[idx, "avg_ev_plus"] = plus_scale(season_rows["full_avg_ev"], avg_ev_mean)
        out.loc[idx, "lbi_blend_plus"] = plus_scale(
            season_rows["full_lbi_event_rate"] * season_rows["full_lbi_severity_mean"],
            lbi_event_rate * severity_mean if pd.notna(lbi_event_rate) and pd.notna(severity_mean) else math.nan,
        )
        out.loc[idx, "season_lg_hr_per_bbe"] = hr_rate
        out.loc[idx, "season_lg_lbi_event_rate"] = lbi_event_rate
        out.loc[idx, "season_lg_lbi_severity"] = severity_mean
    return out


def build_season(season: int, min_lbi_events: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    print(f"Reading {season}...")
    pitches = read_pitch_season(season)
    details = read_hrt_details(season)
    bbe = terminal_bbe_from_pitches(pitches)
    joined = join_hrt_to_bbe(details, bbe)
    lbi_events = add_lbi_event_scores(joined)
    bbe_stats = aggregate_bbe(bbe, "full")
    lbi_stats = aggregate_lbi(lbi_events, "full")
    rows = bbe_stats.merge(lbi_stats, on="pitcher_id", how="left")
    rows = rows.merge(build_role_context(pitches), on="pitcher_id", how="left")
    rows = rows.merge(load_hot_dog(season), on=["pitcher_id"], how="left")
    rows["season"] = season
    rows["role"] = rows["role"].fillna("UNK")
    for column in [
        "full_lbi_events",
        "full_lbi_actual_hr_events",
        "full_lbi_robbed_events",
        "full_lbi_severity_sum",
        "full_lbi_severity_mean",
        "full_lbi_thump_mean",
        "full_lbi_artistry_mean",
    ]:
        if column in rows:
            rows[column] = rows[column].fillna(0 if column.endswith(("events", "sum")) else np.nan)
    rows["pitcher"] = rows["pitcher_hot_dog"].fillna(rows["pitcher_id"].astype("string"))
    rows["team"] = rows["team_hot_dog"].fillna("")

    dates = pd.to_datetime(bbe["game_date"], errors="coerce")
    midpoint = dates.min() + (dates.max() - dates.min()) / 2
    bbe = bbe.assign(split=np.where(dates.le(midpoint), "h1", "h2"))
    event_dates = pd.to_datetime(lbi_events["game_date_statcast"] if "game_date_statcast" in lbi_events else lbi_events["game_date"], errors="coerce")
    lbi_events = lbi_events.assign(split=np.where(event_dates.le(midpoint), "h1", "h2"))
    for prefix in ["h1", "h2"]:
        rows = rows.merge(aggregate_bbe(bbe[bbe["split"].eq(prefix)], prefix), on="pitcher_id", how="left")
        rows = rows.merge(aggregate_lbi(lbi_events[lbi_events["split"].eq(prefix)], prefix), on="pitcher_id", how="left")
        for column in [column for column in rows.columns if column.startswith(f"{prefix}_")]:
            if column.endswith(("bbe", "hr", "barrels", "thunder", "events", "sum")):
                rows[column] = rows[column].fillna(0)
        rows = add_rate_columns(rows, prefix)

    rows = add_rate_columns(rows, "full")
    coverage = {
        "season": season,
        "pitchRows": int(len(pitches)),
        "terminalBbe": int(len(bbe)),
        "hrtDetailRows": int(len(details)),
        "hrtJoinedRows": int(len(joined)),
        "hrtJoinRate": float(len(joined) / len(details)) if len(details) else 0,
        "lbiEligibleEvents": int(len(lbi_events)),
        "lbiActualHrEvents": int(lbi_events["result_norm"].astype("string").str.lower().eq("home_run").sum()) if not lbi_events.empty else 0,
        "lbiRobbedEvents": int((lbi_events["lbi_v14_eligibility_reason"] == "non_hr_standard_parks_8_plus").sum()) if not lbi_events.empty else 0,
        "pitcherSeasons": int(rows["pitcher_id"].nunique()),
        "qualifiedBbe": int(rows["full_bbe"].ge(MIN_BBE).sum()),
        "qualifiedBbeAndLbiEvents": int((rows["full_bbe"].ge(MIN_BBE) & rows["full_lbi_events"].ge(min_lbi_events)).sum()),
        "hotDogRowsJoined": int(rows["current_getting_cooked_plus"].notna().sum()),
    }
    return rows, coverage


def build_distinctness(pool: pd.DataFrame) -> pd.DataFrame:
    candidates = [
        ("Current Getting Cooked composite", "current_getting_cooked_plus"),
        ("HR-capable/LBI events per BBE", "lbi_event_rate_plus"),
        ("Inverted LBI severity per event", "lbi_severity_per_event_plus"),
        ("Inverted LBI per BBE blend", "lbi_per_bbe_plus"),
        ("Rate x severity blend", "lbi_blend_plus"),
    ]
    targets = [
        ("HR-capable/LBI events per BBE", "lbi_event_rate_plus"),
        ("Current Getting Cooked composite", "current_getting_cooked_plus"),
        ("Barrel% allowed", "barrel_rate_plus"),
        ("Adjusted xHR/BBE allowed", "adjusted_xhr_per_bbe_allowed"),
        ("Actual HR/BBE", "actual_hr_per_bbe_plus"),
        ("HR-window Thunder", "thunder_rate_plus"),
    ]
    rows = []
    scopes = [("ALL", pool), ("SP", pool[pool["role"].eq("SP")]), ("RP", pool[pool["role"].eq("RP")])]
    for candidate_label, candidate_col in candidates:
        for target_label, target_col in targets:
            if candidate_col == target_col:
                continue
            for scope, frame in scopes:
                rows.append(
                    {
                        "candidate": candidate_label,
                        "target": target_label,
                        "split": scope,
                        **safe_corr(frame, candidate_col, target_col),
                    }
                )
    return pd.DataFrame(rows)


def consecutive_pairs(pool: pd.DataFrame) -> pd.DataFrame:
    left = pool.copy()
    right = pool.copy()
    left["future_season"] = left["season"] + 1
    return left.merge(
        right,
        left_on=["pitcher_id", "future_season"],
        right_on=["pitcher_id", "season"],
        suffixes=("_current", "_future"),
    )


def build_stability(pool: pd.DataFrame, pairs: pd.DataFrame, min_half_bbe: int) -> pd.DataFrame:
    metrics = [
        ("Current Getting Cooked composite", "current_getting_cooked_plus"),
        ("HR-capable/LBI events per BBE", "lbi_event_rate_plus"),
        ("Inverted LBI severity per event", "lbi_severity_per_event_plus"),
        ("Inverted LBI per BBE blend", "lbi_per_bbe_plus"),
        ("Rate x severity blend", "lbi_blend_plus"),
        ("Actual HR/BBE", "actual_hr_per_bbe_plus"),
        ("Barrel% allowed", "barrel_rate_plus"),
        ("HR-window Thunder", "thunder_rate_plus"),
    ]
    rows = []
    for label, column in metrics:
        for split, frame in [("ALL", pairs), ("SP", pairs[pairs["role_current"].eq("SP")]), ("RP", pairs[pairs["role_current"].eq("RP")])]:
            rows.append({"test": "YoY", "metric": label, "split": split, **safe_corr(frame, f"{column}_current", f"{column}_future")})

    half = pool[(pool["h1_bbe"] >= min_half_bbe) & (pool["h2_bbe"] >= min_half_bbe)].copy()
    half_metrics = [
        ("HR-capable/LBI events per BBE", "lbi_event_rate"),
        ("Inverted LBI severity per event", "lbi_severity_mean"),
        ("Inverted LBI per BBE blend", "lbi_per_100_bbe"),
        ("Actual HR/BBE", "hr_per_bbe"),
        ("Barrel% allowed", "barrel_rate"),
        ("HR-window Thunder", "thunder_rate"),
    ]
    for label, suffix in half_metrics:
        for split, frame in [("ALL", half), ("SP", half[half["role"].eq("SP")]), ("RP", half[half["role"].eq("RP")])]:
            rows.append({"test": "Split-half", "metric": label, "split": split, **safe_corr(frame, f"h1_{suffix}", f"h2_{suffix}")})
    return pd.DataFrame(rows)


def build_future_validity(pairs: pd.DataFrame) -> pd.DataFrame:
    predictors = [
        ("Current Getting Cooked composite", "current_getting_cooked_plus_current"),
        ("HR-capable/LBI events per BBE", "lbi_event_rate_plus_current"),
        ("Inverted LBI severity per event", "lbi_severity_per_event_plus_current"),
        ("Inverted LBI per BBE blend", "lbi_per_bbe_plus_current"),
        ("Rate x severity blend", "lbi_blend_plus_current"),
        ("Actual HR/BBE", "actual_hr_per_bbe_plus_current"),
        ("Barrel% allowed", "barrel_rate_plus_current"),
        ("Adjusted xHR/BBE allowed", "adjusted_xhr_per_bbe_allowed_current"),
        ("HR-window Thunder", "thunder_rate_plus_current"),
    ]
    targets = [
        ("future actual HR/BBE", "full_hr_per_bbe_future"),
        ("future barrel% allowed", "full_barrel_rate_future"),
        ("future LBI event rate", "full_lbi_event_rate_future"),
        ("future LBI per BBE blend", "full_lbi_per_100_bbe_future"),
    ]
    rows = []
    for predictor_label, predictor in predictors:
        for target_label, target in targets:
            for split, frame in [("ALL", pairs), ("SP", pairs[pairs["role_current"].eq("SP")]), ("RP", pairs[pairs["role_current"].eq("RP")])]:
                rows.append(
                    {
                        "predictor": predictor_label,
                        "target": target_label,
                        "split": split,
                        **safe_corr(frame, predictor, target),
                    }
                )
    return pd.DataFrame(rows)


def build_rank_overlap(pool: pd.DataFrame, top_n: int) -> pd.DataFrame:
    metrics = [
        ("Current Getting Cooked composite", "current_getting_cooked_plus"),
        ("HR-capable/LBI events per BBE", "lbi_event_rate_plus"),
        ("Inverted LBI severity per event", "lbi_severity_per_event_plus"),
        ("Inverted LBI per BBE blend", "lbi_per_bbe_plus"),
        ("Rate x severity blend", "lbi_blend_plus"),
    ]
    rows = []
    for season, frame in pool.groupby("season"):
        n = min(top_n, len(frame))
        sets = {
            label: set(frame.nlargest(n, column)["pitcher"].astype(str))
            for label, column in metrics
            if column in frame and frame[column].notna().sum() >= n
        }
        for left_label, left_set in sets.items():
            for right_label, right_set in sets.items():
                if left_label >= right_label:
                    continue
                overlap = len(left_set & right_set)
                rows.append(
                    {
                        "season": season,
                        "left": left_label,
                        "right": right_label,
                        "topN": n,
                        "overlap": overlap,
                        "overlapPct": overlap / n if n else math.nan,
                    }
                )
    return pd.DataFrame(rows)


def build_case_studies(pool: pd.DataFrame, latest_season: int, top_n: int) -> pd.DataFrame:
    current = pool[pool["season"].eq(latest_season)].copy()
    if current.empty:
        return current
    current["rate_rank"] = current["lbi_event_rate_plus"].rank(method="min", ascending=False)
    current["severity_rank"] = current["lbi_severity_per_event_plus"].rank(method="min", ascending=False)
    current["blend_rank"] = current["lbi_per_bbe_plus"].rank(method="min", ascending=False)
    high_severity_lower_rate = current[
        current["lbi_severity_per_event_plus"].ge(current["lbi_severity_per_event_plus"].quantile(0.75))
        & current["lbi_event_rate_plus"].le(current["lbi_event_rate_plus"].quantile(0.50))
    ].nlargest(top_n, "lbi_severity_per_event_plus").assign(caseType="High severity, lower frequency")
    high_rate_lower_severity = current[
        current["lbi_event_rate_plus"].ge(current["lbi_event_rate_plus"].quantile(0.75))
        & current["lbi_severity_per_event_plus"].le(current["lbi_severity_per_event_plus"].quantile(0.50))
    ].nlargest(top_n, "lbi_event_rate_plus").assign(caseType="High frequency, lower severity")
    top_blend = current.nlargest(top_n, "lbi_per_bbe_plus").assign(caseType="Top inverted-LBI per BBE")
    columns = [
        "caseType",
        "season",
        "pitcher",
        "team",
        "role",
        "full_bbe",
        "full_lbi_events",
        "full_hr",
        "current_getting_cooked_plus",
        "lbi_event_rate_plus",
        "lbi_severity_per_event_plus",
        "lbi_per_bbe_plus",
        "lbi_blend_plus",
        "actual_hr_per_bbe_plus",
        "barrel_rate_plus",
        "adjusted_xhr_per_bbe_allowed",
        "rate_rank",
        "severity_rank",
        "blend_rank",
    ]
    return pd.concat([high_severity_lower_rate, high_rate_lower_severity, top_blend], ignore_index=True)[columns]


def format_number(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def markdown_table(frame: pd.DataFrame, columns: list[tuple[str, str]], limit: int | None = None) -> str:
    shown = frame.head(limit) if limit is not None else frame
    header = "| " + " | ".join(label for _key, label in columns) + " |"
    divider = "| " + " | ".join("---" for _key, _label in columns) + " |"
    rows = [header, divider]
    for _, row in shown.iterrows():
        values = []
        for key, _label in columns:
            value = row.get(key)
            if isinstance(value, (float, np.floating)):
                values.append(format_number(value))
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def lookup_corr(table: pd.DataFrame, candidate: str, target: str, split: str = "ALL") -> pd.Series | None:
    rows = table[table["candidate"].eq(candidate) & table["target"].eq(target) & table["split"].eq(split)]
    return rows.iloc[0] if not rows.empty else None


def lookup_future(table: pd.DataFrame, predictor: str, target: str = "future actual HR/BBE", split: str = "ALL") -> pd.Series | None:
    rows = table[table["predictor"].eq(predictor) & table["target"].eq(target) & table["split"].eq(split)]
    return rows.iloc[0] if not rows.empty else None


def lookup_stability(table: pd.DataFrame, test: str, metric: str, split: str = "ALL") -> pd.Series | None:
    rows = table[table["test"].eq(test) & table["metric"].eq(metric) & table["split"].eq(split)]
    return rows.iloc[0] if not rows.empty else None


def write_report(
    path: Path,
    coverage: pd.DataFrame,
    pool: pd.DataFrame,
    distinctness: pd.DataFrame,
    stability: pd.DataFrame,
    future: pd.DataFrame,
    overlap: pd.DataFrame,
    cases: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    latest = int(pool["season"].max()) if not pool.empty else max(args.seasons)
    severity_vs_rate = lookup_corr(distinctness, "Inverted LBI severity per event", "HR-capable/LBI events per BBE")
    severity_vs_cooked = lookup_corr(distinctness, "Inverted LBI severity per event", "Current Getting Cooked composite")
    blend_vs_rate = lookup_corr(distinctness, "Inverted LBI per BBE blend", "HR-capable/LBI events per BBE")
    blend_vs_cooked = lookup_corr(distinctness, "Inverted LBI per BBE blend", "Current Getting Cooked composite")
    current_future = lookup_future(future, "Current Getting Cooked composite")
    rate_future = lookup_future(future, "HR-capable/LBI events per BBE")
    severity_future = lookup_future(future, "Inverted LBI severity per event")
    blend_future = lookup_future(future, "Inverted LBI per BBE blend")
    actual_future = lookup_future(future, "Actual HR/BBE")
    severity_yoy = lookup_stability(stability, "YoY", "Inverted LBI severity per event")
    rate_yoy = lookup_stability(stability, "YoY", "HR-capable/LBI events per BBE")
    blend_yoy = lookup_stability(stability, "YoY", "Inverted LBI per BBE blend")
    current_yoy = lookup_stability(stability, "YoY", "Current Getting Cooked composite")

    rate_future_r = float(rate_future["pearson"]) if rate_future is not None and pd.notna(rate_future["pearson"]) else math.nan
    current_future_r = float(current_future["pearson"]) if current_future is not None and pd.notna(current_future["pearson"]) else math.nan
    blend_future_r = float(blend_future["pearson"]) if blend_future is not None and pd.notna(blend_future["pearson"]) else math.nan
    severity_future_r = float(severity_future["pearson"]) if severity_future is not None and pd.notna(severity_future["pearson"]) else math.nan
    rate_yoy_r = float(rate_yoy["pearson"]) if rate_yoy is not None and pd.notna(rate_yoy["pearson"]) else math.nan
    current_yoy_r = float(current_yoy["pearson"]) if current_yoy is not None and pd.notna(current_yoy["pearson"]) else math.nan
    blend_vs_rate_r = float(blend_vs_rate["pearson"]) if blend_vs_rate is not None and pd.notna(blend_vs_rate["pearson"]) else math.nan

    if pd.notna(severity_future_r) and severity_future_r <= 0:
        verdict = (
            "Do not make inverted LBI severity per event the Getting Cooked formula. "
            "It is distinct and narratively useful, but the signal is too unstable and does not carry future HR/BBE."
        )
    elif pd.notna(blend_vs_rate_r) and blend_vs_rate_r >= 0.95:
        verdict = (
            "The inverted-LBI per-BBE blend is viable only as a frequency-driven simplification; "
            "it is effectively HR-capable/LBI-event rate with light severity seasoning."
        )
    elif pd.notna(rate_future_r) and pd.notna(current_future_r) and rate_future_r > current_future_r and rate_yoy_r >= current_yoy_r:
        verdict = (
            "The strongest improvement is to center Getting Cooked on LBI-eligible HR-capable contact rate, "
            "with severity as context rather than the headline formula."
        )
    elif pd.notna(blend_future_r) and pd.notna(current_future_r) and blend_future_r > current_future_r:
        verdict = (
            "The inverted-LBI blend is live, but its value is mostly the event-rate spine; "
            "severity should be treated as secondary context."
        )
    else:
        verdict = "Inverted LBI is useful context, but the diagnostic does not prove it improves the flagship formula."

    concise_distinct = distinctness[
        distinctness["split"].eq("ALL")
        & distinctness["candidate"].isin(
            ["Inverted LBI severity per event", "Inverted LBI per BBE blend", "Rate x severity blend"]
        )
        & distinctness["target"].isin(
            ["HR-capable/LBI events per BBE", "Current Getting Cooked composite", "Barrel% allowed", "Adjusted xHR/BBE allowed", "Actual HR/BBE"]
        )
    ].copy()
    concise_future = future[
        future["split"].eq("ALL")
        & future["target"].eq("future actual HR/BBE")
        & future["predictor"].isin(
            [
                "Current Getting Cooked composite",
                "HR-capable/LBI events per BBE",
                "Inverted LBI severity per event",
                "Inverted LBI per BBE blend",
                "Rate x severity blend",
                "Actual HR/BBE",
                "Barrel% allowed",
                "Adjusted xHR/BBE allowed",
            ]
        )
    ].copy()
    concise_stability = stability[
        stability["split"].eq("ALL")
        & stability["test"].eq("YoY")
        & stability["metric"].isin(
            [
                "Current Getting Cooked composite",
                "HR-capable/LBI events per BBE",
                "Inverted LBI severity per event",
                "Inverted LBI per BBE blend",
                "Rate x severity blend",
                "Actual HR/BBE",
                "Barrel% allowed",
            ]
        )
    ].copy()

    lines = [
        "# Getting Cooked inverted LBI diagnostic",
        "",
        "## Verdict",
        "",
        f"**{verdict}**",
        "",
        "The tested inversion uses LBI v1.4's physics-only gate: launch angle 14-50 degrees, actual HR with 1+ standard parks, plus non-HR contact with 8+ standard parks. It is terminal-BBE scoped and regular-season scoped.",
        "",
        f"Qualified pool: {len(pool):,} pitcher-seasons at {args.min_bbe}+ terminal BBE and {args.min_lbi_events}+ LBI-eligible events.",
        "",
        "## What Improved Means",
        "",
        "This diagnostic treats improvement as: distinct from plain HR-capable frequency, more stable or at least no noisier than the current rate story, and meaningfully related to future longball damage allowed. It does not optimize a production formula.",
        "",
        "## Coverage",
        "",
        markdown_table(
            coverage,
            [
                ("season", "Season"),
                ("terminalBbe", "Terminal BBE"),
                ("hrtDetailRows", "HRT rows"),
                ("hrtJoinedRows", "Joined"),
                ("hrtJoinRate", "Join%"),
                ("lbiEligibleEvents", "LBI events"),
                ("qualifiedBbeAndLbiEvents", "Qualified"),
                ("hotDogRowsJoined", "Hot Dog joined"),
            ],
        ),
        "",
        "## Distinctness",
        "",
        markdown_table(
            concise_distinct,
            [("candidate", "Candidate"), ("target", "Compared to"), ("n", "n"), ("pearson", "Pearson"), ("spearman", "Spearman")],
        ),
        "",
        "## Stability",
        "",
        markdown_table(
            concise_stability,
            [("metric", "Metric"), ("n", "n"), ("pearson", "YoY Pearson"), ("spearman", "YoY Spearman")],
        ),
        "",
        "## Future HR/BBE Validity",
        "",
        markdown_table(
            concise_future.sort_values("pearson", ascending=False),
            [("predictor", "Current predictor"), ("n", "n"), ("pearson", "Pearson"), ("spearman", "Spearman")],
        ),
        "",
        "## Top-25 Overlap",
        "",
        markdown_table(
            overlap[overlap["season"].eq(latest)].sort_values("overlapPct", ascending=False),
            [("left", "Left"), ("right", "Right"), ("topN", "Top N"), ("overlap", "Overlap"), ("overlapPct", "Overlap%")],
        ),
        "",
        f"## {latest} Case Studies",
        "",
        markdown_table(
            cases,
            [
                ("caseType", "Case"),
                ("pitcher", "Pitcher"),
                ("team", "Team"),
                ("role", "Role"),
                ("full_bbe", "BBE"),
                ("full_lbi_events", "LBI events"),
                ("current_getting_cooked_plus", "Cooked"),
                ("lbi_event_rate_plus", "Rate+"),
                ("lbi_severity_per_event_plus", "Severity+"),
                ("lbi_per_bbe_plus", "Per-BBE+"),
            ],
            limit=30,
        ),
        "",
        "## Quick Reads",
        "",
        f"- Severity vs HR-capable/LBI event frequency: r={format_number(severity_vs_rate['pearson']) if severity_vs_rate is not None else 'n/a'}.",
        f"- Severity vs current Getting Cooked: r={format_number(severity_vs_cooked['pearson']) if severity_vs_cooked is not None else 'n/a'}.",
        f"- Per-BBE inverted LBI blend vs HR-capable/LBI event frequency: r={format_number(blend_vs_rate['pearson']) if blend_vs_rate is not None else 'n/a'}.",
        f"- Per-BBE inverted LBI blend vs current Getting Cooked: r={format_number(blend_vs_cooked['pearson']) if blend_vs_cooked is not None else 'n/a'}.",
        f"- YoY severity stability: r={format_number(severity_yoy['pearson']) if severity_yoy is not None else 'n/a'}; rate stability: r={format_number(rate_yoy['pearson']) if rate_yoy is not None else 'n/a'}; blend stability: r={format_number(blend_yoy['pearson']) if blend_yoy is not None else 'n/a'}.",
        f"- Future HR/BBE: current Cooked r={format_number(current_future['pearson']) if current_future is not None else 'n/a'}, rate r={format_number(rate_future['pearson']) if rate_future is not None else 'n/a'}, severity r={format_number(severity_future['pearson']) if severity_future is not None else 'n/a'}, per-BBE blend r={format_number(blend_future['pearson']) if blend_future is not None else 'n/a'}, actual HR/BBE r={format_number(actual_future['pearson']) if actual_future is not None else 'n/a'}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    season_rows = []
    coverage_rows = []
    for season in args.seasons:
        rows, coverage = build_season(season, args.min_lbi_events)
        season_rows.append(rows)
        coverage_rows.append(coverage)

    all_rows = pd.concat(season_rows, ignore_index=True)
    all_rows = add_season_relative_scores(all_rows, args.min_lbi_events)
    pool = all_rows[
        all_rows["full_bbe"].ge(args.min_bbe)
        & all_rows["full_lbi_events"].ge(args.min_lbi_events)
    ].copy()
    pairs = consecutive_pairs(pool)

    coverage = pd.DataFrame(coverage_rows)
    distinctness = build_distinctness(pool)
    stability = build_stability(pool, pairs, args.min_half_bbe)
    future = build_future_validity(pairs)
    overlap = build_rank_overlap(pool, args.top_n)
    cases = build_case_studies(pool, max(args.seasons), args.top_n)

    prefix = args.output_dir / "getting_cooked_lbi_inversion"
    coverage.to_csv(prefix.with_name(prefix.name + "_coverage.csv"), index=False)
    all_rows.to_csv(prefix.with_name(prefix.name + "_pitcher_seasons.csv"), index=False)
    distinctness.to_csv(prefix.with_name(prefix.name + "_distinctness.csv"), index=False)
    stability.to_csv(prefix.with_name(prefix.name + "_stability.csv"), index=False)
    future.to_csv(prefix.with_name(prefix.name + "_future.csv"), index=False)
    overlap.to_csv(prefix.with_name(prefix.name + "_overlap.csv"), index=False)
    cases.to_csv(prefix.with_name(prefix.name + "_case_studies.csv"), index=False)
    report_path = prefix.with_name(prefix.name + "_report.md")
    write_report(report_path, coverage, pool, distinctness, stability, future, overlap, cases, args)

    print("\n=== Getting Cooked inverted LBI diagnostic ===")
    print(f"Pitcher-seasons: {len(all_rows):,}")
    print(f"Qualified pool: {len(pool):,}")
    print(f"Consecutive pairs: {len(pairs):,}")
    print(f"Report: {display_path(report_path)}")

    summary = future[future["split"].eq("ALL") & future["target"].eq("future actual HR/BBE")].copy()
    if not summary.empty:
        print("\nFuture HR/BBE correlations:")
        for _, row in summary.sort_values("pearson", ascending=False).iterrows():
            print(f"- {row['predictor']}: r={format_number(row['pearson'])}, rho={format_number(row['spearman'])}, n={int(row['n'])}")


if __name__ == "__main__":
    main()
