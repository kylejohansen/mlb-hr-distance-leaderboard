#!/usr/bin/env python3
"""Generate frontend-ready Hot Dog Stand pitcher JSON.

The Hot Dog Stand is a pitcher-accountability view for The Long Ball. It uses
Baseball Savant Home Run Tracker aggregates plus Statcast event data from the
canonical pitch cache. The frontend reads only the generated static JSON.
"""

from __future__ import annotations

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from data_integrity import scope_to_regular_season
from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache
from xlb import (
    DEFAULT_MODEL_PATH as XLB_MODEL_PATH,
    EVENT_UNIVERSE as XLB_EVENT_UNIVERSE,
    XLB_VERSION,
    aggregate_pitcher_xlb,
    load_xlb_model,
    prepare_terminal_bbe,
    score_terminal_bbe,
)


OUTPUT_PATH = Path("public/data/hot-dog-stand-latest.json")
HOT_DOG_SEASON_ARCHIVE_TEMPLATE = "public/data/hot-dog-index-{season}.json"
HOME_RUN_TRACKER_URL = "https://baseballsavant.mlb.com/leaderboard/home-runs"
HOME_RUN_TRACKER_CAT = "adj_xhr"
MLB_STATS_API_URL = "https://statsapi.mlb.com/api/v1/stats"
MIN_HR_ALLOWED = 5
MIN_BBE_ALLOWED = 50
MIN_PITCH_TYPE_SAMPLE = 15
LUCKY_DOG_MIN_MEATBALLS = 15
HOT_DOG_VERSION = "1.3"
GETTING_COOKED_COMPONENTS = {
    "hrCapableBbeRateAllowed": 1.0,
}
HIT_EVENTS = {"single", "double", "triple", "home_run"}
SITE_METADATA = {
    "name": "The Long Ball",
    "url": "https://thelongball.app",
    "tagline": "Digging the data behind the distance.",
}
HOT_DOG_FIELD_METADATA = {
    "pitcher": "Pitcher display name.",
    "team": "Pitcher's team when reliably available; otherwise an em dash.",
    "hotDogIndex": "Legacy cumulative damage field retained for payload compatibility; not displayed publicly.",
    "hotDogDamageAllowed": "Explicit alias for the legacy cumulative hotDogIndex field; not displayed publicly.",
    "xLB": "Expected Long Balls v0.2 allowed: the sum of expected-HR probabilities over terminal BBE.",
    "xLBPerBbe": "Expected Long Balls allowed per terminal batted ball.",
    "xLBPer9": "Expected Long Balls allowed per nine innings, calculated as xLB * 27 / official pitcher outs.",
    "pitcherOuts": "Official MLB pitcher outs recorded, used as the xLB/9 denominator.",
    "inningsPitched": "Official MLB innings-pitched display value.",
    "longBallGap": "Actual home runs allowed minus xLB. Positive means actual HR exceed contact-quality expectation.",
    "xlbVersion": "Expected Long Balls model version.",
    "hdiVersion": "Pitcher-side Hot Dog Stand formula version used for this pitcher row.",
    "gettingCookedIndex": "Getting Cooked v1.3 plus-style pitcher score for HR-capable contact allowed per BBE. 100 is average among qualified pitchers.",
    "cookedPlus": "Backward-compatible alias for gettingCookedIndex.",
    "premiumDamagePer100Bbe": "Premium longball damage units per 100 batted balls in play. Context only.",
    "gettingCookedPer100Bbe": "HR-capable batted balls allowed per 100 BBE. Raw companion to Getting Cooked.",
    "hrCapableBbePer100": "HR-capable batted balls allowed per 100 BBE. Raw companion to Getting Cooked.",
    "cookedPer100Bbe": "Backward-compatible alias for premiumDamagePer100Bbe.",
    "legacyCooked": "Backward-compatible alias for premiumDamagePer100Bbe.",
    "totalBbeAllowed": "Total batted-ball events allowed in the cached Statcast sample.",
    "hrCapableBbeAllowed": "Batted balls allowed that Baseball Savant classifies as having home-run potential in at least one MLB park.",
    "hrWindowThunderBbeAllowed": "Batted balls allowed at 105 mph or harder with launch angle between 25 and 40 degrees.",
    "hrWindowThunderRateAllowed": "Share of BBE allowed at 105 mph or harder with launch angle between 25 and 40 degrees. Pitcher-card context.",
    "noDoubtersAllowed": "HR-capable batted balls allowed that would clear all 30 MLB parks.",
    "mostlyGoneAllowed": "HR-capable batted balls allowed that would clear many parks, but not all.",
    "doubtersAllowed": "HR-capable batted balls allowed that would clear only a small number of parks.",
    "avgExitVelocityAllowed": "Average exit velocity allowed on HR-capable contact when available.",
    "avgDistanceAllowed": "Average projected distance allowed on HR-capable contact when available. Reference stat only.",
    "maxExitVelocityAllowed": "Hardest HR-capable contact allowed.",
    "maxDistanceAllowed": "Longest HR-capable contact allowed.",
    "meatballPitchesThrown": "Heart-zone pitches below the pitcher's 25th-percentile velocity for that pitch type, with the pitch-type sample safeguard applied.",
}


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value) or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    parsed = to_float(value)
    return int(parsed) if parsed is not None else None


def pitcher_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def savant_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Referer": HOME_RUN_TRACKER_URL,
    }


def fetch_home_run_tracker_pitchers(season: int, cat: str = HOME_RUN_TRACKER_CAT) -> pd.DataFrame:
    params = {
        "player_type": "Pitcher",
        "year": str(season),
        "cat": cat,
        "min": "0",
        "csv": "true",
    }
    url = f"{HOME_RUN_TRACKER_URL}?{urlencode(params)}"
    print(f"Fetching Baseball Savant Home Run Tracker pitcher CSV ({cat})")
    print(f"Home Run Tracker URL: {url}")
    request = Request(url, headers=savant_headers())
    with urlopen(request, timeout=45) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    frame = pd.read_csv(io.StringIO(body))
    frame.attrs["source_url"] = url
    return frame


def fetch_official_pitching_stats(season: int) -> pd.DataFrame:
    params = {
        "stats": "season",
        "group": "pitching",
        "season": str(season),
        "sportIds": "1",
        "playerPool": "ALL",
        "limit": "5000",
        "hydrate": "person",
    }
    url = f"{MLB_STATS_API_URL}?{urlencode(params)}"
    print("Fetching official MLB pitcher outs")
    request = Request(url, headers={"User-Agent": savant_headers()["User-Agent"], "Accept": "application/json"})
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = []
    for block in payload.get("stats", []):
        for split in block.get("splits", []):
            player = split.get("player") or {}
            stat = split.get("stat") or {}
            pitcher_id = to_int(player.get("id"))
            outs = to_int(stat.get("outs"))
            if pitcher_id is None or outs is None:
                continue
            rows.append(
                {
                    "pitcher_id": pitcher_id,
                    "pitcher_outs": outs,
                    "innings_pitched": str(stat.get("inningsPitched") or ""),
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id", "pitcher_outs", "innings_pitched"])
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher_id"], errors="coerce").astype("Int64")
    frame = frame.drop_duplicates("pitcher_id", keep="last")
    frame.attrs["source_url"] = url
    return frame


def plus_scale(values: pd.Series, baseline: float) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not baseline or pd.isna(baseline):
        return pd.Series(pd.NA, index=values.index)
    return 100 * numeric / baseline


def getting_cooked_components_for_pitcher(row: pd.Series, league_rate: float) -> dict[str, dict[str, float | None]]:
    score = to_float(row.get("getting_cooked_index"))
    return {
        "hrCapableBbeRateAllowed": {
            "value": round(float(row["hr_capable_bbe_rate_allowed"]), 4)
            if pd.notna(row.get("hr_capable_bbe_rate_allowed"))
            else None,
            "baseline": round(float(league_rate), 4) if league_rate and pd.notna(league_rate) else None,
            "score": round(score, 1) if score is not None else None,
            "weight": 1.0,
        }
    }


def normalize_tracker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    tracker = frame.copy()
    tracker["pitcher_id"] = pd.to_numeric(tracker.get("player_id"), errors="coerce").astype("Int64")
    tracker["pitcher"] = tracker.get("player", "").map(pitcher_display_name)
    tracker["team"] = tracker.get("team_abbrev", "").astype("string")
    for column in ["doubters", "mostly_gone", "no_doubters", "hr_total", "xhr", "xhr_diff"]:
        tracker[column] = pd.to_numeric(tracker.get(column), errors="coerce")

    tracker["hr_capable_bbe_allowed"] = (
        tracker["doubters"].fillna(0) + tracker["mostly_gone"].fillna(0) + tracker["no_doubters"].fillna(0)
    )
    return tracker.dropna(subset=["pitcher_id"])


def build_statcast_pitcher_context(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    events = pitches[pitches["events"].notna()].copy()
    events["pitcher_id"] = pd.to_numeric(events["pitcher"], errors="coerce").astype("Int64")
    events["launch_speed"] = pd.to_numeric(events["launch_speed"], errors="coerce")
    events["launch_angle"] = pd.to_numeric(events["launch_angle"], errors="coerce")
    events["hit_distance_sc"] = pd.to_numeric(events["hit_distance_sc"], errors="coerce")
    bbe = events[events["launch_speed"].notna() & events["launch_angle"].notna()].copy()
    bbe["is_hr_window_thunder_allowed"] = bbe["launch_speed"].ge(105) & bbe["launch_angle"].between(25, 40, inclusive="both")
    home_runs = events[events["events"].astype("string").str.lower().eq("home_run")].copy()

    bbe_counts = bbe.groupby("pitcher_id").size().rename("bbe_allowed")
    thunder_counts = bbe.groupby("pitcher_id")["is_hr_window_thunder_allowed"].sum().rename("hr_window_thunder_bbe_allowed")
    hr_grouped = home_runs.groupby("pitcher_id")
    hr_stats = hr_grouped.agg(
        avgExitVelocityAllowed=("launch_speed", "mean"),
        maxExitVelocityAllowed=("launch_speed", "max"),
        avgDistanceAllowed=("hit_distance_sc", "mean"),
        maxDistanceAllowed=("hit_distance_sc", "max"),
    )

    worst_rows = []
    if not home_runs.empty:
        scored = home_runs.copy()
        scored["worst_score"] = scored["launch_speed"].fillna(0) * 2 + scored["hit_distance_sc"].fillna(0) / 10
        for pitcher_id, row in scored.sort_values("worst_score", ascending=False).groupby("pitcher_id").head(1).set_index("pitcher_id").iterrows():
            worst_rows.append(
                {
                    "pitcher_id": pitcher_id,
                    "worstServedEvent": {
                        "gameDate": str(row.get("game_date", ""))[:10],
                        "batterId": to_int(row.get("batter")),
                        "pitcherId": to_int(row.get("pitcher")),
                        "description": str(row.get("des") or row.get("description") or "").strip(),
                        "exitVelocity": round(float(row["launch_speed"]), 1) if pd.notna(row.get("launch_speed")) else None,
                        "distance": int(round(float(row["hit_distance_sc"]))) if pd.notna(row.get("hit_distance_sc")) else None,
                        "launchAngle": round(float(row["launch_angle"]), 1) if pd.notna(row.get("launch_angle")) else None,
                    },
                }
            )

    context = pd.concat([bbe_counts, thunder_counts, hr_stats], axis=1).reset_index()
    role_context = build_pitcher_role_context(pitches)
    if not role_context.empty:
        context = context.merge(role_context, on="pitcher_id", how="left")
    worst = pd.DataFrame(worst_rows)
    if not worst.empty:
        context = context.merge(worst, on="pitcher_id", how="left")
    else:
        context["worstServedEvent"] = None
    return context


def build_pitcher_role_context(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    frame = pitches.dropna(subset=["game_pk", "pitcher"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id"])

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
        return pd.DataFrame(columns=["pitcher_id"])

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
    roles["relief_appearances"] = (roles["appearances"] - roles["games_started"]).clip(lower=0).astype(int)
    roles["pitcher_role"] = roles.apply(
        lambda row: "SP" if row["games_started"] >= max(1, row["appearances"] / 2) else "RP",
        axis=1,
    )
    return roles


def build_meatball_context(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    frame = pitches.copy()
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["release_speed"] = pd.to_numeric(frame["release_speed"], errors="coerce")
    frame["launch_speed"] = pd.to_numeric(frame["launch_speed"], errors="coerce")
    frame["pitch_type"] = frame["pitch_type"].astype("string")
    frame["description"] = frame["description"].astype("string")
    frame["events"] = frame["events"].astype("string")
    frame["is_heart_zone"] = frame["is_heart_zone"].fillna(False).astype(bool)

    velocity_context = (
        frame.dropna(subset=["pitcher_id", "pitch_type", "release_speed"])
        .groupby(["pitcher_id", "pitch_type"])["release_speed"]
        .agg(pitch_type_count="size", velocity_p25=lambda values: values.quantile(0.25))
        .reset_index()
    )
    frame = frame.merge(velocity_context, on=["pitcher_id", "pitch_type"], how="left")

    meatball_mask = (
        frame["is_heart_zone"]
        & frame["pitch_type_count"].ge(MIN_PITCH_TYPE_SAMPLE)
        & frame["release_speed"].lt(frame["velocity_p25"])
    )
    meatballs = frame[meatball_mask].copy()
    if meatballs.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    meatballs_in_play = meatballs[meatballs["description"].eq("hit_into_play")].copy()
    grouped = meatballs.groupby("pitcher_id", as_index=False).agg(
        meatball_pitches_thrown=("description", "size"),
        meatball_hrs=("events", lambda values: values.astype("string").str.lower().eq("home_run").sum()),
        meatball_hits_allowed=("events", lambda values: values.astype("string").str.lower().isin(HIT_EVENTS).sum()),
    )
    ev = (
        meatballs_in_play.groupby("pitcher_id")["launch_speed"]
        .mean()
        .rename("meatball_avg_ev_allowed")
        .reset_index()
    )
    grouped = grouped.merge(ev, on="pitcher_id", how="left")
    grouped["lucky_dog_rate"] = 1 - (
        grouped["meatball_hrs"] / grouped["meatball_pitches_thrown"].where(grouped["meatball_pitches_thrown"] > 0)
    )
    return grouped


def build_hot_dog_rows(
    pitches: pd.DataFrame,
    tracker: pd.DataFrame,
    official_pitching: pd.DataFrame,
    xlb_context: pd.DataFrame,
    min_hr_allowed: int,
    min_bbe_allowed: int,
) -> list[dict[str, Any]]:
    tracker = normalize_tracker(tracker)
    context = build_statcast_pitcher_context(pitches)
    meatball_context = build_meatball_context(pitches)
    if tracker.empty or context.empty:
        return []

    merged = tracker.merge(context, on="pitcher_id", how="left")
    if not official_pitching.empty:
        merged = merged.merge(official_pitching, on="pitcher_id", how="left")
    else:
        merged["pitcher_outs"] = pd.NA
        merged["innings_pitched"] = pd.NA
    if not xlb_context.empty:
        merged = merged.merge(xlb_context, on="pitcher_id", how="left")
    else:
        for column in ["xlb_bbe", "xlb", "xlb_per_bbe"]:
            merged[column] = pd.NA
    if not meatball_context.empty:
        merged = merged.merge(meatball_context, on="pitcher_id", how="left")
    else:
        for column in ["meatball_pitches_thrown", "meatball_hrs", "meatball_hits_allowed", "meatball_avg_ev_allowed", "lucky_dog_rate"]:
            merged[column] = pd.NA
    merged["bbe_allowed"] = pd.to_numeric(merged["bbe_allowed"], errors="coerce").fillna(0)
    merged["xhr_per_bbe_allowed"] = merged["xhr"].fillna(0) / merged["bbe_allowed"].where(merged["bbe_allowed"] > 0)
    merged["hr_capable_bbe_rate_allowed"] = merged["hr_capable_bbe_allowed"].fillna(0) / merged["bbe_allowed"].where(merged["bbe_allowed"] > 0)
    merged["no_doubter_rate_allowed"] = merged["no_doubters"].fillna(0) / merged["hr_capable_bbe_allowed"].where(merged["hr_capable_bbe_allowed"] > 0)
    merged["hr_window_thunder_bbe_allowed"] = pd.to_numeric(merged.get("hr_window_thunder_bbe_allowed"), errors="coerce").fillna(0)
    merged["hr_window_thunder_rate_allowed"] = merged["hr_window_thunder_bbe_allowed"] / merged["bbe_allowed"].where(merged["bbe_allowed"] > 0)

    qualified = merged[(merged["hr_total"].fillna(0) >= min_hr_allowed) & (merged["bbe_allowed"] >= min_bbe_allowed)].copy()
    if qualified.empty:
        return []

    league_hr_capable_rate = (
        qualified["hr_capable_bbe_allowed"].fillna(0).sum()
        / qualified["bbe_allowed"].where(qualified["bbe_allowed"] > 0).sum()
    )
    qualified["getting_cooked_index"] = plus_scale(qualified["hr_capable_bbe_rate_allowed"], league_hr_capable_rate)
    qualified["getting_cooked_per_100_bbe"] = qualified["hr_capable_bbe_rate_allowed"] * 100
    qualified["getting_cooked_components"] = qualified.apply(
        lambda row: getting_cooked_components_for_pitcher(row, league_hr_capable_rate),
        axis=1,
    )
    qualified["hot_dog_damage_allowed"] = (
        qualified["xhr"].fillna(0)
        + qualified["hr_window_thunder_bbe_allowed"].fillna(0)
        + qualified["no_doubters"].fillna(0)
        + 0.5 * qualified["hr_total"].fillna(0)
    )
    qualified["premium_damage_per_100_bbe"] = (
        qualified["hot_dog_damage_allowed"] / qualified["bbe_allowed"].where(qualified["bbe_allowed"] > 0) * 100
    )
    qualified["xlb_per_9"] = (
        qualified["xlb"] * 27 / qualified["pitcher_outs"].where(qualified["pitcher_outs"] > 0)
    )
    qualified["long_ball_gap"] = qualified["hr_total"] - qualified["xlb"]
    qualified["cooked_plus"] = qualified["getting_cooked_index"]

    rows = []
    for _, row in qualified.iterrows():
        rows.append(
            {
                "pitcherId": int(row["pitcher_id"]),
                "pitcher": str(row.get("pitcher") or f"MLBAM {int(row['pitcher_id'])}"),
                "team": str(row.get("team") or ""),
                "pitcherRole": str(row.get("pitcher_role") or ""),
                "appearances": int(row["appearances"]) if pd.notna(row.get("appearances")) else 0,
                "gamesStarted": int(row["games_started"]) if pd.notna(row.get("games_started")) else 0,
                "reliefAppearances": int(row["relief_appearances"]) if pd.notna(row.get("relief_appearances")) else 0,
                "hotDogIndex": round(float(row["hot_dog_damage_allowed"]), 1),
                "hotDogDamageAllowed": round(float(row["hot_dog_damage_allowed"]), 1),
                "hdiVersion": HOT_DOG_VERSION,
                "xLB": round(float(row["xlb"]), 3) if pd.notna(row.get("xlb")) else None,
                "xLBPerBbe": round(float(row["xlb_per_bbe"]), 5) if pd.notna(row.get("xlb_per_bbe")) else None,
                "xLBPer9": round(float(row["xlb_per_9"]), 2) if pd.notna(row.get("xlb_per_9")) else None,
                "xlbBbe": int(row["xlb_bbe"]) if pd.notna(row.get("xlb_bbe")) else 0,
                "pitcherOuts": int(row["pitcher_outs"]) if pd.notna(row.get("pitcher_outs")) else None,
                "inningsPitched": str(row["innings_pitched"]) if pd.notna(row.get("innings_pitched")) else None,
                "longBallGap": round(float(row["long_ball_gap"]), 2) if pd.notna(row.get("long_ball_gap")) else None,
                "xlbVersion": XLB_VERSION,
                "bbeAllowed": int(row["bbe_allowed"]),
                "totalBbeAllowed": int(row["bbe_allowed"]),
                "gettingCookedIndex": round(float(row["getting_cooked_index"]), 1) if pd.notna(row.get("getting_cooked_index")) else None,
                "cookedPlus": round(float(row["cooked_plus"]), 1) if pd.notna(row.get("cooked_plus")) else None,
                "premiumDamagePer100Bbe": round(float(row["premium_damage_per_100_bbe"]), 1) if pd.notna(row.get("premium_damage_per_100_bbe")) else None,
                "gettingCookedPer100Bbe": round(float(row["getting_cooked_per_100_bbe"]), 1) if pd.notna(row.get("getting_cooked_per_100_bbe")) else None,
                "hrCapableBbePer100": round(float(row["getting_cooked_per_100_bbe"]), 1) if pd.notna(row.get("getting_cooked_per_100_bbe")) else None,
                "cookedPer100Bbe": round(float(row["premium_damage_per_100_bbe"]), 1) if pd.notna(row.get("premium_damage_per_100_bbe")) else None,
                "legacyCooked": round(float(row["premium_damage_per_100_bbe"]), 1) if pd.notna(row.get("premium_damage_per_100_bbe")) else None,
                "hrsAllowed": int(row["hr_total"]),
                "adjustedXhrAllowed": round(float(row["xhr"]), 1) if pd.notna(row.get("xhr")) else None,
                "adjustedXhrPerBbeAllowed": round(float(row["xhr_per_bbe_allowed"]), 4) if pd.notna(row.get("xhr_per_bbe_allowed")) else None,
                "xhrDiffAllowed": round(float(row["xhr_diff"]), 1) if pd.notna(row.get("xhr_diff")) else None,
                "hrCapableBbeAllowed": int(row["hr_capable_bbe_allowed"]),
                "hrCapableBbeRateAllowed": round(float(row["hr_capable_bbe_rate_allowed"]), 4) if pd.notna(row.get("hr_capable_bbe_rate_allowed")) else None,
                "hrWindowThunderBbeAllowed": int(row["hr_window_thunder_bbe_allowed"]),
                "hrWindowThunderRateAllowed": round(float(row["hr_window_thunder_rate_allowed"]), 4) if pd.notna(row.get("hr_window_thunder_rate_allowed")) else None,
                "noDoubtersAllowed": int(row["no_doubters"] or 0),
                "mostlyGoneAllowed": int(row["mostly_gone"] or 0),
                "doubtersAllowed": int(row["doubters"] or 0),
                "noDoubterRateAllowed": round(float(row["no_doubter_rate_allowed"]), 4) if pd.notna(row.get("no_doubter_rate_allowed")) else None,
                "meatballPitchesThrown": int(row["meatball_pitches_thrown"]) if pd.notna(row.get("meatball_pitches_thrown")) else 0,
                "meatballHrs": int(row["meatball_hrs"]) if pd.notna(row.get("meatball_hrs")) else 0,
                "meatballHitsAllowed": int(row["meatball_hits_allowed"]) if pd.notna(row.get("meatball_hits_allowed")) else 0,
                "meatballAvgEvAllowed": round(float(row["meatball_avg_ev_allowed"]), 1) if pd.notna(row.get("meatball_avg_ev_allowed")) else None,
                "luckyDogRate": round(float(row["lucky_dog_rate"]), 4) if pd.notna(row.get("lucky_dog_rate")) else None,
                "avgExitVelocityAllowed": round(float(row["avgExitVelocityAllowed"]), 1) if pd.notna(row.get("avgExitVelocityAllowed")) else None,
                "avgDistanceAllowed": round(float(row["avgDistanceAllowed"]), 1) if pd.notna(row.get("avgDistanceAllowed")) else None,
                "maxExitVelocityAllowed": round(float(row["maxExitVelocityAllowed"]), 1) if pd.notna(row.get("maxExitVelocityAllowed")) else None,
                "maxDistanceAllowed": int(round(float(row["maxDistanceAllowed"]))) if pd.notna(row.get("maxDistanceAllowed")) else None,
                "worstServedEvent": row.get("worstServedEvent") if isinstance(row.get("worstServedEvent"), dict) else None,
                "gettingCookedComponents": row["getting_cooked_components"],
                "hotDogDamageComponents": {
                    "adjustedXhrProxyAllowed": round(float(row["xhr"]), 1) if pd.notna(row.get("xhr")) else None,
                    "hrWindowThunderBbeAllowed": int(row["hr_window_thunder_bbe_allowed"]),
                    "noDoubtersAllowed": int(row["no_doubters"] or 0),
                    "actualHrAllowed": int(row["hr_total"]),
                    "bbeAllowed": int(row["bbe_allowed"]),
                    "formula": "adjustedXhrAllowed + HRWindowThunderBbeAllowed + noDoubtersAllowed + 0.5 * actualHrAllowed",
                },
                "hdiComponents": row["getting_cooked_components"],
                "hotDogComponents": row["getting_cooked_components"],
            }
        )

    return sorted(rows, key=lambda item: (-(item["cookedPlus"] or 0), -(item["xLBPer9"] or 0), item["pitcher"]))


def write_json(
    path: Path,
    rows: list[dict[str, Any]],
    pitch_cache: Path,
    xlb_model_path: Path,
    season: int,
    min_hr_allowed: int,
    min_bbe_allowed: int,
    tracker_url: str | None,
    pitching_stats_url: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "site": SITE_METADATA,
        "dataset": "Hot Dog Stand",
        "season": season,
        "description": "Pitcher-facing longball danger leaderboard for The Hot Dog Stand.",
        "methodologyVersion": f"Hot Dog Stand v{HOT_DOG_VERSION}",
        "sourceNotes": (
            "Uses the canonical Statcast pitch cache, Baseball Savant Home Run Tracker Adjusted mode, "
            "a committed xLB v0.2 historical model, and official MLB pitcher outs. "
            "The frontend reads this precomputed static JSON and never queries Statcast directly."
        ),
        "fields": HOT_DOG_FIELD_METADATA,
        "source": {
            "pitchCache": str(pitch_cache),
            "homeRunTracker": tracker_url or HOME_RUN_TRACKER_URL,
            "homeRunTrackerMode": HOME_RUN_TRACKER_CAT,
            "mlbPitchingStats": pitching_stats_url or MLB_STATS_API_URL,
            "xlbModel": str(xlb_model_path.relative_to(Path.cwd())) if xlb_model_path.is_absolute() else str(xlb_model_path),
            "xlbVersion": XLB_VERSION,
            "xlbEventUniverse": XLB_EVENT_UNIVERSE,
            "methodology": "Getting Cooked v1.3 is the flagship plus-style pitcher score for HR-capable batted balls allowed per BBE. 100 is average among qualified pitchers. xLB/9 sums xLB v0.2 expected-HR probabilities over terminal BBE and scales them to nine innings using official MLB pitcher outs. Foul and other non-terminal contact is excluded. Hot Dog Damage remains in the payload for backward compatibility but is not a public display stat.",
        },
        "qualifiedBy": {
            "minimumHrsAllowed": min_hr_allowed,
            "minimumBbeAllowed": min_bbe_allowed,
            "meatballMinimumPitches": LUCKY_DOG_MIN_MEATBALLS,
            "meatballPitchTypeMinimumSample": MIN_PITCH_TYPE_SAMPLE,
        },
        "hotDogIndexVersion": HOT_DOG_VERSION,
        "hdiVersion": HOT_DOG_VERSION,
        "gettingCookedComponents": GETTING_COOKED_COMPONENTS,
        "hdiComponents": GETTING_COOKED_COMPONENTS,
        "pitchers": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    archive_path = Path(HOT_DOG_SEASON_ARCHIVE_TEMPLATE.format(season=season))
    if archive_path != path:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def print_board(title: str, rows: list[dict[str, Any]], key: Any, value: Any) -> None:
    print(f"\n{title}")
    for index, row in enumerate(sorted(rows, key=key)[:10], 1):
        print(f"{index:2}. {row['pitcher']} ({row['team']}) | {value(row)}")


def print_diagnostics(rows: list[dict[str, Any]]) -> None:
    print("\n=== The Hot Dog Stand diagnostics ===")
    print(f"Qualified pitchers: {len(rows)}")
    print_board("Getting Cooked: HR-capable contact rate allowed", rows, lambda row: (-(row["cookedPlus"] or 0), -(row["xLBPer9"] or 0), row["pitcher"]), lambda row: f"Cooked {row['cookedPlus']} | HR-capable/100 {row['gettingCookedPer100Bbe']} | xLB/9 {row['xLBPer9']}")
    print_board("Expected Long Balls per nine innings", [row for row in rows if row.get("xLBPer9") is not None], lambda row: (-row["xLBPer9"], -row["cookedPlus"], row["pitcher"]), lambda row: f"xLB/9 {row['xLBPer9']} | xLB {row['xLB']} | IP {row['inningsPitched']}")
    print_board("Footlongs: HR-capable BBE allowed", rows, lambda row: (-row["hrCapableBbeAllowed"], -(row["xLBPer9"] or 0), row["pitcher"]), lambda row: f"HR-capable {row['hrCapableBbeAllowed']} | no-doubters {row['noDoubtersAllowed']}")
    print_board("Extra Mustard: no-doubters allowed", rows, lambda row: (-row["noDoubtersAllowed"], -(row["xLBPer9"] or 0), row["pitcher"]), lambda row: f"no-doubters {row['noDoubtersAllowed']} | mostly gone {row['mostlyGoneAllowed']}")
    lucky_rows = [row for row in rows if row.get("meatballPitchesThrown", 0) >= LUCKY_DOG_MIN_MEATBALLS and row.get("luckyDogRate") is not None]
    print_board("Meatball escape rate", lucky_rows, lambda row: (-(row["luckyDogRate"] or 0), -row["meatballPitchesThrown"], row["pitcher"]), lambda row: f"{row['luckyDogRate']:.0%} | meatballs {row['meatballPitchesThrown']} | HR {row['meatballHrs']}")
    rates = [float(row["luckyDogRate"]) for row in lucky_rows if row.get("luckyDogRate") is not None]
    print(f"\nMeatball escape qualified pitchers: {len(lucky_rows)}")
    if rates:
        print(
            "Meatball escape rate distribution: "
            f"median={pd.Series(rates).median():.1%}, mean={pd.Series(rates).mean():.1%}, "
            f"max={max(rates):.1%}, min={min(rates):.1%}"
        )
        small_sample = [row for row in sorted(lucky_rows, key=lambda row: (-(row["luckyDogRate"] or 0), -row["meatballPitchesThrown"], row["pitcher"]))[:10] if row["meatballPitchesThrown"] < 20]
        if small_sample:
            names = ", ".join(f"{row['pitcher']} ({row['meatballPitchesThrown']})" for row in small_sample)
            print(f"Meatball escape top-10 small-sample candidates below 20 meatballs: {names}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate The Hot Dog Stand pitcher JSON.")
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--pitch-cache", type=Path, default=PITCH_CACHE_PATH)
    parser.add_argument("--xlb-model", type=Path, default=XLB_MODEL_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr-allowed", type=int, default=MIN_HR_ALLOWED)
    parser.add_argument("--min-bbe-allowed", type=int, default=MIN_BBE_ALLOWED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pitches = scope_to_regular_season(read_pitch_cache(args.pitch_cache), args.season)
    tracker = fetch_home_run_tracker_pitchers(args.season)
    official_pitching = fetch_official_pitching_stats(args.season)
    xlb_model = load_xlb_model(args.xlb_model)
    xlb_bbe = prepare_terminal_bbe(pitches)
    xlb_context = aggregate_pitcher_xlb(score_terminal_bbe(xlb_bbe, xlb_model))
    rows = build_hot_dog_rows(
        pitches,
        tracker,
        official_pitching,
        xlb_context,
        args.min_hr_allowed,
        args.min_bbe_allowed,
    )
    print_diagnostics(rows)
    write_json(
        args.output,
        rows,
        args.pitch_cache,
        args.xlb_model,
        args.season,
        args.min_hr_allowed,
        args.min_bbe_allowed,
        tracker.attrs.get("source_url"),
        official_pitching.attrs.get("source_url"),
    )
    print(f"Wrote {len(rows)} qualified pitchers to {args.output}")


if __name__ == "__main__":
    main()
