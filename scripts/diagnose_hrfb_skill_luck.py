#!/usr/bin/env python3
"""Diagnose whether park-neutral expected HR/FB is skill, luck flag, or clone.

This script is diagnostic-only. It reads existing Statcast pitch caches, existing
Home Run Tracker detail caches, and existing Hot Dog / Getting Cooked JSON. It
does not write production data.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_integrity import scope_to_regular_season


CACHE_DIR = Path("data/cache/longball-threat-backtest")
HOT_DOG_TEMPLATE = "public/data/hot-dog-index-{season}.json"
PITCH_TEMPLATE = "data/cache/longball-threat-backtest/statcast-pitches-{season}-{half}.csv"
HRT_TEMPLATE = "data/cache/longball-threat-backtest/hrt-details-{season}-adj_xhr.csv"

DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]
PITCH_USECOLS = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "player_name",
    "batter",
    "events",
    "description",
    "type",
    "bb_type",
    "launch_speed",
    "launch_angle",
    "launch_speed_angle",
    "hit_distance_sc",
    "home_team",
    "away_team",
    "inning_topbot",
]
HRT_USECOLS = [
    "game_pk",
    "batter_id",
    "pitcher_id",
    "result",
    "game_date",
    "ct",
    "exit_velocity",
    "launch_angle",
    "hr_distance",
]

FLY_BALL_LA_MIN = 25.0
POPUP_LA_MIN = 50.0
LOW_EV_FB_MAX = 85.0
MIN_FLY_BALLS = 150
MIN_HALF_FLY_BALLS = 75
CLONE_R = 0.90
SKILL_R = 0.50


@dataclass(frozen=True)
class SeasonArtifacts:
    season: int
    rows: pd.DataFrame
    coverage: dict[str, Any]


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def safe_corr(frame: pd.DataFrame, x: str, y: str) -> float | None:
    cols = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(cols) < 3 or cols[x].nunique() < 2 or cols[y].nunique() < 2:
        return None
    return float(cols[x].corr(cols[y]))


def safe_divide(num: pd.Series | float, den: pd.Series | float) -> pd.Series | float:
    return num / den.where(den.gt(0)) if isinstance(den, pd.Series) else (num / den if den else math.nan)


def plus_scale(values: pd.Series, league_value: float, *, inverse: bool = False) -> pd.Series:
    numeric = to_numeric(values)
    if not league_value or pd.isna(league_value):
        return pd.Series(pd.NA, index=values.index)
    if inverse:
        return 100 * league_value / numeric.where(numeric.gt(0))
    return 100 * numeric / league_value


def read_pitch_season(season: int) -> pd.DataFrame:
    frames = []
    for half in ["first", "second"]:
        path = Path(PITCH_TEMPLATE.format(season=season, half=half))
        if not path.exists():
            raise FileNotFoundError(f"Missing pitch cache: {path}")
        frames.append(pd.read_csv(path, usecols=lambda column: column in PITCH_USECOLS))
    pitches = pd.concat(frames, ignore_index=True)
    for column in [
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher",
        "batter",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "hit_distance_sc",
    ]:
        if column in pitches.columns:
            pitches[column] = to_numeric(pitches[column])
    pitches = scope_to_regular_season(pitches, season)
    return pitches


def read_hrt_details(season: int) -> pd.DataFrame:
    path = Path(HRT_TEMPLATE.format(season=season))
    if not path.exists():
        raise FileNotFoundError(f"Missing HRT detail cache: {path}")
    details = pd.read_csv(path, usecols=lambda column: column in HRT_USECOLS)
    for column in ["game_pk", "batter_id", "pitcher_id", "ct", "exit_velocity", "launch_angle", "hr_distance"]:
        if column in details.columns:
            details[column] = to_numeric(details[column])
    return scope_to_regular_season(details, season)


def load_getting_cooked(season: int) -> pd.DataFrame:
    path = Path(HOT_DOG_TEMPLATE.format(season=season))
    if not path.exists():
        raise FileNotFoundError(f"Missing Hot Dog JSON: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = pd.DataFrame(payload.get("pitchers", []))
    if rows.empty:
        return pd.DataFrame(columns=["season", "pitcher_id", "getting_cooked_plus", "getting_cooked_raw"])
    rows["season"] = season
    rows["pitcher_id"] = to_numeric(rows["pitcherId"]).astype("Int64")
    raw = to_numeric(rows.get("gettingCookedPer100Bbe", rows.get("cookedPer100Bbe")))
    rows["getting_cooked_raw"] = raw
    rows["getting_cooked_plus"] = to_numeric(rows.get("cookedPlus", pd.Series(pd.NA, index=rows.index)))
    missing_plus = rows["getting_cooked_plus"].isna()
    league_raw = raw.dropna().mean()
    if league_raw and pd.notna(league_raw):
        rows.loc[missing_plus, "getting_cooked_plus"] = 100 * raw.loc[missing_plus] / league_raw
    keep = [
        "season",
        "pitcher_id",
        "pitcher",
        "pitcherRole",
        "getting_cooked_raw",
        "getting_cooked_plus",
        "adjustedXhrPerBbeAllowed",
        "hotDogIndex",
    ]
    return rows[[column for column in keep if column in rows.columns]].copy()


def build_role_context(pitches: pd.DataFrame) -> pd.DataFrame:
    frame = pitches.dropna(subset=["game_pk", "pitcher"]).copy()
    frame["pitcher_id"] = to_numeric(frame["pitcher"]).astype("Int64")
    frame["game_pk"] = to_numeric(frame["game_pk"]).astype("Int64")
    frame["at_bat_number"] = to_numeric(frame["at_bat_number"])
    frame["pitch_number"] = to_numeric(frame["pitch_number"])
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


def bbe_from_pitches(pitches: pd.DataFrame) -> pd.DataFrame:
    bbe = pitches[pitches["pitcher"].notna() & pitches["launch_speed"].notna() & pitches["launch_angle"].notna()].copy()
    bbe["pitcher_id"] = to_numeric(bbe["pitcher"]).astype("Int64")
    bbe["batter_id"] = to_numeric(bbe["batter"]).astype("Int64")
    bbe["is_hr"] = bbe["events"].astype("string").str.lower().eq("home_run")
    bbe["is_barrel"] = to_numeric(bbe["launch_speed_angle"]).eq(6)
    bbe["is_fly_ball_la"] = to_numeric(bbe["launch_angle"]).ge(FLY_BALL_LA_MIN)
    bbe["is_popup_la"] = to_numeric(bbe["launch_angle"]).ge(POPUP_LA_MIN)
    bbe["is_low_ev_fly"] = bbe["is_fly_ball_la"] & to_numeric(bbe["launch_speed"]).le(LOW_EV_FB_MAX)
    return bbe


def join_hrt_to_bbe(details: pd.DataFrame, bbe: pd.DataFrame) -> pd.DataFrame:
    if details.empty or bbe.empty:
        return pd.DataFrame(columns=["bbe_id", "detail_xhr"])
    statcast = bbe.reset_index(names="bbe_id")[
        [
            "bbe_id",
            "game_pk",
            "batter_id",
            "pitcher_id",
            "hit_distance_sc",
            "launch_speed",
            "launch_angle",
        ]
    ].copy()
    left = details.reset_index(names="detail_id")
    merged = left.merge(
        statcast,
        on=["game_pk", "batter_id", "pitcher_id"],
        how="left",
    )
    merged["distance_diff"] = (merged["hr_distance"] - merged["hit_distance_sc"]).abs()
    merged["ev_diff"] = (merged["exit_velocity"] - merged["launch_speed"]).abs()
    merged["la_diff"] = (merged["launch_angle_x"] - merged["launch_angle_y"]).abs()
    candidates = merged[
        merged["distance_diff"].le(2)
        & merged["ev_diff"].le(0.6)
        & merged["la_diff"].le(1)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=["bbe_id", "detail_xhr"])
    candidates["match_score"] = candidates["distance_diff"] + candidates["ev_diff"] + candidates["la_diff"]
    candidates = candidates.sort_values(["detail_id", "match_score"]).drop_duplicates("detail_id", keep="first")
    candidates["detail_xhr"] = to_numeric(candidates["ct"]).fillna(0).clip(0, 30) / 30
    return candidates[["bbe_id", "detail_xhr"]]


def event_stats(frame: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby("pitcher_id").agg(
        bbe=("pitcher_id", "size"),
        fly_balls=("is_fly_ball_la", "sum"),
        actual_hr=("is_hr", "sum"),
        barrels=("is_barrel", "sum"),
        popup_fly=("is_popup_la", "sum"),
        low_ev_fly=("is_low_ev_fly", "sum"),
        fly_ev=("launch_speed", lambda s: s[frame.loc[s.index, "is_fly_ball_la"]].mean()),
        expected_hr_on_fb=("detail_xhr", lambda s: s[frame.loc[s.index, "is_fly_ball_la"]].sum()),
    ).reset_index()
    grouped = grouped.rename(columns={column: f"{prefix}_{column}" for column in grouped.columns if column != "pitcher_id"})
    return grouped


def terminal_pitch_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    frame = pitches[pitches["pitcher"].notna()].copy()
    frame["pitcher_id"] = to_numeric(frame["pitcher"]).astype("Int64")
    events = frame["events"].fillna("").astype(str).str.strip().str.lower()
    terminal = frame[events.ne("")].copy()
    if terminal.empty:
        return pd.DataFrame(columns=["pitcher_id", "pa", "strikeouts", "walks", "hbp"])
    terminal = (
        terminal.sort_values(["game_pk", "at_bat_number", "pitch_number"])
        .drop_duplicates(["game_pk", "at_bat_number", "pitcher_id"], keep="last")
    )
    ev = terminal["events"].fillna("").astype(str).str.lower()
    out = terminal.groupby("pitcher_id").size().rename("pa").reset_index()
    out = out.merge(ev.eq("strikeout").groupby(terminal["pitcher_id"]).sum().rename("strikeouts").reset_index(), on="pitcher_id", how="left")
    out = out.merge(ev.eq("walk").groupby(terminal["pitcher_id"]).sum().rename("walks").reset_index(), on="pitcher_id", how="left")
    out = out.merge(ev.eq("hit_by_pitch").groupby(terminal["pitcher_id"]).sum().rename("hbp").reset_index(), on="pitcher_id", how="left")
    return out.fillna(0)


def add_rates(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    out["actual_hrfb"] = out["full_actual_hr"] / out["full_fly_balls"].where(out["full_fly_balls"].gt(0))
    out["expected_hrfb"] = out["full_expected_hr_on_fb"] / out["full_fly_balls"].where(out["full_fly_balls"].gt(0))
    out["barrel_rate_allowed"] = out["full_barrels"] / out["full_bbe"].where(out["full_bbe"].gt(0))
    out["popup_rate"] = out["full_popup_fly"] / out["full_fly_balls"].where(out["full_fly_balls"].gt(0))
    out["low_ev_fly_rate"] = out["full_low_ev_fly"] / out["full_fly_balls"].where(out["full_fly_balls"].gt(0))
    return out


def season_relative(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    league_actual_hrfb = out["full_actual_hr"].sum() / out["full_fly_balls"].sum()
    league_expected_hrfb = out["full_expected_hr_on_fb"].sum() / out["full_fly_balls"].sum()
    league_barrel = out["full_barrels"].sum() / out["full_bbe"].sum()
    league_popup = out["full_popup_fly"].sum() / out["full_fly_balls"].sum()
    league_low_ev = out["full_low_ev_fly"].sum() / out["full_fly_balls"].sum()
    league_fly_ev = out.loc[out["full_fly_balls"].gt(0), "full_fly_ev"].mean()

    out["actual_hrfb_plus"] = plus_scale(out["actual_hrfb"], league_actual_hrfb)
    out["expected_hrfb_plus"] = plus_scale(out["expected_hrfb"], league_expected_hrfb)
    out["barrel_rate_plus"] = plus_scale(out["barrel_rate_allowed"], league_barrel)
    out["popup_rate_plus"] = plus_scale(out["popup_rate"], league_popup)
    out["low_ev_fly_rate_plus"] = plus_scale(out["low_ev_fly_rate"], league_low_ev)
    out["weak_fly_plus"] = (out["popup_rate_plus"] + out["low_ev_fly_rate_plus"]) / 2
    out["fly_ev_plus"] = plus_scale(out["full_fly_ev"], league_fly_ev)
    out["hrfb_gap_plus"] = out["actual_hrfb_plus"] - out["expected_hrfb_plus"]
    out.attrs["league_actual_hrfb"] = float(league_actual_hrfb)
    out.attrs["league_expected_hrfb"] = float(league_expected_hrfb)
    return out


def add_xfip_proxy(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    league_hrfb = out["full_actual_hr"].sum() / out["full_fly_balls"].sum()
    expected_hr = out["full_fly_balls"] * league_hrfb
    numerator = 13 * expected_hr + 3 * (out["walks"].fillna(0) + out["hbp"].fillna(0)) - 2 * out["strikeouts"].fillna(0)
    out["xfip_proxy_rate"] = numerator / out["pa"].where(out["pa"].gt(0))
    league_proxy = out["xfip_proxy_rate"].dropna().mean()
    out["xfip_proxy_plus"] = plus_scale(out["xfip_proxy_rate"], league_proxy)
    return out


def build_season(season: int) -> SeasonArtifacts:
    print(f"Reading {season} Statcast pitch cache...")
    pitches = read_pitch_season(season)
    details = read_hrt_details(season)
    bbe = bbe_from_pitches(pitches)
    hrt_join = join_hrt_to_bbe(details, bbe)
    bbe = bbe.reset_index(names="bbe_id").merge(hrt_join, on="bbe_id", how="left")
    bbe["detail_xhr"] = bbe["detail_xhr"].fillna(0.0)

    full = event_stats(bbe, prefix="full")
    pa = terminal_pitch_stats(pitches)
    roles = build_role_context(pitches)
    cooked = load_getting_cooked(season)
    rows = full.merge(pa, on="pitcher_id", how="left").merge(roles, on="pitcher_id", how="left")
    rows = rows.merge(cooked, on=["season", "pitcher_id"], how="left") if "season" in rows.columns else rows
    rows["season"] = season
    if not cooked.empty:
        rows = rows.merge(
            cooked.drop(columns=[column for column in ["pitcher", "pitcherRole"] if column in cooked.columns]),
            on=["season", "pitcher_id"],
            how="left",
            suffixes=("", "_cooked"),
        )
    rows["role"] = rows["role"].fillna("UNK")
    rows = add_xfip_proxy(season_relative(add_rates(rows)))
    league_actual_hrfb = rows["full_actual_hr"].sum() / rows["full_fly_balls"].sum()
    league_expected_hrfb = rows["full_expected_hr_on_fb"].sum() / rows["full_fly_balls"].sum()

    dates = pd.to_datetime(bbe["game_date"], errors="coerce")
    midpoint = dates.min() + (dates.max() - dates.min()) / 2
    first = bbe[dates.le(midpoint)].copy()
    second = bbe[dates.gt(midpoint)].copy()
    halves = event_stats(first, prefix="h1").merge(event_stats(second, prefix="h2"), on="pitcher_id", how="outer")
    rows = rows.merge(halves, on="pitcher_id", how="left")
    for prefix in ["h1", "h2"]:
        rows[f"{prefix}_actual_hrfb"] = rows[f"{prefix}_actual_hr"] / rows[f"{prefix}_fly_balls"].where(rows[f"{prefix}_fly_balls"].gt(0))
        rows[f"{prefix}_expected_hrfb"] = rows[f"{prefix}_expected_hr_on_fb"] / rows[f"{prefix}_fly_balls"].where(rows[f"{prefix}_fly_balls"].gt(0))
        rows[f"{prefix}_popup_rate"] = rows[f"{prefix}_popup_fly"] / rows[f"{prefix}_fly_balls"].where(rows[f"{prefix}_fly_balls"].gt(0))
        rows[f"{prefix}_low_ev_fly_rate"] = rows[f"{prefix}_low_ev_fly"] / rows[f"{prefix}_fly_balls"].where(rows[f"{prefix}_fly_balls"].gt(0))

    coverage = {
        "season": season,
        "statcastRows": len(pitches),
        "bbeRows": len(bbe),
        "flyBalls": int(bbe["is_fly_ball_la"].sum()),
        "hrtDetailRowsRegular": len(details),
        "hrtJoinedRows": len(hrt_join),
        "hrtJoinRate": len(hrt_join) / len(details) if len(details) else 0,
        "gettingCookedPool": int(cooked["pitcher_id"].nunique()) if not cooked.empty else 0,
        "candidatePoolMinFb": int(rows["full_fly_balls"].ge(MIN_FLY_BALLS).sum()),
        "candidateAndCooked": int((rows["full_fly_balls"].ge(MIN_FLY_BALLS) & rows["getting_cooked_plus"].notna()).sum()),
        "leagueActualHrfb": float(league_actual_hrfb),
        "leagueExpectedHrfb": float(league_expected_hrfb),
    }
    return SeasonArtifacts(season=season, rows=rows, coverage=coverage)


def format_r(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:+.3f}"


def print_coverage(artifacts: list[SeasonArtifacts]) -> None:
    print("\n=== Part 0: candidate input coverage ===")
    print(f"Airborne/fly-ball definition: Statcast launch_angle >= {FLY_BALL_LA_MIN:.0f} degrees.")
    print(f"Pop-up definition: launch_angle >= {POPUP_LA_MIN:.0f} degrees among fly balls.")
    print(f"Low-EV fly definition: launch_speed <= {LOW_EV_FB_MAX:.0f} mph among fly balls.")
    print("Expected HR/FB source: existing HRT adjusted detail convention, ct / 30, restricted to fly balls.")
    print("Season | BBE | FB | HRT detail rows | HRT joined | join% | Cooked pool | FB>=150 | FB>=150 + Cooked | lg actual HR/FB | lg exp HR/FB")
    for item in artifacts:
        c = item.coverage
        print(
            f"{c['season']} | {c['bbeRows']:,} | {c['flyBalls']:,} | {c['hrtDetailRowsRegular']:,} | "
            f"{c['hrtJoinedRows']:,} | {c['hrtJoinRate']:.1%} | {c['gettingCookedPool']:,} | "
            f"{c['candidatePoolMinFb']:,} | {c['candidateAndCooked']:,} | "
            f"{c['leagueActualHrfb']:.1%} | {c['leagueExpectedHrfb']:.1%}"
        )


def print_distinctness(pool: pd.DataFrame) -> dict[str, bool]:
    print("\n=== Part 1: distinctness gate ===")
    print("Pool: pitcher-seasons with >=150 LA-defined fly balls and matching Getting Cooked row.")
    targets = [
        ("Getting Cooked", "getting_cooked_plus"),
        ("Barrel% allowed", "barrel_rate_plus"),
        ("xFIP proxy", "xfip_proxy_plus"),
        ("Actual HR/FB", "actual_hrfb_plus"),
    ]
    candidates = [
        ("Expected HR/FB", "expected_hrfb_plus"),
        ("Weak-fly combo", "weak_fly_plus"),
        ("Pop-up rate", "popup_rate_plus"),
        ("Low-EV fly rate", "low_ev_fly_rate_plus"),
    ]
    print("Candidate | Split | N | r vs Getting Cooked | r vs Barrel% | r vs xFIP proxy | r vs Actual HR/FB")
    gate = {"expected_clone": False, "expected_barrel_clone": False, "weak_clone": False, "weak_barrel_clone": False}
    for label, column in candidates:
        for split, frame in [("ALL", pool), ("SP", pool[pool["role"].eq("SP")]), ("RP", pool[pool["role"].eq("RP")])]:
            cors = [safe_corr(frame, column, target_col) for _target_label, target_col in targets]
            print(
                f"{label} | {split} | {len(frame):,} | "
                f"{format_r(cors[0])} | {format_r(cors[1])} | {format_r(cors[2])} | {format_r(cors[3])}"
            )
            if split == "ALL" and label == "Expected HR/FB":
                gate["expected_clone"] = bool(cors[0] is not None and abs(cors[0]) >= CLONE_R)
                gate["expected_barrel_clone"] = bool(cors[1] is not None and abs(cors[1]) >= CLONE_R)
            if split == "ALL" and label == "Weak-fly combo":
                gate["weak_clone"] = bool(cors[0] is not None and abs(cors[0]) >= CLONE_R)
                gate["weak_barrel_clone"] = bool(cors[1] is not None and abs(cors[1]) >= CLONE_R)
    return gate


def split_half_stability(pool: pd.DataFrame) -> pd.DataFrame:
    base = pool[(pool["h1_fly_balls"] >= MIN_HALF_FLY_BALLS) & (pool["h2_fly_balls"] >= MIN_HALF_FLY_BALLS)].copy()
    rows = []
    metrics = [
        ("Expected HR/FB", "expected_hrfb"),
        ("Fly-ball EV", "fly_ev"),
        ("Pop-up rate", "popup_rate"),
        ("Low-EV fly rate", "low_ev_fly_rate"),
        ("Actual HR/FB", "actual_hrfb"),
    ]
    for label, suffix in metrics:
        for split, frame in [("ALL", base), ("SP", base[base["role"].eq("SP")]), ("RP", base[base["role"].eq("RP")])]:
            rows.append(
                {
                    "metric": label,
                    "split": split,
                    "n": len(frame),
                    "r": safe_corr(frame, f"h1_{suffix}", f"h2_{suffix}"),
                }
            )
    return pd.DataFrame(rows)


def yoy_stability(pool: pd.DataFrame) -> pd.DataFrame:
    base = pool[pool["full_fly_balls"] >= MIN_FLY_BALLS].copy()
    merged = base.merge(
        base,
        left_on=["pitcher_id", "next_season"],
        right_on=["pitcher_id", "season"],
        suffixes=("_t", "_next"),
    )
    rows = []
    metrics = [
        ("Expected HR/FB", "expected_hrfb_plus"),
        ("Fly-ball EV", "fly_ev_plus"),
        ("Pop-up rate", "popup_rate_plus"),
        ("Low-EV fly rate", "low_ev_fly_rate_plus"),
        ("Weak-fly combo", "weak_fly_plus"),
        ("Actual HR/FB", "actual_hrfb_plus"),
    ]
    for label, column in metrics:
        for split, frame in [("ALL", merged), ("SP", merged[merged["role_t"].eq("SP")]), ("RP", merged[merged["role_t"].eq("RP")])]:
            rows.append(
                {
                    "metric": label,
                    "split": split,
                    "n": len(frame),
                    "r": safe_corr(frame, f"{column}_t", f"{column}_next"),
                }
            )
    return pd.DataFrame(rows)


def print_stability(pool: pd.DataFrame) -> None:
    print("\n=== Part 2: stability ===")
    split = split_half_stability(pool)
    print(f"Split-half gate: >= {MIN_HALF_FLY_BALLS} fly balls in each half.")
    print("Metric | Split | N | split-half r")
    for row in split.to_dict("records"):
        print(f"{row['metric']} | {row['split']} | {row['n']:,} | {format_r(row['r'])}")

    yoy = yoy_stability(pool)
    print(f"\nYear-over-year gate: >= {MIN_FLY_BALLS} fly balls in both seasons.")
    print("Metric | Split | N | YoY r")
    for row in yoy.to_dict("records"):
        print(f"{row['metric']} | {row['split']} | {row['n']:,} | {format_r(row['r'])}")


def consecutive_pool(pool: pd.DataFrame) -> pd.DataFrame:
    base = pool[pool["full_fly_balls"] >= MIN_FLY_BALLS].copy()
    return base.merge(
        base,
        left_on=["pitcher_id", "next_season"],
        right_on=["pitcher_id", "season"],
        suffixes=("_t", "_next"),
    )


def residual_corr(frame: pd.DataFrame, x: str, y: str, controls: list[str]) -> float | None:
    if len(controls) != 1:
        return None
    cols = frame[[x, y, *controls]].apply(pd.to_numeric, errors="coerce").dropna()
    cols = cols.replace([math.inf, -math.inf], pd.NA).dropna()
    if len(cols) < 5 or cols[x].nunique() < 2 or cols[y].nunique() < 2:
        return None
    control = controls[0]
    r_xy = safe_corr(cols, x, y)
    r_xc = safe_corr(cols, x, control)
    r_yc = safe_corr(cols, y, control)
    if r_xy is None or r_xc is None or r_yc is None:
        return None
    denominator = math.sqrt((1 - r_xc**2) * (1 - r_yc**2))
    if not denominator:
        return None
    return float((r_xy - r_xc * r_yc) / denominator)


def flag_validity(pool: pd.DataFrame) -> dict[str, Any]:
    merged = consecutive_pool(pool)
    merged["future_change_actual_hrfb_plus"] = merged["actual_hrfb_plus_next"] - merged["actual_hrfb_plus_t"]
    expected_future_r = safe_corr(merged, "expected_hrfb_plus_t", "actual_hrfb_plus_next")
    actual_future_r = safe_corr(merged, "actual_hrfb_plus_t", "actual_hrfb_plus_next")
    weak_future_r = safe_corr(merged, "weak_fly_plus_t", "actual_hrfb_plus_next")
    weak_resid_future_r = residual_corr(
        merged,
        "weak_fly_plus_t",
        "actual_hrfb_plus_next",
        ["expected_hrfb_plus_t"],
    )
    gap_change_r = safe_corr(merged, "hrfb_gap_plus_t", "future_change_actual_hrfb_plus")
    gap_future_r = safe_corr(merged, "hrfb_gap_plus_t", "actual_hrfb_plus_next")

    q = merged["hrfb_gap_plus_t"].quantile([0.2, 0.8])
    negative_gap = merged[merged["hrfb_gap_plus_t"].le(q.loc[0.2])]
    positive_gap = merged[merged["hrfb_gap_plus_t"].ge(q.loc[0.8])]
    middle = merged[(merged["hrfb_gap_plus_t"].gt(q.loc[0.2])) & (merged["hrfb_gap_plus_t"].lt(q.loc[0.8]))]

    return {
        "n": len(merged),
        "expected_future_r": expected_future_r,
        "actual_future_r": actual_future_r,
        "weak_future_r": weak_future_r,
        "weak_resid_future_r": weak_resid_future_r,
        "gap_change_r": gap_change_r,
        "gap_future_r": gap_future_r,
        "expected_beats_actual": (
            expected_future_r is not None
            and actual_future_r is not None
            and abs(expected_future_r) > abs(actual_future_r)
        ),
        "negative_gap_n": len(negative_gap),
        "negative_gap_avg": negative_gap["hrfb_gap_plus_t"].mean(),
        "negative_gap_change": negative_gap["future_change_actual_hrfb_plus"].mean(),
        "positive_gap_n": len(positive_gap),
        "positive_gap_avg": positive_gap["hrfb_gap_plus_t"].mean(),
        "positive_gap_change": positive_gap["future_change_actual_hrfb_plus"].mean(),
        "middle_n": len(middle),
        "middle_change": middle["future_change_actual_hrfb_plus"].mean(),
    }


def print_flag_validity(pool: pd.DataFrame) -> dict[str, Any]:
    print("\n=== Part 3: flag validity ===")
    result = flag_validity(pool)
    print(f"Leakage-clean consecutive pitcher-seasons: {result['n']:,}")
    merged = consecutive_pool(pool)
    merged["future_change_actual_hrfb_plus"] = merged["actual_hrfb_plus_next"] - merged["actual_hrfb_plus_t"]
    print("Split | N | r exp->next actual | r actual->next actual | r weak->next actual | weak residual r | r gap->change")
    for split, frame in [("ALL", merged), ("SP", merged[merged["role_t"].eq("SP")]), ("RP", merged[merged["role_t"].eq("RP")])]:
        print(
            f"{split} | {len(frame):,} | "
            f"{format_r(safe_corr(frame, 'expected_hrfb_plus_t', 'actual_hrfb_plus_next'))} | "
            f"{format_r(safe_corr(frame, 'actual_hrfb_plus_t', 'actual_hrfb_plus_next'))} | "
            f"{format_r(safe_corr(frame, 'weak_fly_plus_t', 'actual_hrfb_plus_next'))} | "
            f"{format_r(residual_corr(frame, 'weak_fly_plus_t', 'actual_hrfb_plus_next', ['expected_hrfb_plus_t']))} | "
            f"{format_r(safe_corr(frame, 'hrfb_gap_plus_t', 'future_change_actual_hrfb_plus'))}"
        )
    print(f"\nr(T gap actual-expected, T+1 actual): {format_r(result['gap_future_r'])}")
    print("\nLift read by season-T HR/FB gap quintile:")
    print("Bucket | N | avg T gap | avg next-season change in actual HR/FB+")
    print(
        f"Most negative gap | {result['negative_gap_n']:,} | {result['negative_gap_avg']:+.1f} | "
        f"{result['negative_gap_change']:+.1f}"
    )
    print(
        f"Middle 60% | {result['middle_n']:,} | n/a | "
        f"{result['middle_change']:+.1f}"
    )
    print(
        f"Most positive gap | {result['positive_gap_n']:,} | {result['positive_gap_avg']:+.1f} | "
        f"{result['positive_gap_change']:+.1f}"
    )
    return result


def print_recommendation(gate: dict[str, bool], pool: pd.DataFrame, flag: dict[str, Any]) -> None:
    yoy = yoy_stability(pool)
    expected_yoy = yoy[(yoy["metric"].eq("Expected HR/FB")) & (yoy["split"].eq("ALL"))]["r"]
    weak_yoy = yoy[(yoy["metric"].eq("Weak-fly combo")) & (yoy["split"].eq("ALL"))]["r"]
    actual_yoy = yoy[(yoy["metric"].eq("Actual HR/FB")) & (yoy["split"].eq("ALL"))]["r"]
    expected_r = float(expected_yoy.iloc[0]) if len(expected_yoy) and pd.notna(expected_yoy.iloc[0]) else None
    weak_r = float(weak_yoy.iloc[0]) if len(weak_yoy) and pd.notna(weak_yoy.iloc[0]) else None
    actual_r = float(actual_yoy.iloc[0]) if len(actual_yoy) and pd.notna(actual_yoy.iloc[0]) else None

    print("\n=== Part 4: recommendation ===")
    if gate["expected_clone"]:
        print("Expected HR/FB fails the distinctness gate: it is a Getting Cooked clone at |r| >= 0.90.")
    elif gate["expected_barrel_clone"]:
        print("Expected HR/FB fails the distinctness gate: it is a barrel% clone at |r| >= 0.90.")
    else:
        print("Expected HR/FB clears the pre-registered clone gates vs Getting Cooked and barrel% allowed.")

    stable_skill = expected_r is not None and expected_r >= SKILL_R
    print(
        "Stability read: "
        f"expected HR/FB YoY r={format_r(expected_r)}, weak-fly YoY r={format_r(weak_r)}, "
        f"actual HR/FB YoY r={format_r(actual_r)}."
    )
    if stable_skill:
        print("Skill-stat gate: viable by the pre-registered YoY >= ~0.5 input-stability rule.")
    else:
        print("Skill-stat gate: not met; this is too thin for a standalone true-talent HR/FB skill stat.")

    if flag["expected_beats_actual"]:
        print("Luck-flag gate: met; expected HR/FB beats current actual HR/FB at predicting next-season actual HR/FB.")
    else:
        print("Luck-flag gate: not met; expected HR/FB does not beat current actual HR/FB for next-season actual HR/FB.")

    if gate["expected_clone"] or gate["expected_barrel_clone"]:
        print("Ship recommendation: do not ship as standalone; at most keep as a Getting Cooked decomposition appendix.")
    elif stable_skill:
        print("Ship recommendation: park-neutral expected HR/FB can be considered as a skill stat, with sample warnings near 150 FB.")
    elif flag["expected_beats_actual"]:
        print("Ship recommendation: regression flag only; keep the skill stat framing out of the product.")
    else:
        print("Ship recommendation: close it. No distinct HR/FB skill-or-luck product from this test.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostic HR/FB skill-vs-luck test.")
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--min-fly-balls", type=int, default=MIN_FLY_BALLS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global MIN_FLY_BALLS
    MIN_FLY_BALLS = args.min_fly_balls

    artifacts = [build_season(season) for season in args.seasons]
    print_coverage(artifacts)
    pool = pd.concat([item.rows for item in artifacts], ignore_index=True)
    pool["next_season"] = pool["season"] + 1
    eligible = pool[(pool["full_fly_balls"] >= MIN_FLY_BALLS) & pool["getting_cooked_plus"].notna()].copy()
    gate = print_distinctness(eligible)
    print_stability(pool)
    flag = print_flag_validity(pool)
    print_recommendation(gate, pool, flag)


if __name__ == "__main__":
    main()
