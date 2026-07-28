#!/usr/bin/env python3
"""Generate frontend-ready Longball Index JSON.

This script is the only Statcast access layer. The frontend reads static JSON
from public/data and never calls Baseball Savant, pybaseball, or any live API.

Default behavior:
- Keep raw pitch-level events in data/raw/statcast-pitches.csv.gz.
- On the first run, backfill the current season to date.
- On later runs, fetch the last few days, merge, dedupe, and rebuild JSON.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist, mean, median
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))

import pandas as pd
from contact_metrics import ContactMetricDiagnostics, build_contact_metrics
from data_integrity import (
    is_missing_hrt_statcast_contradiction,
    print_integrity_quarantine,
    scope_to_regular_season,
    validate_hrt_detail_completeness,
)
from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache, refresh_pitch_cache
from lbi_v14 import (
    LBI_V14_IMPROB_SHRINK_K,
    LBI_V14_MIN_PA_FOR_NORMALIZATION,
    LBI_V14_MIN_EVENTS_FOR_ARCHETYPE,
    add_lbi_v14_event_columns,
    apply_lbi_v14_player_scores,
    classify_batter_relative_spray,
    compute_true_spray_angle,
)
from pybaseball import playerid_reverse_lookup


RAW_CACHE_PATH = PITCH_CACHE_PATH
OUTPUT_PATH = Path("public/data/hr-distance-latest.json")
DAILY_FEATURE_ARCHIVE_TEMPLATE = "public/data/daily-features-{season}.json"
TALE_OF_THE_TAPE_ARCHIVE_DIR = Path("public/data/tale-of-the-tape")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
FETCH_CHUNK_DAYS = 7
LBI_VERSION = "1.4"
LBI_MINIMUM_BBE_FLOOR = 70
LBI_FULL_SEASON_BBE_TARGET = 245
MLB_SCHEDULED_TEAM_GAMES = 162
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
HOME_RUN_TRACKER_URL = "https://baseballsavant.mlb.com/leaderboard/home-runs"
HOME_RUN_TRACKER_CAT = "adj_xhr"
STANDARD_HOME_RUN_TRACKER_CAT = "xhr"
BATTED_BALL_LEADERBOARD_URL = "https://baseballsavant.mlb.com/leaderboard/batted-ball"
CHEAPIE_JOIN_MIN_RATE = 0.95
HCY_CURRENT_CACHE_PATH = Path("/private/tmp/lbi_statcast_with_hcy_2026.csv")
HCY_HISTORICAL_PATH_TEMPLATE = "data/cache/longball-threat-backtest/statcast-pitches-{season}-{half}.csv"
HRT_DETAIL_CACHE_TEMPLATE = "data/cache/longball-threat-backtest/hrt-details-{season}-{cat}.csv"
HCY_MIN_BBE_COVERAGE = 0.90
RAW_COLUMNS = [
    "game_date",
    "batter",
    "player_name",
    "bat_team",
    "events",
    "type",
    "hit_distance_sc",
    "launch_speed",
    "launch_angle",
    "launch_speed_angle",
    "bb_type",
    "hc_x",
    "hc_y",
    "stand",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "sv_id",
    "pitcher",
    "pitcher_name",
    "home_team",
    "away_team",
    "inning_topbot",
    "zone",
    "des",
]
STATCAST_FIELD_GROUPS = {
    "parks out of 30": ["parks_out", "parks_out_of_30", "home_run_parks", "hr_stadiums"],
    "hr_stadiums": ["hr_stadiums"],
    "expected_hr": ["expected_hr", "x_hr", "xhr"],
    "no-doubter / home-run park count": ["is_no_doubter", "no_doubter", "home_run_parks", "hr_stadiums"],
    "attack zone / heart zone": ["attack_zone", "attack_zone_bucket", "heart", "zone"],
    "pitcher name / pitcher id": ["pitcher", "player_name", "pitcher_name"],
}
LBI_COMPONENT_WEIGHTS = {
    "adjustedXhrPerBbe": 0.50,
    "barrelRate": 0.20,
    "hrWindowThunderRate": 0.25,
    "hardHitRate": 0.05,
}
LBI_COMPONENT_VALUE_KEYS = {
    "adjustedXhrPerBbe": "xhrPerBbe",
    "barrelRate": "barrelRate",
    "hrWindowThunderRate": "hrWindowThunderRate",
    "hardHitRate": "hardHitRate",
}
OPPO_POP_MIN_OPPO_AIR_BBE = 12
DIRECTIONAL_POP_AVERAGE = 100
DIRECTIONAL_PULL_STRONG = 150
DIRECTIONAL_OPPO_STRONG = 200
DIRECTIONAL_OPPO_NEUTRAL_CEILING = 115
OPPO_POP_ELITE = 300
OPPO_POP_STRONG = 200
OPPO_POP_ABOVE_AVERAGE = 125
OPPO_POP_SOME_DAMAGE = 85
SITE_METADATA = {
    "name": "The Long Ball",
    "url": "https://thelongball.app",
    "tagline": "Digging the data behind the distance.",
}
LBI_FIELD_METADATA = {
    "player": "Hitter display name.",
    "team": "Most recent batting team inferred from Statcast context.",
    "bbe": "Batted-ball events in the cached Statcast sample.",
    "pa": "Plate appearances inferred from unique game and at-bat identifiers in the cached Statcast sample.",
    "hr": "Actual home runs in the cached Statcast sample.",
    "battingHomeRuns": "Home runs inferred from true terminal plate appearances in the cached Statcast sample. Used for ISO Breakdown.",
    "ab": "Official at-bats inferred from true terminal plate appearances in the cached Statcast sample.",
    "hits": "Hits inferred from terminal plate-appearance outcomes in the cached Statcast sample.",
    "doubles": "Doubles inferred from terminal plate-appearance outcomes in the cached Statcast sample.",
    "triples": "Triples inferred from terminal plate-appearance outcomes in the cached Statcast sample.",
    "iso": "Isolated power from the cached batting line: (2B + 2*3B + 3*HR) / AB.",
    "otfIso": "Over-the-fence portion of ISO: 3*HR / AB.",
    "legsIso": "Non-HR extra-base portion of ISO: (2B + 2*3B) / AB.",
    "otfShare": "Share of ISO coming from home-run damage over the fence.",
    "legsShare": "Share of ISO coming from doubles and triples.",
    "doublesShare": "Share of ISO coming from doubles.",
    "triplesShare": "Share of ISO coming from triples.",
    "longballIndex": "LBI v1.4 descriptive long-ball contact quality index. 100 is league average among qualified hitters.",
    "thumpIndex": "LBI v1.4 axis: long-ball authority from exit velocity and park-neutral estimated distance, accumulated per PA and plus-scaled to 100 = qualified-player average.",
    "improbabilityIndex": "Internal field for the LBI v1.4 Artistry axis: how rare/difficult the spray-direction x launch-angle route to long-ball contact was, averaged per qualifying long-ball event, shrunk toward league average, and plus-scaled to 100 = qualified-player average.",
    "longBallEventCount": "Count of LBI v1.4 qualifying long-ball events.",
    "lbiArchetype": "LBI v1.4 style label: Apex Power, Thumper, Specialist, or Balanced Power.",
    "sprayDiversity": "Entropy-style spread of LBI v1.4 qualifying long balls across pull, center, and opposite field. Read-only context.",
    "lbiV14OppoPct": "Share of known-spray LBI v1.4 qualifying long balls hit opposite field.",
    "lbiV14PullPct": "Share of known-spray LBI v1.4 qualifying long balls hit to the pull side.",
    "lbiV14CenterPct": "Share of known-spray LBI v1.4 qualifying long balls hit to center field.",
    "xhr": "Adjusted expected home runs from Baseball Savant Home Run Tracker.",
    "xhrPerBbe": "Adjusted expected home runs per batted-ball event.",
    "barrelRate": "Share of batted balls classified as barrels.",
    "hrWindowThunderBbe": "Count of batted balls hit 105 mph or harder with launch angle between 25 and 40 degrees.",
    "hrWindowThunderRate": "Share of batted balls hit 105 mph or harder with launch angle between 25 and 40 degrees. LBI v1.3 component.",
    "hardHitRate": "Share of batted balls hit 95 mph or harder.",
    "maxExitVelocity": "Hardest batted ball hit by the hitter in the cached Statcast sample. Reference stat only, not part of LBI.",
    "avgDistanceOnBarrels": "Average projected distance on barreled batted balls. Reference stat only, not part of LBI v1.3.",
    "pullAirRate": "Pull Air percentage from Baseball Savant's batted-ball leaderboard. Reference stat only.",
    "pullAirJuice": "Weighted pulled-air contact per plate appearance. Context stat only, not part of LBI.",
    "pullAirJuicePer100Pa": "Weighted pulled-air contact per 100 plate appearances. Context stat only, not part of LBI.",
    "pullPop": "Plus-scaled Pull Pop, with 100 equal to league average among qualified hitters.",
    "oppoAirBbe": "Opposite-field batted balls with launch angle between 15 and 45 degrees, using per-PA batter side.",
    "oppoAirJuice": "Weighted opposite-field air contact per plate appearance. Context stat only, not part of LBI.",
    "oppoAirJuicePer100Pa": "Weighted opposite-field air contact per 100 plate appearances. Context stat only, not part of LBI.",
    "oppoPop": "Plus-scaled opposite-field air power context, with 100 equal to league average among qualified hitters with enough opposite-field air contact.",
    "oppoPopTier": "Tier-first opposite-field air power display label. Context only, not part of LBI.",
    "oppoPopDisplayLabel": "Readable player-card label for OppoPop. Context only, not part of LBI.",
    "directionalPowerTag": "Directional power context tag based on Pull Pop and OppoPop. Context only, not part of LBI.",
    "directionalPowerNote": "Short explanation for the directional power context tag.",
    "contactPct": "Contact percentage from full pitch-level Statcast: contacts divided by swings. Context stat only, not part of LBI.",
    "pesky": "Plus-scaled contact percentage, with 100 equal to average contact% among LBI-qualified hitters.",
    "contactSwings": "Swing count used for public contact% / Pesky context.",
    "contactPa": "True terminal plate appearances from the full pitch-level cache. Audit field for contact context.",
    "pulledAirBbe": "Pulled batted balls with launch angle between 15 and 45 degrees.",
    "crushedPulledAirBbe": "Pulled-air batted balls hit 105 mph or harder.",
    "sweetSpotRate": "Share of batted balls launched between 8 and 32 degrees. Reference stat only.",
    "actualDoubterHr": "Actual home runs classified as Doubters by Home Run Tracker detail data.",
    "cheapieRate": "Actual Doubter HR divided by actual HR total.",
    "dailyFeatures": "Latest-date Daily Dong, Hot Dog Robbery, and Cheapest Dong event objects.",
}
DIAGNOSTIC_PLAYERS = [
    "Ke'Bryan Hayes",
    "Nico Hoerner",
    "Alex Bregman",
    "Kyle Schwarber",
    "Aaron Judge",
    "Isaac Paredes",
    "Fernando Tatis Jr.",
    "Colt Keith",
]


def hcy_source_paths(season: int, raw_cache: Path) -> list[Path]:
    paths = [raw_cache]
    for half in ["first", "second"]:
        paths.append(Path(HCY_HISTORICAL_PATH_TEMPLATE.format(season=season, half=half)))
    if season == 2026:
        paths.append(HCY_CURRENT_CACHE_PATH)
    return paths


def parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected date format YYYY-MM-DD.") from error


def iso_today() -> date:
    return datetime.now(timezone.utc).date()


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.replace("’", "'"))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text

    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


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


def pull_pop_event_scores(
    pulled: pd.Series,
    launch_speeds: pd.Series,
    launch_angles: pd.Series,
) -> pd.Series:
    ev_score = ((launch_speeds - 100) / 16).clip(lower=0)
    angle_score = pd.Series(0.0, index=launch_angles.index)

    lower_taper = launch_angles.between(15, 24, inclusive="left")
    sweet_band = launch_angles.between(24, 33, inclusive="both")
    upper_taper = launch_angles.between(33, 40, inclusive="right")

    angle_score.loc[lower_taper] = (launch_angles.loc[lower_taper] - 15) / 9
    angle_score.loc[sweet_band] = 1.0
    angle_score.loc[upper_taper] = (40 - launch_angles.loc[upper_taper]) / 7

    return ev_score.fillna(0) * angle_score.clip(lower=0) * pulled.astype(float)


def oppo_pop_tier(player: dict[str, Any]) -> tuple[str, str]:
    oppo_pop = to_float(player.get("oppoPop"))
    oppo_air_bbe = to_int(player.get("oppoAirBbe")) or 0

    if oppo_air_bbe < OPPO_POP_MIN_OPPO_AIR_BBE or oppo_pop is None:
        return "Insufficient Oppo Sample", "Insufficient Oppo Sample"
    if oppo_pop >= OPPO_POP_ELITE:
        return "Elite Oppo Authority", "Elite Oppo Authority"
    if oppo_pop >= OPPO_POP_STRONG:
        return "Strong Oppo Authority", "Strong Oppo Authority"
    if oppo_pop >= OPPO_POP_ABOVE_AVERAGE:
        return "Above Average Oppo Pop", "Above Average Oppo Pop"
    if oppo_pop >= OPPO_POP_SOME_DAMAGE:
        return "Average / Some Oppo Damage", "Average / Some Oppo Damage"
    return "Limited Oppo Damage", "Limited Oppo Damage"


def directional_power_context(player: dict[str, Any]) -> tuple[str | None, str]:
    pull_pop = to_float(player.get("pullPop"))
    oppo_pop = to_float(player.get("oppoPop"))
    oppo_air_bbe = to_int(player.get("oppoAirBbe")) or 0

    if oppo_air_bbe < OPPO_POP_MIN_OPPO_AIR_BBE or oppo_pop is None:
        return (
            "Insufficient Oppo Sample",
            f"Opposite-field air sample is below the {OPPO_POP_MIN_OPPO_AIR_BBE} BBE display gate.",
        )

    if (
        pull_pop is not None
        and pull_pop >= DIRECTIONAL_PULL_STRONG
        and oppo_pop >= DIRECTIONAL_OPPO_STRONG
    ):
        return "All-Fields Thunder", "Strong pulled-air and opposite-field air power both show up."

    if oppo_pop >= DIRECTIONAL_OPPO_STRONG:
        return "Oppo Authority", "Opposite-field air power is the standout directional trait."

    if (
        pull_pop is not None
        and pull_pop >= DIRECTIONAL_PULL_STRONG
        and oppo_pop < DIRECTIONAL_OPPO_NEUTRAL_CEILING
    ):
        return "Pull-Heavy Power", "Pulled-air juice is the standout directional trait."

    if pull_pop is not None and pull_pop >= DIRECTIONAL_POP_AVERAGE and oppo_pop >= DIRECTIONAL_POP_AVERAGE:
        return "Directional Balance", "Pull and opposite-field air reads both sit above average."

    return None, "Directional air power is not strongly separated by field side yet."


def calculate_iso_breakdown(
    ab: int,
    doubles: int,
    triples: int,
    home_runs: int,
) -> dict[str, float | None]:
    if ab <= 0:
        return {
            "iso": None,
            "otfIso": None,
            "legsIso": None,
            "otfShare": None,
            "legsShare": None,
            "doublesShare": None,
            "triplesShare": None,
        }

    doubles_iso = doubles / ab
    triples_iso = (2 * triples) / ab
    fence_iso = (3 * home_runs) / ab
    legs_iso = doubles_iso + triples_iso
    iso = fence_iso + legs_iso
    if abs((fence_iso + legs_iso) - iso) > 1e-12:
        raise RuntimeError("ISO identity check failed: otfIso + legsIso must equal ISO.")

    return {
        "iso": round(float(iso), 3),
        "otfIso": round(float(fence_iso), 3),
        "legsIso": round(float(legs_iso), 3),
        "otfShare": round(float(fence_iso / iso), 3) if iso > 0 else None,
        "legsShare": round(float(legs_iso / iso), 3) if iso > 0 else None,
        "doublesShare": round(float(doubles_iso / iso), 3) if iso > 0 else None,
        "triplesShare": round(float(triples_iso / iso), 3) if iso > 0 else None,
    }


def summarize_iso_breakdown(players: list[dict[str, Any]]) -> dict[str, Any]:
    valid_players = [
        player
        for player in players
        if to_float(player.get("iso")) is not None
        and to_int(player.get("ab"))
    ]
    iso_values = [float(player["iso"]) for player in valid_players]
    iso_median = float(median(iso_values)) if iso_values else None

    return {
        "isoMedian": round(iso_median, 3) if iso_median is not None else None,
        "isoBreakdownQualifiedPlayers": len(valid_players),
    }


def season_start(season: int) -> date:
    return date(season, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY)


def read_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=RAW_COLUMNS)

    return pd.read_csv(path, dtype={"sv_id": "string"})


def normalize_event_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    if "pitcher_name" not in frame.columns and "player_name" in frame.columns:
        frame["pitcher_name"] = frame["player_name"]

    for column in RAW_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    if "bat_team" not in frame.columns or frame["bat_team"].isna().all():
        frame["bat_team"] = pd.NA

    top_mask = frame["inning_topbot"].astype("string").str.lower().eq("top")
    bottom_mask = frame["inning_topbot"].astype("string").str.lower().eq("bot")
    frame.loc[top_mask, "bat_team"] = frame.loc[top_mask, "away_team"]
    frame.loc[bottom_mask, "bat_team"] = frame.loc[bottom_mask, "home_team"]

    frame["events"] = frame["events"].astype("string")
    frame["type"] = frame["type"].astype("string")
    frame["hit_distance_sc"] = pd.to_numeric(frame["hit_distance_sc"], errors="coerce")
    frame["launch_speed"] = pd.to_numeric(frame["launch_speed"], errors="coerce")
    frame["launch_angle"] = pd.to_numeric(frame["launch_angle"], errors="coerce")
    frame["launch_speed_angle"] = pd.to_numeric(frame["launch_speed_angle"], errors="coerce")
    frame["hc_x"] = pd.to_numeric(frame["hc_x"], errors="coerce")
    frame["hc_y"] = pd.to_numeric(frame["hc_y"], errors="coerce")
    frame["bb_type"] = frame["bb_type"].astype("string")
    frame["stand"] = frame["stand"].astype("string")
    frame["batter"] = pd.to_numeric(frame["batter"], errors="coerce").astype("Int64")
    frame["pitcher"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["game_pk"] = pd.to_numeric(frame["game_pk"], errors="coerce").astype("Int64")
    frame["at_bat_number"] = pd.to_numeric(frame["at_bat_number"], errors="coerce").astype("Int64")
    frame["pitch_number"] = pd.to_numeric(frame["pitch_number"], errors="coerce").astype("Int64")

    bbe_mask = (
        frame["batter"].notna()
        & frame["launch_speed"].notna()
        & frame["launch_angle"].notna()
        & frame["events"].notna()
    )
    frame = frame[bbe_mask]
    return frame[RAW_COLUMNS]


def inspect_statcast_columns(frame: pd.DataFrame) -> None:
    columns = set(frame.columns)
    print("Statcast column availability:")
    for label, candidates in STATCAST_FIELD_GROUPS.items():
        present = [candidate for candidate in candidates if candidate in columns]
        status = ", ".join(present) if present else "not found"
        print(f"- {label}: {status}")


def fetch_statcast_events(start_date: date, end_date: date) -> pd.DataFrame:
    raise RuntimeError(
        "Direct BBE fetching has been replaced by the canonical pitch cache. "
        "Run scripts/generate_pitch_cache.py or let generate_hr_distance.py refresh "
        "data/raw/statcast-pitches.csv.gz, then derive BBE rows from that cache."
    )


def fetch_home_run_tracker(season: int, cat: str = HOME_RUN_TRACKER_CAT) -> pd.DataFrame:
    params = {
        "player_type": "Batter",
        "year": str(season),
        "cat": cat,
        "min": "0",
        "csv": "true",
    }
    url = f"{HOME_RUN_TRACKER_URL}?{urlencode(params)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Referer": HOME_RUN_TRACKER_URL,
    }

    print(f"Fetching Baseball Savant Home Run Tracker aggregate CSV ({cat})")
    print(f"Home Run Tracker URL: {url}")
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8-sig", errors="replace")
            content_type = response.headers.get("content-type", "")
    except Exception as error:
        raise RuntimeError(
            "Failed to fetch Baseball Savant Home Run Tracker aggregate CSV.\n"
            f"URL: {url}\n"
            "This source supplies context xHR fields and daily-feature inputs. "
            "If Baseball Savant is unavailable, rerun after the upstream service recovers."
        ) from error

    if "csv" not in content_type.lower() and not body.startswith('"player"'):
        raise RuntimeError(
            "Baseball Savant Home Run Tracker did not return CSV data.\n"
            f"URL: {url}\n"
            f"Content-Type: {content_type}\n"
            f"Response preview: {body[:200]}"
        )

    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        raise RuntimeError(f"Home Run Tracker returned zero rows for season {season}. URL: {url}")

    tracker = pd.DataFrame(rows)
    tracker["player_id"] = pd.to_numeric(tracker["player_id"], errors="coerce").astype("Int64")
    for column in ["hr_total", "xhr", "xhr_diff", "doubters", "mostly_gone", "no_doubters", "no_doubter_per"]:
        if column in tracker.columns:
            tracker[column] = pd.to_numeric(tracker[column], errors="coerce")

    return tracker


def fetch_batted_ball_leaderboard(season: int) -> pd.DataFrame:
    params = {
        "year": str(season),
        "sortColumn": "pull_air_rate",
        "sortDirection": "asc",
        "csv": "true",
    }
    url = f"{BATTED_BALL_LEADERBOARD_URL}?{urlencode(params)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Referer": BATTED_BALL_LEADERBOARD_URL,
    }

    print("Fetching Baseball Savant batted-ball leaderboard CSV for Pull AIR%")
    print(f"Batted-ball leaderboard URL: {url}")
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8-sig", errors="replace")
            content_type = response.headers.get("content-type", "")
    except Exception as error:
        raise RuntimeError(
            "Failed to fetch Baseball Savant batted-ball leaderboard CSV.\n"
            f"URL: {url}\n"
            "This source supplies the official Pull AIR% reference column."
        ) from error

    if "csv" not in content_type.lower() and not body.startswith('"id"'):
        raise RuntimeError(
            "Baseball Savant batted-ball leaderboard did not return CSV data.\n"
            f"URL: {url}\n"
            f"Content-Type: {content_type}\n"
            f"Response preview: {body[:200]}"
        )

    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        raise RuntimeError(f"Batted-ball leaderboard returned zero rows for season {season}. URL: {url}")

    leaderboard = pd.DataFrame(rows)
    leaderboard["player_id"] = pd.to_numeric(leaderboard["id"], errors="coerce").astype("Int64")
    for column in ["bbe", "pull_air_rate"]:
        if column in leaderboard.columns:
            leaderboard[column] = pd.to_numeric(leaderboard[column], errors="coerce")

    if "pull_air_rate" not in leaderboard.columns:
        raise RuntimeError(
            "Baseball Savant batted-ball leaderboard is missing pull_air_rate.\n"
            f"Columns: {', '.join(leaderboard.columns)}"
        )

    return leaderboard


def savant_headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": accept,
        "Referer": HOME_RUN_TRACKER_URL,
        "X-Requested-With": "XMLHttpRequest",
    }


def fetch_home_run_tracker_detail_rows(
    tracker: pd.DataFrame,
    season: int,
    cat: str = HOME_RUN_TRACKER_CAT,
) -> pd.DataFrame:
    cache_path = Path(HRT_DETAIL_CACHE_TEMPLATE.format(season=season, cat=cat))
    if cache_path.exists():
        print(f"Reading cached Baseball Savant Home Run Tracker detail rows ({cat}) from {cache_path}")
        details = pd.read_csv(cache_path)
        for column in ["game_pk", "batter_id", "pitcher_id", "ct", "hr_distance", "exit_velocity", "launch_angle", "hrt_hr_total"]:
            if column in details.columns:
                details[column] = pd.to_numeric(details[column], errors="coerce")
        for column in ["is_doubter_detail", "is_no_doubter_detail", "is_mostly_gone_detail"]:
            if column in details.columns:
                details[column] = details[column].astype("string").str.lower().isin({"true", "1", "yes"})
        return details

    detail_rows: list[dict[str, Any]] = []
    if tracker.empty:
        return pd.DataFrame()

    print(f"Fetching Baseball Savant Home Run Tracker detail rows ({cat})")
    for index, row in enumerate(tracker.to_dict("records"), start=1):
        player_id = to_int(row.get("player_id"))
        if player_id is None:
            continue

        params = {
            "type": "details",
            "player_id": str(player_id),
            "year": str(season),
            "player_type": "Batter",
            "cat": cat,
        }
        url = f"{HOME_RUN_TRACKER_URL}?{urlencode(params)}"
        request = Request(url, headers=savant_headers("application/json,text/plain,*/*"))
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urlopen(request, timeout=45) as response:
                    rows = json.loads(response.read().decode("utf-8-sig", errors="replace"))
                break
            except Exception as error:
                last_error = error
                if attempt < 3:
                    print(f"Detail fetch failed for player {player_id}; retrying ({attempt}/3)...")
                    time.sleep(attempt * 1.5)
        else:
            raise RuntimeError(
                "Failed to fetch Baseball Savant Home Run Tracker detail rows.\n"
                f"URL: {url}\n"
                "These rows classify actual home runs for the CHEAPIES card."
            ) from last_error

        for detail in rows:
            detail["hrt_hr_total"] = row.get("hr_total")
            detail_rows.append(detail)

        if index % 50 == 0:
            print(f"Fetched detail rows for {index} Home Run Tracker hitters...")
        time.sleep(0.02)

    details = pd.DataFrame(detail_rows)
    if details.empty:
        return details

    for column in ["game_pk", "batter_id", "pitcher_id", "ct", "hr_distance", "exit_velocity", "launch_angle", "hrt_hr_total"]:
        if column in details.columns:
            details[column] = pd.to_numeric(details[column], errors="coerce")

    hr_cat = details.get("hr_cat", pd.Series("", index=details.index)).astype("string").str.lower()
    ct = pd.to_numeric(details.get("ct", pd.Series(pd.NA, index=details.index)), errors="coerce")
    missing_hr_cat = hr_cat.isna() | hr_cat.eq("")
    details["is_doubter_detail"] = hr_cat.eq("doubter") | (missing_hr_cat & ct.le(7))
    details["is_no_doubter_detail"] = hr_cat.eq("no doubter") | (missing_hr_cat & ct.eq(30))
    details["is_mostly_gone_detail"] = hr_cat.eq("mostly gone") | (missing_hr_cat & ct.between(8, 29, inclusive="both"))
    return details


def join_home_run_tracker_details(details: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if details.empty or events.empty:
        return pd.DataFrame()

    statcast = events[
        [
            "game_date",
            "game_pk",
            "batter",
            "player_name",
            "bat_team",
            "pitcher",
            "pitcher_name",
            "home_team",
            "away_team",
            "inning_topbot",
            "events",
            "hit_distance_sc",
            "launch_speed",
            "launch_angle",
            "hc_x",
            "hc_y",
            "stand",
        ]
    ].copy()
    for column in ["game_pk", "batter", "pitcher", "hit_distance_sc", "launch_speed", "launch_angle", "hc_x", "hc_y"]:
        statcast[column] = pd.to_numeric(statcast[column], errors="coerce")

    left = details.reset_index(names="detail_id")
    merged = left.merge(
        statcast,
        left_on=["game_pk", "batter_id", "pitcher_id"],
        right_on=["game_pk", "batter", "pitcher"],
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
    candidates["match_score"] = (
        candidates["distance_diff"].fillna(999)
        + candidates["ev_diff"].fillna(999)
        + candidates["la_diff"].fillna(999)
    )
    candidates = candidates.sort_values(["detail_id", "match_score"])
    return candidates.drop_duplicates("detail_id", keep="first")


def hr_category_score(value: Any, parks_cleared: float | None = None) -> int:
    if parks_cleared is not None and pd.notna(parks_cleared):
        if parks_cleared >= 30:
            return 3
        if parks_cleared >= 8:
            return 2
        return 1

    category = str(value or "").strip().lower()
    if "no" in category and "doubter" in category:
        return 3
    if "mostly" in category:
        return 2
    if "doubter" in category:
        return 1
    return 0


def pitcher_team_from_event(row: pd.Series) -> str:
    inning_topbot = str(first_present(row, "inning_topbot", "inning_topbot_statcast") or "").lower()
    if inning_topbot == "top":
        return str(first_present(row, "home_team", "home_team_statcast") or "")
    if inning_topbot == "bot":
        return str(first_present(row, "away_team", "away_team_statcast") or "")
    return ""


def first_present(row: pd.Series, *columns: str) -> Any:
    for column in columns:
        if column in row.index:
            value = row.get(column)
            if value is not None and not pd.isna(value):
                return value
    return None


def is_public_play_url(value: Any) -> bool:
    url = str(value or "")
    return bool(url) and "research.mlb.com" not in url and "/login" not in url


def prepare_daily_feature_candidates(joined: pd.DataFrame) -> pd.DataFrame:
    if joined.empty:
        return pd.DataFrame()

    candidates = joined.copy()
    date_column = next((column for column in ["game_date_statcast", "game_date", "game_date_detail"] if column in candidates.columns), None)
    if date_column is None:
        return pd.DataFrame()

    candidates["daily_feature_game_date"] = pd.to_datetime(candidates[date_column], errors="coerce").dt.date
    candidates = candidates[candidates["daily_feature_game_date"].notna()].copy()
    if candidates.empty:
        return candidates

    candidates["parks_cleared"] = pd.to_numeric(candidates.get("ct"), errors="coerce")
    candidates["distance_value"] = pd.to_numeric(candidates.get("hr_distance"), errors="coerce").fillna(
        pd.to_numeric(candidates.get("hit_distance_sc"), errors="coerce")
    )
    candidates["exit_velocity_value"] = pd.to_numeric(candidates.get("exit_velocity"), errors="coerce").fillna(
        pd.to_numeric(candidates.get("launch_speed"), errors="coerce")
    )
    candidates["category_strength"] = candidates.apply(
        lambda row: hr_category_score(row.get("hr_cat"), to_float(row.get("parks_cleared"))),
        axis=1,
    )
    return candidates


def event_outcome(row: pd.Series) -> str:
    outcome = str(first_present(row, "events", "result") or "").strip()
    return outcome.replace("_", " ").title() if outcome else ""


def daily_feature_event(row: pd.Series, score: float | None = None) -> dict[str, Any]:
    play_url = row.get("play_url") or row.get("video") or row.get("video_url")
    game_date = str(row.get("daily_feature_game_date"))
    batter = str(first_present(row, "player_name_statcast", "player_name") or "").strip()
    pitcher = display_name(first_present(row, "pitcher_name", "pitcher_name_statcast"))
    distance = int(round(float(row["distance_value"]))) if pd.notna(row.get("distance_value")) else None
    exit_velocity = round(float(row["exit_velocity_value"]), 1) if pd.notna(row.get("exit_velocity_value")) else None
    event_key = f"{game_date}|{batter}|{pitcher}|{distance}|{exit_velocity}"
    play_id = first_present(row, "play_id", "play_id_detail", "play_id_statcast")
    return {
        "eventKey": event_key,
        **({"playId": str(play_id)} if play_id else {}),
        "gameDate": game_date,
        "batter": batter,
        "batterId": to_int(first_present(row, "batter", "batter_id")),
        "batterTeam": str(first_present(row, "bat_team", "bat_team_statcast") or "").strip(),
        "pitcher": pitcher,
        "pitcherId": to_int(first_present(row, "pitcher", "pitcher_id")),
        "pitcherTeam": pitcher_team_from_event(row),
        "distance": distance,
        "exitVelocity": exit_velocity,
        "launchAngle": round(float(first_present(row, "launch_angle_statcast", "launch_angle")), 1)
        if first_present(row, "launch_angle_statcast", "launch_angle") is not None
        else None,
        "hrCat": str(row.get("hr_cat") or "").strip(),
        "parksCleared": to_int(row.get("parks_cleared")),
        "eventOutcome": event_outcome(row),
        "score": round(float(score), 1) if score is not None and pd.notna(score) else None,
        **({"playUrl": str(play_url)} if is_public_play_url(play_url) else {}),
    }


def build_daily_features(joined: pd.DataFrame) -> dict[str, Any] | None:
    candidates = prepare_daily_feature_candidates(joined)
    if candidates.empty:
        return None

    latest_date = candidates["daily_feature_game_date"].max()
    latest = candidates[candidates["daily_feature_game_date"].eq(latest_date)].copy()
    latest["longball_score"] = (
        latest["category_strength"].fillna(0) * 100
        + latest["parks_cleared"].fillna(0)
        + latest["distance_value"].fillna(0) / 10
        + latest["exit_velocity_value"].fillna(0)
    )

    actual_hrs = latest[latest["events"].astype("string").str.lower().eq("home_run")].copy()
    non_hrs = latest[~latest["events"].astype("string").str.lower().eq("home_run")].copy()

    daily_dong = None
    if not actual_hrs.empty:
        winner = actual_hrs.sort_values(
            ["category_strength", "parks_cleared", "distance_value", "exit_velocity_value"],
            ascending=False,
        ).iloc[0]
        daily_dong = daily_feature_event(winner, winner.get("longball_score"))

    hot_dog_robbery = None
    if not non_hrs.empty:
        winner = non_hrs.sort_values(
            ["parks_cleared", "distance_value", "exit_velocity_value"],
            ascending=False,
        ).iloc[0]
        hot_dog_robbery = daily_feature_event(winner, winner.get("longball_score"))

    cheapest_dong = None
    if not actual_hrs.empty:
        doubters = actual_hrs[actual_hrs["category_strength"].eq(1)]
        cheapie_pool = doubters if not doubters.empty else actual_hrs
        winner = cheapie_pool.sort_values(
            ["parks_cleared", "distance_value", "exit_velocity_value"],
            ascending=True,
        ).iloc[0]
        cheapest_dong = daily_feature_event(winner, winner.get("longball_score"))

    return {
        "gameDate": str(latest_date),
        "dailyDong": daily_dong,
        "hotDogRobbery": hot_dog_robbery,
        "cheapestDong": cheapest_dong,
    }


def calculate_actual_cheapies(
    events: pd.DataFrame,
    tracker: pd.DataFrame,
    season: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    details = fetch_home_run_tracker_detail_rows(tracker, season)
    validate_hrt_detail_completeness(details, season, label="production HRT detail pull")
    joined = join_home_run_tracker_details(details, events)
    actual_joined = joined[joined["events"].astype("string").str.lower().eq("home_run")].copy()
    daily_features = build_daily_features(joined)
    daily_dong = daily_features.get("dailyDong") if daily_features else None
    statcast_actual_hrs = int(events["events"].astype("string").str.lower().eq("home_run").sum())
    hrt_actual_hrs = int(details["result"].astype("string").str.lower().eq("home_run").sum()) if "result" in details.columns else 0
    joined_actual_hrs = int(len(actual_joined))
    detail_rows = int(len(details))
    join_rate = float(len(joined) / detail_rows) if detail_rows else 0.0
    actual_hr_match_rate = float(joined_actual_hrs / hrt_actual_hrs) if hrt_actual_hrs else 0.0
    source = "actual-home-run-classification" if join_rate >= CHEAPIE_JOIN_MIN_RATE and actual_hr_match_rate >= CHEAPIE_JOIN_MIN_RATE else "avg-distance-proxy"

    print("\n=== CHEAPIES actual HR classification diagnostics ===")
    print(f"Total Home Run Tracker detail rows fetched: {detail_rows}")
    print(f"Total joined to Statcast: {len(joined)}")
    print(f"Join rate: {join_rate:.1%}" if detail_rows else "Join rate: n/a")
    print(f"Total joined actual HR rows: {joined_actual_hrs}")
    print(f"Total actual HR rows expected from Statcast: {statcast_actual_hrs}")
    print(f"Home Run Tracker actual HR detail rows: {hrt_actual_hrs}")
    print(f"Actual HR match rate vs Home Run Tracker details: {actual_hr_match_rate:.1%}" if hrt_actual_hrs else "Actual HR match rate: n/a")
    print(f"CHEAPIES source: {source}")
    if daily_dong:
        print(
            "Daily Dong: "
            f"{daily_dong.get('gameDate')} | {daily_dong.get('batter')} vs {daily_dong.get('pitcher')} | "
            f"{daily_dong.get('distance')} ft, {daily_dong.get('exitVelocity')} mph, "
            f"{daily_dong.get('hrCat') or 'HR'}, {daily_dong.get('parksCleared')}/30 parks"
        )
    if daily_features:
        for label, key in [
            ("Hot Dog Robbery", "hotDogRobbery"),
            ("Cheapest Dong", "cheapestDong"),
        ]:
            feature = daily_features.get(key)
            if feature:
                print(
                    f"{label}: "
                    f"{feature.get('gameDate')} | {feature.get('batter')} vs {feature.get('pitcher')} | "
                    f"{feature.get('distance')} ft, {feature.get('exitVelocity')} mph, "
                    f"{feature.get('eventOutcome') or feature.get('hrCat') or 'event'}, "
                    f"{feature.get('parksCleared')}/30 parks"
                )

    if source != "actual-home-run-classification":
        return {}, {
            "cheapieSource": source,
            "homeRunTrackerDetailRows": detail_rows,
            "homeRunTrackerDetailJoinedRows": int(len(joined)),
            "homeRunTrackerDetailJoinRate": round(join_rate, 4),
            "homeRunTrackerActualHrRows": hrt_actual_hrs,
            "joinedActualHrRows": joined_actual_hrs,
            "actualHrMatchRate": round(actual_hr_match_rate, 4),
        }, daily_features

    grouped = actual_joined.groupby("batter_id", as_index=False).agg(
        actualDoubterHr=("is_doubter_detail", "sum"),
        actualMostlyGoneHr=("is_mostly_gone_detail", "sum"),
        actualNoDoubterHr=("is_no_doubter_detail", "sum"),
        joinedActualHr=("events", "size"),
    )
    cheapies = {
        int(row["batter_id"]): {
            "actualDoubterHr": int(row["actualDoubterHr"]),
            "actualMostlyGoneHr": int(row["actualMostlyGoneHr"]),
            "actualNoDoubterHr": int(row["actualNoDoubterHr"]),
            "joinedActualHr": int(row["joinedActualHr"]),
        }
        for row in grouped.to_dict("records")
        if pd.notna(row.get("batter_id"))
    }
    return cheapies, {
        "cheapieSource": source,
        "homeRunTrackerDetailRows": detail_rows,
        "homeRunTrackerDetailJoinedRows": int(len(joined)),
        "homeRunTrackerDetailJoinRate": round(join_rate, 4),
        "homeRunTrackerActualHrRows": hrt_actual_hrs,
        "joinedActualHrRows": joined_actual_hrs,
        "actualHrMatchRate": round(actual_hr_match_rate, 4),
    }, daily_features


def build_lbi_v14_scored_events(events: pd.DataFrame, standard_tracker: pd.DataFrame, season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    standard_details = fetch_home_run_tracker_detail_rows(standard_tracker, season, cat=STANDARD_HOME_RUN_TRACKER_CAT)
    validate_hrt_detail_completeness(standard_details, season, label="LBI v1.4 standard HRT detail pull")
    joined = join_home_run_tracker_details(standard_details, events)
    if joined.empty:
        raise RuntimeError("LBI v1.4 standard HRT detail rows could not be joined to Statcast events.")

    joined["standard_parks_cleared"] = pd.to_numeric(joined.get("ct"), errors="coerce")
    scored, cells = add_lbi_v14_event_columns(
        joined,
        standard_parks_col="standard_parks_cleared",
        result_col="result",
        ev_col="exit_velocity",
        distance_col="hr_distance",
        launch_angle_col="launch_angle_detail",
        hc_x_col="hc_x",
        hc_y_col="hc_y",
        stand_col="stand",
    )
    known_spray = int(scored["spray_bucket"].notna().sum()) if "spray_bucket" in scored else 0
    diagnostics = {
        "lbiV14StandardDetailRows": int(len(standard_details)),
        "lbiV14StandardJoinedRows": int(len(joined)),
        "lbiV14StandardJoinRate": round(float(len(joined) / len(standard_details)), 4) if len(standard_details) else 0,
        "lbiV14EligibleEvents": int(len(scored)),
        "lbiV14ActualHrEvents": int(scored["result_norm"].astype("string").str.lower().eq("home_run").sum()),
        "lbiV14RobbedEvents": int((scored["lbi_v14_eligibility_reason"] == "non_hr_standard_parks_8_plus").sum()),
        "lbiV14KnownSprayEvents": known_spray,
        "lbiV14KnownSprayRate": round(float(known_spray / len(scored)), 4) if len(scored) else 0,
        "lbiV14ImprobabilityCells": int(len(cells)),
        "lbiV14Eligibility": (
            "14-50 degree launch angle and physical standard park-count gate: "
            "actual HR with 1+ standard parks or non-HR with 8+ standard parks."
        ),
    }
    print("\n=== LBI v1.4 event scoring diagnostics ===")
    print(f"Standard HRT detail rows: {diagnostics['lbiV14StandardDetailRows']:,}")
    print(f"Joined standard detail rows: {diagnostics['lbiV14StandardJoinedRows']:,}")
    print(f"Standard detail join rate: {diagnostics['lbiV14StandardJoinRate']:.1%}")
    print(f"LBI v1.4 eligible events: {diagnostics['lbiV14EligibleEvents']:,}")
    print(f"Actual HR eligible events: {diagnostics['lbiV14ActualHrEvents']:,}")
    print(f"Robbed 8+ park eligible events: {diagnostics['lbiV14RobbedEvents']:,}")
    print(f"Known true-spray rate among eligible events: {diagnostics['lbiV14KnownSprayRate']:.1%}")
    return scored, diagnostics


def lookup_player_names(batter_ids: list[int]) -> dict[int, str]:
    if not batter_ids:
        return {}

    try:
        lookup = playerid_reverse_lookup(batter_ids, key_type="mlbam")
    except Exception as error:
        print(f"Player name lookup failed; falling back to batter ids. Error: {error}")
        return {}

    names: dict[int, str] = {}
    for row in lookup.to_dict("records"):
        mlbam_id = row.get("key_mlbam")
        first = str(row.get("name_first") or "").strip()
        last = str(row.get("name_last") or "").strip()

        if pd.notna(mlbam_id) and (first or last):
            names[int(mlbam_id)] = f"{first} {last}".strip().title()

    return names


def name_from_description(description: Any) -> str | None:
    if pd.isna(description):
        return None

    text = str(description)
    markers = [
        " homers ",
        " singles ",
        " doubles ",
        " triples ",
        " grounds out",
        " flies out",
        " lines out",
        " pops out",
        " reaches",
    ]
    matches = [text.find(marker) for marker in markers if marker in text]
    if not matches:
        return None

    name = text[: min(matches)].strip()
    return name.title() if name else None


def add_player_names(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    batter_ids = sorted(frame["batter"].dropna().astype(int).unique().tolist())
    names = lookup_player_names(batter_ids)

    if names:
        frame["player_name"] = frame["batter"].map(names)

    fallback_names = frame["player_name"].isna() | frame["player_name"].astype("string").str.strip().eq("")
    if "des" in frame.columns:
        frame.loc[fallback_names, "player_name"] = frame.loc[fallback_names, "des"].map(name_from_description)

    fallback_names = frame["player_name"].isna() | frame["player_name"].astype("string").str.strip().eq("")
    frame.loc[fallback_names, "player_name"] = "MLBAM " + frame.loc[fallback_names, "batter"].astype(str)
    return frame


def merge_events(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    events = pd.concat([existing, incoming], ignore_index=True)
    events = normalize_event_frame(events)

    if events.empty:
        return events

    events = add_player_names(events)
    events["dedupe_key"] = events["sv_id"].astype("string")
    fallback_key = (
        events["game_pk"].astype("string")
        + ":"
        + events["at_bat_number"].astype("string")
        + ":"
        + events["pitch_number"].astype("string")
        + ":"
        + events["batter"].astype("string")
    )
    events.loc[events["dedupe_key"].isna() | events["dedupe_key"].eq(""), "dedupe_key"] = fallback_key
    events = events.drop_duplicates(subset=["dedupe_key"], keep="last")
    events = events.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])
    return events[RAW_COLUMNS]


def write_events(path: Path, events: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(path, index=False, columns=RAW_COLUMNS)


def read_hcy_lookup(season: int, raw_cache: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    columns = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "hc_y"]
    for path in hcy_source_paths(season, raw_cache):
        if not path.exists():
            continue
        header = pd.read_csv(path, nrows=0).columns
        if "hc_y" not in header:
            continue
        usecols = [column for column in columns if column in header]
        if set(columns) - set(usecols):
            continue
        frame = pd.read_csv(path, usecols=usecols)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=columns)
    lookup = pd.concat(frames, ignore_index=True)
    for column in columns:
        lookup[column] = pd.to_numeric(lookup[column], errors="coerce")
    lookup = lookup.dropna(subset=["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "hc_y"])
    return lookup.drop_duplicates(["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"], keep="last")


def ensure_true_spray_coordinates(events: pd.DataFrame, season: int, raw_cache: Path) -> pd.DataFrame:
    out = events.copy()
    if "hc_y" not in out.columns:
        out["hc_y"] = pd.NA
    initial_coverage = float(out["hc_y"].notna().mean()) if len(out) else 1.0
    if initial_coverage >= HCY_MIN_BBE_COVERAGE:
        return out

    lookup = read_hcy_lookup(season, raw_cache)
    if lookup.empty:
        raise RuntimeError(
            "LBI v1.4 requires true two-coordinate spray, but no hc_y source was available.\n"
            f"Checked: {', '.join(str(path) for path in hcy_source_paths(season, raw_cache))}\n"
            "Do not fall back to hc_x-only spray. Refresh the canonical pitch cache with hc_y."
        )

    key_columns = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"]
    merged = out.merge(lookup, on=key_columns, how="left", suffixes=("", "_lookup"))
    merged["hc_y"] = pd.to_numeric(merged["hc_y"], errors="coerce").fillna(
        pd.to_numeric(merged["hc_y_lookup"], errors="coerce")
    )
    merged = merged.drop(columns=["hc_y_lookup"])
    coverage = float(merged["hc_y"].notna().mean()) if len(merged) else 1.0
    if coverage < HCY_MIN_BBE_COVERAGE:
        raise RuntimeError(
            "LBI v1.4 true spray coverage is too low for production scoring.\n"
            f"hc_y coverage after recovery: {coverage:.1%}; required >= {HCY_MIN_BBE_COVERAGE:.0%}.\n"
            "Do not fall back to hc_x-only spray. Refresh Statcast with hc_y before shipping."
        )
    print(f"Recovered true-spray hc_y coverage for LBI v1.4: {initial_coverage:.1%} -> {coverage:.1%}")
    return merged


def estimated_team_games(events: pd.DataFrame) -> int:
    if events.empty:
        return 0

    team_games = events.dropna(subset=["bat_team", "game_pk"]).groupby("bat_team")["game_pk"].nunique()
    if team_games.empty:
        return 0

    return int(team_games.max())


def floating_lbi_bbe_minimum(team_games: int) -> int:
    if team_games <= 0:
        return LBI_MINIMUM_BBE_FLOOR

    season_progress_games = min(team_games, MLB_SCHEDULED_TEAM_GAMES)
    progress_floor = round(LBI_FULL_SEASON_BBE_TARGET * season_progress_games / MLB_SCHEDULED_TEAM_GAMES)
    return min(LBI_FULL_SEASON_BBE_TARGET, max(LBI_MINIMUM_BBE_FLOOR, progress_floor))


def lbi_score_from_percentile(percentile: float) -> float:
    clipped = min(max(percentile, 0.01), 0.99)
    return 100 + (NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped))


def component_percentiles(players: list[dict[str, Any]], key: str) -> dict[int, float]:
    value_key = LBI_COMPONENT_VALUE_KEYS.get(key, key)
    values = pd.Series([player.get(value_key) for player in players], dtype="float64")
    percentiles = values.rank(method="average", pct=True)
    return {
        id(player): float(percentile)
        for player, percentile in zip(players, percentiles)
        if pd.notna(percentile) and player.get(value_key) is not None
    }


def sample_badge(player: dict[str, Any], bbe_minimum: int) -> str:
    if player["bbe"] >= bbe_minimum * 1.6:
        return "Reliable Sample"

    if player["barrels"] < 10 and player["longballIndex"] >= 125:
        return "Small Sample Monster"

    if player["barrelRate"] >= 0.18 and player["hardHitRate"] >= 0.50:
        return "No-Doubter Candidate"

    if player["avgDistanceOnBarrels"] is not None and player["avgDistanceOnBarrels"] <= 350:
        return "Wall-Scraper Watch"

    return "Qualified Sample"


def lbi_components_for_player(
    player: dict[str, Any],
    percentile_maps: dict[str, dict[int, float]],
) -> tuple[float, dict[str, dict[str, float | None]]]:
    components: dict[str, dict[str, float | None]] = {}
    total_weight = 0.0
    weighted_score = 0.0

    for key in LBI_COMPONENT_WEIGHTS:
        value_key = LBI_COMPONENT_VALUE_KEYS.get(key, key)
        base_weight = LBI_COMPONENT_WEIGHTS.get(key, 0)
        if not base_weight:
            components[key] = {
                "value": player.get(value_key),
                "percentile": None,
                "score": None,
                "weight": 0,
            }
            continue

        percentile = percentile_maps[key].get(id(player))
        if percentile is None:
            components[key] = {
                "value": player.get(value_key),
                "percentile": None,
                "score": None,
                "weight": 0,
            }
            continue

        score = lbi_score_from_percentile(percentile)
        components[key] = {
            "value": player.get(value_key),
            "percentile": round(percentile, 4),
            "score": round(score, 1),
            "weight": base_weight,
        }
        total_weight += base_weight
        weighted_score += score * base_weight

    if total_weight == 0:
        return 0, components

    for component in components.values():
        component["weight"] = round(float(component["weight"]) / total_weight, 4) if component["weight"] else 0

    return round(weighted_score / total_weight, 1), components


def build_leaderboard(
    events: pd.DataFrame,
    home_run_tracker: pd.DataFrame,
    lbi_v14_events: pd.DataFrame,
    batted_ball_leaderboard: pd.DataFrame,
    contact_metrics: dict[int, dict[str, Any]],
    contact_diagnostics: ContactMetricDiagnostics,
    actual_cheapies: dict[int, dict[str, Any]],
    cheapie_source: str,
    minimum_hr: int,
    minimum_pa: int | None,
) -> tuple[list[dict[str, Any]], int, int, dict[str, Any]]:
    if events.empty:
        return [], 0, 0, {
            "qualified": 0,
            "matchedHomeRunTracker": 0,
            "missingHomeRunTracker": 0,
            "matchedBattedBallLeaderboard": 0,
            "missingBattedBallLeaderboard": 0,
        }

    team_games = estimated_team_games(events)
    bbe_minimum = floating_lbi_bbe_minimum(team_games)
    grouped = events.groupby(["batter", "player_name"], dropna=False)
    tracker_by_batter = {}
    if not home_run_tracker.empty:
        tracker_by_batter = {
            int(row["player_id"]): row
            for row in home_run_tracker.to_dict("records")
            if pd.notna(row.get("player_id"))
        }
    batted_ball_by_batter = {}
    if not batted_ball_leaderboard.empty:
        batted_ball_by_batter = {
            int(row["player_id"]): row
            for row in batted_ball_leaderboard.to_dict("records")
            if pd.notna(row.get("player_id"))
        }

    players = []
    matched_home_run_tracker = 0
    missing_home_run_tracker = 0
    matched_batted_ball_leaderboard = 0
    missing_batted_ball_leaderboard = 0
    matched_contact_metrics = 0
    missing_contact_metrics = 0
    iso_hr_mismatches = 0
    integrity_quarantined: list[dict[str, Any]] = []

    for (batter, player), group in grouped:
        bbe = int(len(group))
        if bbe < bbe_minimum:
            continue

        batter_id = int(batter)
        contact_row = contact_metrics.get(batter_id, {})
        pa_count = to_int(contact_row.get("contactPa"))
        if pa_count is None or pa_count <= 0:
            raise RuntimeError(
                "Missing true terminal PA from contact metrics for "
                f"{player} ({batter_id}); refusing to fall back to BBE."
            )
        if pa_count < bbe:
            raise RuntimeError(
                "True terminal PA is smaller than BBE for "
                f"{player} ({batter_id}): PA {pa_count}, BBE {bbe}."
            )
        if minimum_pa is not None and pa_count < minimum_pa:
            continue

        home_runs = group[group["events"].astype("string").str.lower().eq("home_run")]
        hr_count = int(len(home_runs))

        team = group["bat_team"].dropna().astype(str)
        launch_speeds = pd.to_numeric(group["launch_speed"], errors="coerce")
        launch_angles = pd.to_numeric(group["launch_angle"], errors="coerce")
        barrel_values = pd.to_numeric(group["launch_speed_angle"], errors="coerce")
        barrels = group[barrel_values.eq(6)]
        hard_hits = launch_speeds.ge(95)
        sweet_spots = launch_angles.between(8, 32)
        stand = group["stand"].astype("string").str.upper()
        pulled = (stand.eq("R") & pd.to_numeric(group["hc_x"], errors="coerce").lt(125)) | (
            stand.eq("L") & pd.to_numeric(group["hc_x"], errors="coerce").gt(125)
        )
        oppo = (stand.eq("R") & pd.to_numeric(group["hc_x"], errors="coerce").gt(125)) | (
            stand.eq("L") & pd.to_numeric(group["hc_x"], errors="coerce").lt(125)
        )
        pulled_air = pulled & launch_angles.between(15, 45)
        oppo_air = oppo & launch_angles.between(15, 45)
        crushed_pulled_air = pulled_air & launch_speeds.ge(105)
        pull_pop_weighted_events = float(pull_pop_event_scores(pulled, launch_speeds, launch_angles).sum())
        oppo_pop_weighted_events = float(pull_pop_event_scores(oppo, launch_speeds, launch_angles).sum())
        hr_window_thunder = launch_speeds.ge(105) & launch_angles.between(25, 40)
        pulled_air_bbe = int(pulled_air.sum())
        oppo_air_bbe = int(oppo_air.sum())
        crushed_pulled_air_bbe = int(crushed_pulled_air.sum())
        hr_window_thunder_bbe = int(hr_window_thunder.sum())
        pull_air_juice = float(pull_pop_weighted_events / pa_count) if pa_count else None
        oppo_air_juice = float(oppo_pop_weighted_events / pa_count) if pa_count else None
        barrel_distances = pd.to_numeric(barrels["hit_distance_sc"], errors="coerce").dropna()
        barrel_launch_angles = pd.to_numeric(barrels["launch_angle"], errors="coerce").dropna()
        hr_distances = pd.to_numeric(home_runs["hit_distance_sc"], errors="coerce").dropna()
        tracker_row = tracker_by_batter.get(batter_id)
        batted_ball_row = batted_ball_by_batter.get(batter_id)

        if tracker_row:
            matched_home_run_tracker += 1
        else:
            missing_home_run_tracker += 1

        should_quarantine, quarantine_reason = is_missing_hrt_statcast_contradiction(
            hrt_missing=tracker_row is None,
            bbe=bbe,
            ev90=launch_speeds.quantile(0.90) if launch_speeds.notna().any() else None,
            thunder_bbe=hr_window_thunder_bbe,
            barrels=len(barrels),
            hr=hr_count,
            min_bbe=bbe_minimum,
        )
        if should_quarantine:
            integrity_quarantined.append(
                {
                    "batter": batter_id,
                    "player": str(player),
                    "bbe": bbe,
                    "ev90": round(float(launch_speeds.quantile(0.90)), 1) if launch_speeds.notna().any() else None,
                    "hrWindowThunderBbe": hr_window_thunder_bbe,
                    "hr": hr_count,
                    "integrityReason": quarantine_reason,
                }
            )
            continue

        if batted_ball_row:
            matched_batted_ball_leaderboard += 1
        else:
            missing_batted_ball_leaderboard += 1

        if contact_row.get("contactPct") is not None:
            matched_contact_metrics += 1
        else:
            missing_contact_metrics += 1

        xhr = to_float(tracker_row.get("xhr")) if tracker_row else None
        xhr_diff = to_float(tracker_row.get("xhr_diff")) if tracker_row else None
        no_doubters = to_int(tracker_row.get("no_doubters")) if tracker_row else None
        doubters = to_int(tracker_row.get("doubters")) if tracker_row else None
        mostly_gone = to_int(tracker_row.get("mostly_gone")) if tracker_row else None
        no_doubter_rate = to_float(tracker_row.get("no_doubter_per")) if tracker_row else None
        if no_doubter_rate is not None:
            no_doubter_rate = no_doubter_rate / 100
        cheapie_row = actual_cheapies.get(batter_id, {})
        actual_doubter_hr = cheapie_row.get("actualDoubterHr") if cheapie_source == "actual-home-run-classification" else None
        actual_mostly_gone_hr = cheapie_row.get("actualMostlyGoneHr") if cheapie_source == "actual-home-run-classification" else None
        actual_no_doubter_hr = cheapie_row.get("actualNoDoubterHr") if cheapie_source == "actual-home-run-classification" else None
        cheapie_rate = None
        if actual_doubter_hr is not None and hr_count:
            cheapie_rate = float(actual_doubter_hr / hr_count)
        pull_air_rate = to_float(batted_ball_row.get("pull_air_rate")) if batted_ball_row else None
        if pull_air_rate is not None and pull_air_rate > 1:
            pull_air_rate = pull_air_rate / 100
        ab_count = to_int(contact_row.get("ab")) or 0
        hits_count = to_int(contact_row.get("hits")) or 0
        doubles_count = to_int(contact_row.get("doubles")) or 0
        triples_count = to_int(contact_row.get("triples")) or 0
        batting_home_runs = to_int(contact_row.get("battingHomeRuns")) or 0
        if batting_home_runs != hr_count:
            iso_hr_mismatches += 1
        iso_breakdown = calculate_iso_breakdown(ab_count, doubles_count, triples_count, batting_home_runs)

        players.append(
            {
                "batter": batter_id,
                "player": str(player),
                "team": team.iloc[-1] if not team.empty else "",
                "bbe": bbe,
                "pa": pa_count,
                "hr": hr_count,
                "battingHomeRuns": batting_home_runs,
                "ab": ab_count,
                "hits": hits_count,
                "doubles": doubles_count,
                "triples": triples_count,
                **iso_breakdown,
                "xhr": round(xhr, 1) if xhr is not None else None,
                "xhrPerBbe": round(float(xhr / bbe), 4) if xhr is not None and bbe else None,
                "xhrDiff": round(xhr_diff, 1) if xhr_diff is not None else None,
                "noDoubters": no_doubters,
                "doubters": doubters,
                "mostlyGone": mostly_gone,
                "noDoubterRate": round(no_doubter_rate, 3) if no_doubter_rate is not None else None,
                "actualDoubterHr": int(actual_doubter_hr) if actual_doubter_hr is not None else None,
                "actualMostlyGoneHr": int(actual_mostly_gone_hr) if actual_mostly_gone_hr is not None else None,
                "actualNoDoubterHr": int(actual_no_doubter_hr) if actual_no_doubter_hr is not None else None,
                "cheapieRate": round(cheapie_rate, 3) if cheapie_rate is not None else None,
                "cheapieSource": cheapie_source,
                "barrels": int(len(barrels)),
                "barrelRate": round(float(len(barrels) / bbe), 3),
                "hrWindowThunderBbe": hr_window_thunder_bbe,
                "hrWindowThunderRate": round(float(hr_window_thunder_bbe / bbe), 4),
                "hardHitRate": round(float(hard_hits.sum() / bbe), 3),
                "maxExitVelocity": round(float(launch_speeds.dropna().max()), 1) if launch_speeds.notna().any() else None,
                "sweetSpotRate": round(float(sweet_spots.sum() / bbe), 3),
                "pullAirRate": round(float(pull_air_rate), 3) if pull_air_rate is not None else None,
                "pullAirSource": "baseball-savant-batted-ball" if pull_air_rate is not None else "unavailable",
                "pulledAirBbe": pulled_air_bbe,
                "oppoAirBbe": oppo_air_bbe,
                "crushedPulledAirBbe": crushed_pulled_air_bbe,
                "pullAirJuice": round(pull_air_juice, 4) if pull_air_juice is not None else None,
                "pullAirJuicePer100Pa": round(pull_air_juice * 100, 1) if pull_air_juice is not None else None,
                "oppoAirJuice": round(oppo_air_juice, 4) if oppo_air_juice is not None else None,
                "oppoAirJuicePer100Pa": round(oppo_air_juice * 100, 1) if oppo_air_juice is not None else None,
                "contactPct": round(float(contact_row["contactPct"]), 4)
                if contact_row.get("contactPct") is not None
                else None,
                "contactSwings": int(contact_row["contactSwings"])
                if contact_row.get("contactSwings") is not None
                else None,
                "contactPa": pa_count,
                "avgDistanceOnBarrels": round(float(barrel_distances.mean()), 1)
                if len(barrel_distances) and len(barrels) >= 5
                else None,
                "avgLaunchAngleOnBarrels": round(float(barrel_launch_angles.mean()), 1)
                if len(barrel_launch_angles) and len(barrels) >= 3
                else None,
                "avgLaunchAngle": round(float(launch_angles.dropna().mean()), 1) if launch_angles.notna().any() else None,
                "avgDistance": round(float(hr_distances.mean()), 1) if len(hr_distances) else 0,
                "longestHr": round(float(hr_distances.max())) if len(hr_distances) else 0,
                "avgExitVelocity": round(float(launch_speeds.dropna().mean()), 1) if launch_speeds.notna().any() else 0,
            }
        )

    lbi_v14_counts = apply_lbi_v14_player_scores(players, lbi_v14_events)
    if players and all(player.get("pa") == player.get("bbe") for player in players):
        raise RuntimeError(
            "Every qualified player has PA equal to BBE. "
            "This indicates a batted-ball-only PA denominator; refusing to generate LBI v1.4."
        )

    for player in players:
        player["lbiVersion"] = LBI_VERSION
        player["lbiComponents"] = {
            "thumpIndex": {
                "value": player.get("thumpIndex"),
                "score": player.get("thumpIndex"),
                "weight": 0.5,
            },
            "improbabilityIndex": {
                "value": player.get("improbabilityIndex"),
                "score": player.get("improbabilityIndex"),
                "weight": 0.5,
            },
        }
        player["sampleBadge"] = sample_badge(player, bbe_minimum)
        del player["barrels"]

    iso_breakdown_counts = summarize_iso_breakdown(players)

    lbi_normalization_players = [
        player for player in players if player.get("_lbiV14NormalizationQualified")
    ]
    pull_pop_values_consistent = [
        player["pullAirJuicePer100Pa"]
        for player in lbi_normalization_players
        if player.get("pullAirJuicePer100Pa") is not None
    ]
    league_pull_pop_consistent = mean(pull_pop_values_consistent) if pull_pop_values_consistent else None
    pull_pop_values_stat_specific = [
        player["pullAirJuicePer100Pa"]
        for player in players
        if player.get("pullAirJuicePer100Pa") is not None
    ]
    league_pull_pop_stat_specific = mean(pull_pop_values_stat_specific) if pull_pop_values_stat_specific else None
    for player in players:
        raw_pull_pop = player.get("pullAirJuicePer100Pa")
        player["pullPop"] = (
            round(float(100 * raw_pull_pop / league_pull_pop_consistent), 1)
            if league_pull_pop_consistent and raw_pull_pop is not None
            else None
        )

    oppo_pop_values_consistent = [
        player["oppoAirJuicePer100Pa"]
        for player in lbi_normalization_players
        if player.get("oppoAirJuicePer100Pa") is not None
    ]
    league_oppo_pop_consistent = mean(oppo_pop_values_consistent) if oppo_pop_values_consistent else None
    oppo_pop_values_stat_specific = [
        player["oppoAirJuicePer100Pa"]
        for player in players
        if player.get("oppoAirJuicePer100Pa") is not None
        and (player.get("oppoAirBbe") or 0) >= OPPO_POP_MIN_OPPO_AIR_BBE
    ]
    league_oppo_pop_stat_specific = mean(oppo_pop_values_stat_specific) if oppo_pop_values_stat_specific else None
    for player in players:
        raw_oppo_pop = player.get("oppoAirJuicePer100Pa")
        player["oppoPop"] = (
            round(float(100 * raw_oppo_pop / league_oppo_pop_consistent), 1)
            if league_oppo_pop_consistent
            and raw_oppo_pop is not None
            and (player.get("oppoAirBbe") or 0) >= OPPO_POP_MIN_OPPO_AIR_BBE
            else None
        )
        tier, display_label = oppo_pop_tier(player)
        tag, note = directional_power_context(player)
        player["oppoPopTier"] = tier
        player["oppoPopDisplayLabel"] = display_label
        player["directionalPowerTag"] = tag
        player["directionalPowerNote"] = note

    contact_values = [
        player["contactPct"]
        for player in players
        if player.get("contactPct") is not None
    ]
    league_contact_pct = mean(contact_values) if contact_values else None
    for player in players:
        contact_pct = player.get("contactPct")
        player["pesky"] = (
            round(float(100 * contact_pct / league_contact_pct), 1)
            if league_contact_pct and contact_pct is not None
            else None
        )
        player.pop("_lbiV14NormalizationQualified", None)

    source_counts = {
        "qualified": len(players),
        "matchedHomeRunTracker": matched_home_run_tracker,
        "missingHomeRunTracker": missing_home_run_tracker,
        "integrityQuarantined": len(integrity_quarantined),
        "matchedBattedBallLeaderboard": matched_batted_ball_leaderboard,
        "missingBattedBallLeaderboard": missing_batted_ball_leaderboard,
        "matchedContactMetrics": matched_contact_metrics,
        "missingContactMetrics": missing_contact_metrics,
        "leagueContactPct": league_contact_pct,
        "leaguePullPopConsistentPer100Pa": league_pull_pop_consistent,
        "leaguePullPopStatSpecificPer100Pa": league_pull_pop_stat_specific,
        "leagueOppoPopConsistentPer100Pa": league_oppo_pop_consistent,
        "leagueOppoPopStatSpecificPer100Pa": league_oppo_pop_stat_specific,
        "leagueOppoAirJuicePer100Pa": league_oppo_pop_consistent,
        "directionalPopBaselineMode": "consistent-lbi-qualified-provisional",
        "oppoPopMinOppoAirBbe": OPPO_POP_MIN_OPPO_AIR_BBE,
        "contactMetricSourceRows": contact_diagnostics.source_rows,
        "contactMetricRegularSeasonRows": contact_diagnostics.regular_season_rows,
        "contactMetricTerminalPaRows": contact_diagnostics.terminal_pa_rows,
        "contactMetricBatterCount": contact_diagnostics.batter_count,
        "cheapieSource": cheapie_source,
        "isoHrMismatches": iso_hr_mismatches,
        **iso_breakdown_counts,
        **lbi_v14_counts,
    }
    print_integrity_quarantine("Longball Index generation", integrity_quarantined)
    return (
        sorted(players, key=lambda row: (-row["longballIndex"], -row["bbe"], row["player"])),
        bbe_minimum,
        team_games,
        source_counts,
    )


def payload_without_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def lbi_metadata(season: int) -> dict[str, Any]:
    return {
        "site": SITE_METADATA,
        "dataset": "Longball Index",
        "season": season,
        "description": "Long-ball contact quality. Stadium-neutral. All fields.",
        "methodologyVersion": f"LBI v{LBI_VERSION}",
        "sourceNotes": (
            "Uses public Statcast pitch data, true two-coordinate batter-relative spray, and "
            "Baseball Savant Home Run Tracker standard park-count geometry for LBI v1.4 event "
            "eligibility. Adjusted xHR remains a context field only and is not used in LBI scoring."
        ),
        "fields": LBI_FIELD_METADATA,
    }


def daily_feature_event_payload(
    event: dict[str, Any],
    season: int,
    generated_at: str,
    source_archive: str | None = None,
) -> dict[str, Any]:
    payload = {
        "generatedAt": generated_at,
        "site": SITE_METADATA,
        "dataset": "Tale of the Tape Daily Features",
        "season": season,
        "gameDate": event.get("gameDate"),
        "description": "Date-stamped Daily Dong, Hot Dog Robbery, and Cheapest Dong selections.",
        "methodologyVersion": "Daily Features v1.0",
        "sourceNotes": "Derived from Statcast and Baseball Savant Home Run Tracker event joins. This file preserves one daily Tale of the Tape row for long-term reference.",
        "fields": {
            "dailyDong": "The day's loudest actual home run.",
            "hotDogRobbery": "The day's strongest HR-capable batted ball that stayed in the yard.",
            "cheapestDong": "The day's flimsiest actual home run that still counted.",
        },
        "dailyDong": event.get("dailyDong"),
        "hotDogRobbery": event.get("hotDogRobbery"),
        "cheapestDong": event.get("cheapestDong"),
    }
    if source_archive:
        payload["sourceArchive"] = source_archive
    return payload


def write_tale_of_the_tape_archive(
    event: dict[str, Any],
    season: int,
    generated_at: str,
    source_archive: Path | None = None,
) -> None:
    game_date = str(event.get("gameDate") or "").strip()
    if not game_date:
        return
    TALE_OF_THE_TAPE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = TALE_OF_THE_TAPE_ARCHIVE_DIR / f"{game_date}.json"
    payload = daily_feature_event_payload(
        event,
        season,
        generated_at,
        source_archive.as_posix() if source_archive else None,
    )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_daily_feature_archive(season: int, daily_features: dict[str, Any] | None, generated_at: str) -> None:
    if not daily_features or not daily_features.get("gameDate"):
        return

    archive_path = Path(DAILY_FEATURE_ARCHIVE_TEMPLATE.format(season=season))
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    existing_events: list[dict[str, Any]] = []

    if archive_path.exists():
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
            existing_events = archive_payload.get("events", [])
            if not isinstance(existing_events, list):
                existing_events = []
        except json.JSONDecodeError:
            existing_events = []

    event = {
        "gameDate": daily_features.get("gameDate"),
        "dailyDong": daily_features.get("dailyDong"),
        "hotDogRobbery": daily_features.get("hotDogRobbery"),
        "cheapestDong": daily_features.get("cheapestDong"),
    }
    events_by_date = {
        str(item.get("gameDate", "")): item
        for item in existing_events
        if isinstance(item, dict) and item.get("gameDate")
    }
    events_by_date[str(event["gameDate"])] = event
    events = [events_by_date[key] for key in sorted(events_by_date.keys(), reverse=True)]

    payload = {
        "generatedAt": generated_at,
        "site": SITE_METADATA,
        "dataset": "Daily Longball Features",
        "season": season,
        "description": "Daily Dong, Hot Dog Robbery, and Cheapest Dong selections by game date.",
        "methodologyVersion": "Daily Features v1.0",
        "sourceNotes": "Derived from the same Statcast and Baseball Savant Home Run Tracker event joins used by the Longball Index data job.",
        "fields": {
            "gameDate": "Latest game date represented by the daily feature row.",
            "dailyDong": "The day's loudest actual home run.",
            "hotDogRobbery": "The day's strongest HR-capable batted ball that stayed in the yard.",
            "cheapestDong": "The day's flimsiest actual home run that still counted.",
        },
        "events": events,
    }
    archive_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_tale_of_the_tape_archive(event, season, generated_at, archive_path)


def write_json(
    path: Path,
    players: list[dict[str, Any]],
    daily_features: dict[str, Any] | None,
    season: int,
    minimum_hr: int,
    minimum_pa: int | None,
    bbe_minimum: int,
    team_games: int,
    raw_cache: Path,
    source_counts: dict[str, Any],
    allow_empty: bool,
) -> None:
    if not players and not allow_empty:
        raise RuntimeError(
            f"Refusing to overwrite {path} with an empty players array. "
            "Use --allow-empty only when an empty leaderboard is expected."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **lbi_metadata(season),
        "source": {
            "rawCache": str(raw_cache),
            "fetcher": "canonical pitch cache + Baseball Savant Home Run Tracker",
            "homeRunTrackerMode": HOME_RUN_TRACKER_CAT,
            "lbiV14ParkCountMode": STANDARD_HOME_RUN_TRACKER_CAT,
            "longballIndexVersion": LBI_VERSION,
            "methodology": (
                "LBI v1.4 = 50% Thump + 50% Artistry. "
                "Thump is accumulated per PA from exit velocity and park-neutral estimated distance. "
                "Artistry is averaged per qualifying long-ball event from true batter-relative "
                "spray x launch-angle route difficulty, with shrinkage toward league average."
            ),
            "tagline": "Long-ball contact quality. Stadium-neutral. All fields.",
            "lbiV14UsesXhrInScoring": False,
            "lbiV14UsesAdjustedXhrInScoring": False,
            "lbiV14UsesHardHitInScoring": False,
            "lbiV14UsesTrueSpray": True,
            "lbiV14EligibleEvents": source_counts.get("lbiV14EligibleEvents", 0),
            "lbiV14ActualHrEvents": source_counts.get("lbiV14ActualHrEvents", 0),
            "lbiV14RobbedEvents": source_counts.get("lbiV14RobbedEvents", 0),
            "lbiV14KnownSprayRate": source_counts.get("lbiV14KnownSprayRate", 0),
            "lbiV14LeagueThumpRate": source_counts.get("lbiV14LeagueThumpRate"),
            "lbiV14LeagueImprobability": source_counts.get("lbiV14LeagueImprobability"),
            "lbiV14ImprobabilityShrinkK": source_counts.get("lbiV14ImprobabilityShrinkK", LBI_V14_IMPROB_SHRINK_K),
            "lbiV14MinEventsForArchetype": source_counts.get(
                "lbiV14MinEventsForArchetype",
                LBI_V14_MIN_EVENTS_FOR_ARCHETYPE,
            ),
            "homeRunTrackerMatchedPlayers": source_counts.get("matchedHomeRunTracker", 0),
            "homeRunTrackerMissingPlayers": source_counts.get("missingHomeRunTracker", 0),
            "battedBallLeaderboardMatchedPlayers": source_counts.get("matchedBattedBallLeaderboard", 0),
            "battedBallLeaderboardMissingPlayers": source_counts.get("missingBattedBallLeaderboard", 0),
            "pullAirSource": "Baseball Savant batted-ball leaderboard pull_air_rate",
            "oppoPopSource": (
                "Full pitch-level Statcast opposite-field air power, mirrored from Pull Pop's EV/LA kernel. "
                "Context only, not part of LBI."
            ),
            "directionalPopBaselineMode": source_counts.get("directionalPopBaselineMode"),
            "pullPopLeagueConsistentPer100Pa": source_counts.get("leaguePullPopConsistentPer100Pa"),
            "pullPopLeagueStatSpecificPer100Pa": source_counts.get("leaguePullPopStatSpecificPer100Pa"),
            "oppoPopMinOppoAirBbe": source_counts.get("oppoPopMinOppoAirBbe"),
            "oppoPopLeagueOppoAirJuicePer100Pa": source_counts.get("leagueOppoAirJuicePer100Pa"),
            "oppoPopLeagueConsistentPer100Pa": source_counts.get("leagueOppoPopConsistentPer100Pa"),
            "oppoPopLeagueStatSpecificPer100Pa": source_counts.get("leagueOppoPopStatSpecificPer100Pa"),
            "peskySource": "Full pitch-level Statcast contact% plus-scaled among LBI-qualified hitters.",
            "peskyLeagueContactPct": source_counts.get("leagueContactPct"),
            "contactMetricMatchedPlayers": source_counts.get("matchedContactMetrics", 0),
            "contactMetricMissingPlayers": source_counts.get("missingContactMetrics", 0),
            "contactMetricSourceRows": source_counts.get("contactMetricSourceRows", 0),
            "contactMetricRegularSeasonRows": source_counts.get("contactMetricRegularSeasonRows", 0),
            "contactMetricTerminalPaRows": source_counts.get("contactMetricTerminalPaRows", 0),
            "contactMetricBatterCount": source_counts.get("contactMetricBatterCount", 0),
            "isoBreakdownSource": "Terminal plate-appearance batting line inferred from the full pitch-level Statcast cache.",
            "isoBreakdownMedianIso": source_counts.get("isoMedian"),
            "isoBreakdownHrMismatchedPlayers": source_counts.get("isoHrMismatches", 0),
            "isoBreakdownQualifiedPlayers": source_counts.get("isoBreakdownQualifiedPlayers"),
            "cheapieSource": source_counts.get("cheapieSource", "avg-distance-proxy"),
            "homeRunTrackerDetailRows": source_counts.get("homeRunTrackerDetailRows", 0),
            "homeRunTrackerDetailJoinedRows": source_counts.get("homeRunTrackerDetailJoinedRows", 0),
            "homeRunTrackerDetailJoinRate": source_counts.get("homeRunTrackerDetailJoinRate", 0),
            "homeRunTrackerActualHrRows": source_counts.get("homeRunTrackerActualHrRows", 0),
            "joinedActualHrRows": source_counts.get("joinedActualHrRows", 0),
            "actualHrMatchRate": source_counts.get("actualHrMatchRate", 0),
        },
        "qualifiedBy": {
            "minimumHomeRuns": None,
            "frontendMinimumHomeRunsDefault": minimum_hr,
            "minimumPlateAppearances": minimum_pa,
            "minimumBbe": bbe_minimum,
            "estimatedTeamGames": team_games,
        },
        "players": players,
        "dailyDong": daily_features.get("dailyDong") if daily_features else None,
        "dailyFeatures": daily_features,
    }

    generated_at = datetime.now(timezone.utc).isoformat()
    if path.exists():
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))
            if payload_without_timestamp(existing_payload) == payload:
                generated_at = existing_payload.get("generatedAt", generated_at)
        except json.JSONDecodeError:
            pass

    payload = {"generatedAt": generated_at, **payload}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_daily_feature_archive(season, daily_features, generated_at)


def refresh_events(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[int, dict[str, Any]], ContactMetricDiagnostics]:
    if args.input_csv:
        print(f"Reading local Statcast pitch CSV from {args.input_csv}")
        pitches = pd.read_csv(args.input_csv)
        if args.contact_csv:
            contact_frames = []
            for path in args.contact_csv:
                print(f"Reading full pitch contact/PA CSV from {path}")
                contact_frames.append(pd.read_csv(path))
            contact_pitches = pd.concat(contact_frames, ignore_index=True) if contact_frames else pitches
        else:
            contact_pitches = pitches
    else:
        end = args.end_date or iso_today()
        start = args.start_date
        existing = read_pitch_cache(args.raw_cache)
        first_run = existing.empty

        if start is None:
            start = season_start(args.season) if first_run else end - timedelta(days=args.lookback_days)

        print(f"Refreshing canonical pitch cache from {start} through {end}")
        pitch_args = argparse.Namespace(
            season=args.season,
            output=args.raw_cache,
            lookback_days=args.lookback_days,
            start_date=start,
            end_date=end,
            allow_empty=args.allow_empty,
            skip_heart_zones=args.skip_heart_zones,
        )
        pitches = refresh_pitch_cache(pitch_args)
        contact_pitches = pitches

    contact_metrics, contact_diagnostics = build_contact_metrics(contact_pitches, args.season)
    if contact_diagnostics.source_rows != contact_diagnostics.regular_season_rows:
        print(
            f"Scoped contact metrics to regular-season dates for {args.season}: "
            f"{contact_diagnostics.source_rows:,} -> {contact_diagnostics.regular_season_rows:,}"
        )
    print(
        "Derived contact metrics from full pitch cache: "
        f"{contact_diagnostics.batter_count:,} batters, "
        f"{contact_diagnostics.terminal_pa_rows:,} true terminal PA"
    )

    events = merge_events(pd.DataFrame(columns=RAW_COLUMNS), normalize_event_frame(pitches))
    before_scope = len(events)
    events = scope_to_regular_season(events, args.season)
    if before_scope != len(events):
        print(
            f"Scoped batted-ball events to regular-season dates for {args.season}: "
            f"{before_scope:,} -> {len(events):,}"
        )
    events = ensure_true_spray_coordinates(events, args.season, args.raw_cache)

    if events.empty and not args.allow_empty:
        raise RuntimeError(
            "The pitch cache produced 0 usable batted-ball events. "
            "Refusing to publish an empty leaderboard.\n"
            f"Pitch cache path: {args.raw_cache}\n"
            "If this date range truly has no usable batted balls, rerun with --allow-empty."
        )

    print(f"Derived {len(events)} deduped batted-ball events from {args.raw_cache}")
    return events, contact_metrics, contact_diagnostics


def read_existing_player_lbis(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    players = payload.get("players", []) if isinstance(payload, dict) else []
    old_lbis = {}
    for player in players:
        name = normalize_name(str(player.get("player", "")))
        lbi = to_float(player.get("longballIndex"))
        if name and lbi is not None:
            old_lbis[name] = lbi
    return old_lbis


def print_player_component_breakdown(player: dict[str, Any]) -> None:
    print(f"\n{player['player']}")
    print(f"  BBE: {player['bbe']}")
    print(f"  HR: {player['hr']}")
    print(f"  xHR: {player.get('xhr')}")
    print(f"  xHR/BBE: {player.get('xhrPerBbe')}")
    print(f"  Barrel%: {player.get('barrelRate')}")
    print(f"  HR-Window Thunder Rate: {player.get('hrWindowThunderRate')}")
    print(f"  Hard Hit%: {player.get('hardHitRate')}")
    print(f"  ThumpIndex: {player.get('thumpIndex')}")
    print(f"  ArtistryIndex: {player.get('improbabilityIndex')}")
    print(f"  Long-ball events: {player.get('longBallEventCount')}")
    print(f"  Archetype: {player.get('lbiArchetype')}")
    print(f"  Sweet Spot% reference only, not in LBI v1.4: {player.get('sweetSpotRate')}")
    print(f"  Avg Distance on Barrels reference only: {player.get('avgDistanceOnBarrels')}")
    print("  Components:")
    for key, component in player.get("lbiComponents", {}).items():
        print(
            f"    {key}: value={component.get('value')}, "
            f"percentile={component.get('percentile')}, "
            f"score={component.get('score')}, "
            f"effective_weight={component.get('weight')}"
        )
    print(f"  Final LBI: {player.get('longballIndex')}")


def print_run_diagnostics(
    players: list[dict[str, Any]],
    source_counts: dict[str, Any],
    old_lbis: dict[str, float],
) -> None:
    print(f"\n=== LBI v{LBI_VERSION} run diagnostics ===")
    print(f"Qualified players: {source_counts.get('qualified', len(players))}")
    print(f"Matched to Home Run Tracker xHR: {source_counts.get('matchedHomeRunTracker', 0)}")
    print(f"Missing Home Run Tracker xHR: {source_counts.get('missingHomeRunTracker', 0)}")
    print(f"Matched to batted-ball Pull AIR%: {source_counts.get('matchedBattedBallLeaderboard', 0)}")
    print(f"Missing batted-ball Pull AIR%: {source_counts.get('missingBattedBallLeaderboard', 0)}")
    print(f"Matched to full-pitch contact metrics: {source_counts.get('matchedContactMetrics', 0)}")
    print(f"Missing full-pitch contact metrics: {source_counts.get('missingContactMetrics', 0)}")
    league_contact = source_counts.get("leagueContactPct")
    if league_contact is not None:
        print(f"Pesky league contact% baseline: {league_contact:.1%}")
    print(f"CHEAPIES source: {source_counts.get('cheapieSource', 'unknown')}")
    print(f"CHEAPIES detail join rate: {source_counts.get('homeRunTrackerDetailJoinRate', 0):.1%}")
    print(f"CHEAPIES actual HR match rate: {source_counts.get('actualHrMatchRate', 0):.1%}")
    print(f"LBI v1.4 eligible events: {source_counts.get('lbiV14EligibleEvents', 0):,}")
    print(f"LBI v1.4 known true-spray rate: {source_counts.get('lbiV14KnownSprayRate', 0):.1%}")

    hayes_key = normalize_name("Ke'Bryan Hayes")
    hayes = next((player for player in players if normalize_name(player["player"]) == hayes_key), None)
    if hayes:
        old_lbi = old_lbis.get(hayes_key)
        print(
            "Hayes old/new LBI: "
            f"{old_lbi if old_lbi is not None else 'not available'} -> {hayes['longballIndex']}"
        )

    print("\nDiagnostic player component breakdowns:")
    by_name = {normalize_name(player["player"]): player for player in players}
    for name in DIAGNOSTIC_PLAYERS:
        player = by_name.get(normalize_name(name))
        if player:
            print_player_component_breakdown(player)
        else:
            print(f"\n{name}: not qualified or not present")

    print("\nTop 25 LBI players:")
    for index, player in enumerate(players[:25], start=1):
        print(
            f"{index:2}. {player['player']} ({player['team']}) "
            f"LBI {player['longballIndex']} | BBE {player['bbe']} | "
            f"HR {player['hr']} | xHR {player.get('xhr')}"
        )

    print("\nBottom 25 LBI players:")
    for index, player in enumerate(players[-25:], start=1):
        print(
            f"{index:2}. {player['player']} ({player['team']}) "
            f"LBI {player['longballIndex']} | BBE {player['bbe']} | "
            f"HR {player['hr']} | xHR {player.get('xhr')}"
        )

    scores = [float(player["longballIndex"]) for player in players if player.get("longballIndex") is not None]
    if scores:
        print(
            "\nDistribution: "
            f"median={median(scores):.1f}, mean={mean(scores):.1f}, "
            f"max={max(scores):.1f}, min={min(scores):.1f}"
        )

    true_cheapie_players = [
        player for player in players
        if player.get("cheapieSource") == "actual-home-run-classification"
        and player.get("hr", 0) >= 5
        and player.get("actualDoubterHr") is not None
    ]
    if true_cheapie_players:
        print("\nTop 20 true CHEAPIES (HR >= 5):")
        top_cheapies = sorted(
            true_cheapie_players,
            key=lambda row: (-(row.get("cheapieRate") or 0), -(row.get("actualDoubterHr") or 0), -row.get("hr", 0), row["player"]),
        )[:20]
        for index, player in enumerate(top_cheapies, start=1):
            print(
                f"{index:2}. {player['player']} ({player['team']}) "
                f"{(player.get('cheapieRate') or 0):.0%} | "
                f"{player.get('actualDoubterHr')} Cheapies / {player.get('hr')} HR"
            )

    sanoja = by_name.get(normalize_name("Javier Sanoja"))
    if sanoja:
        print(
            "\nJavier Sanoja CHEAPIES check: "
            f"HR={sanoja.get('hr')}, actualDoubterHr={sanoja.get('actualDoubterHr')}, "
            f"eligible={sanoja.get('hr', 0) >= 5}"
        )

    bobby_witt = by_name.get(normalize_name("Bobby Witt"))
    if bobby_witt:
        print(
            "Bobby Witt CHEAPIES check: "
            f"HR={bobby_witt.get('hr')}, actualDoubterHr={bobby_witt.get('actualDoubterHr')}, "
            f"cheapieRate={bobby_witt.get('cheapieRate')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate The Long Ball leaderboard JSON.")
    parser.add_argument("--season", type=int, default=iso_today().year)
    parser.add_argument("--input-csv", type=Path, help="Merge a local Statcast CSV instead of fetching data.")
    parser.add_argument(
        "--contact-csv",
        nargs="+",
        type=Path,
        help="Full pitch-level Statcast CSV(s) for true PA/contact metrics when --input-csv is batted-ball-only.",
    )
    parser.add_argument("--raw-cache", type=Path, default=RAW_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr", type=int, default=1)
    parser.add_argument("--min-pa", type=int, help="Optional plate appearance filter for offline analysis.")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--start-date", type=parse_date, help="Override fetch start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", type=parse_date, help="Override fetch end date, YYYY-MM-DD.")
    parser.add_argument("--skip-heart-zones", action="store_true", help="Skip Heart-zone tagging when building LBI-only caches.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow writing an empty leaderboard JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    old_lbis = read_existing_player_lbis(args.output)
    events, contact_metrics, contact_diagnostics = refresh_events(args)
    home_run_tracker = fetch_home_run_tracker(args.season)
    standard_home_run_tracker = fetch_home_run_tracker(args.season, cat=STANDARD_HOME_RUN_TRACKER_CAT)
    batted_ball_leaderboard = fetch_batted_ball_leaderboard(args.season)
    actual_cheapies, cheapie_counts, daily_features = calculate_actual_cheapies(events, home_run_tracker, args.season)
    lbi_v14_events, lbi_v14_counts = build_lbi_v14_scored_events(events, standard_home_run_tracker, args.season)
    players, bbe_minimum, team_games, source_counts = build_leaderboard(
        events,
        home_run_tracker=home_run_tracker,
        lbi_v14_events=lbi_v14_events,
        batted_ball_leaderboard=batted_ball_leaderboard,
        contact_metrics=contact_metrics,
        contact_diagnostics=contact_diagnostics,
        actual_cheapies=actual_cheapies,
        cheapie_source=str(cheapie_counts.get("cheapieSource", "avg-distance-proxy")),
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
    )
    source_counts.update(cheapie_counts)
    source_counts.update(lbi_v14_counts)
    print_run_diagnostics(players, source_counts, old_lbis)
    write_json(
        args.output,
        players,
        daily_features=daily_features,
        season=args.season,
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
        bbe_minimum=bbe_minimum,
        team_games=team_games,
        raw_cache=args.raw_cache,
        source_counts=source_counts,
        allow_empty=args.allow_empty,
    )
    print(f"Wrote {len(players)} players to {args.output}")


if __name__ == "__main__":
    main()
