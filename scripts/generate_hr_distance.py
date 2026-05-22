#!/usr/bin/env python3
"""Generate frontend-ready Longball Index JSON.

This script is the only Statcast access layer. The frontend reads static JSON
from public/data and never calls Baseball Savant, pybaseball, or any live API.

Default behavior:
- Keep raw pitch-level events in data/raw/statcast-pitches.csv.
- On the first run, backfill the current season to date.
- On later runs, fetch the last few days, merge, dedupe, and rebuild JSON.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
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
from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache, refresh_pitch_cache
from pybaseball import playerid_reverse_lookup


RAW_CACHE_PATH = PITCH_CACHE_PATH
OUTPUT_PATH = Path("public/data/hr-distance-latest.json")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
FETCH_CHUNK_DAYS = 7
LBI_VERSION = "1.2"
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
HOME_RUN_TRACKER_URL = "https://baseballsavant.mlb.com/leaderboard/home-runs"
HOME_RUN_TRACKER_CAT = "adj_xhr"
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
    "xhrPerBbe": 0.60,
    "barrelRate": 0.20,
    "avgDistanceOnBarrels": 0.125,
    "hardHitRate": 0.075,
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
        "data/raw/statcast-pitches.csv, then derive BBE rows from that cache."
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
            "This source supplies Adjusted xHR/BBE for LBI v1.2. "
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


def estimated_team_games(events: pd.DataFrame) -> int:
    if events.empty:
        return 0

    team_games = events.dropna(subset=["bat_team", "game_pk"]).groupby("bat_team")["game_pk"].nunique()
    if team_games.empty:
        return 0

    return int(team_games.max())


def lbi_score_from_percentile(percentile: float) -> float:
    clipped = min(max(percentile, 0.01), 0.99)
    return 100 + (NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped))


def component_percentiles(players: list[dict[str, Any]], key: str) -> dict[int, float]:
    values = pd.Series([player.get(key) for player in players], dtype="float64")
    percentiles = values.rank(method="average", pct=True)
    return {
        id(player): float(percentile)
        for player, percentile in zip(players, percentiles)
        if pd.notna(percentile) and player.get(key) is not None
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
    barrels = int(player["barrels"])

    if barrels >= 10:
        component_weights = LBI_COMPONENT_WEIGHTS
    elif barrels >= 5:
        component_weights = {
            "xhrPerBbe": 0.675,
            "barrelRate": 0.175,
            "avgDistanceOnBarrels": 0.075,
            "hardHitRate": 0.075,
        }
    else:
        component_weights = {
            "xhrPerBbe": 0.75,
            "barrelRate": 0.175,
            "hardHitRate": 0.075,
        }

    for key in LBI_COMPONENT_WEIGHTS:
        base_weight = component_weights.get(key, 0)
        if not base_weight:
            components[key] = {
                "value": player.get(key),
                "percentile": None,
                "score": None,
                "weight": 0,
            }
            continue

        percentile = percentile_maps[key].get(id(player))
        if percentile is None:
            components[key] = {
                "value": player.get(key),
                "percentile": None,
                "score": None,
                "weight": 0,
            }
            continue

        score = lbi_score_from_percentile(percentile)
        components[key] = {
            "value": player.get(key),
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
    minimum_hr: int,
    minimum_pa: int | None,
) -> tuple[list[dict[str, Any]], int, int, dict[str, int]]:
    if events.empty:
        return [], 0, 0, {"qualified": 0, "matchedHomeRunTracker": 0, "missingHomeRunTracker": 0}

    team_games = estimated_team_games(events)
    bbe_minimum = max(50, round(team_games * 1.5))
    grouped = events.groupby(["batter", "player_name"], dropna=False)
    tracker_by_batter = {}
    if not home_run_tracker.empty:
        tracker_by_batter = {
            int(row["player_id"]): row
            for row in home_run_tracker.to_dict("records")
            if pd.notna(row.get("player_id"))
        }

    players = []
    matched_home_run_tracker = 0
    missing_home_run_tracker = 0

    for (batter, player), group in grouped:
        bbe = int(len(group))
        if bbe < bbe_minimum:
            continue

        plate_appearances = group[["game_pk", "at_bat_number"]].drop_duplicates()
        if minimum_pa is not None and len(plate_appearances) < minimum_pa:
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
        barrel_distances = pd.to_numeric(barrels["hit_distance_sc"], errors="coerce").dropna()
        barrel_launch_angles = pd.to_numeric(barrels["launch_angle"], errors="coerce").dropna()
        hr_distances = pd.to_numeric(home_runs["hit_distance_sc"], errors="coerce").dropna()
        batter_id = int(batter)
        tracker_row = tracker_by_batter.get(batter_id)

        if tracker_row:
            matched_home_run_tracker += 1
        else:
            missing_home_run_tracker += 1

        xhr = to_float(tracker_row.get("xhr")) if tracker_row else None
        xhr_diff = to_float(tracker_row.get("xhr_diff")) if tracker_row else None
        no_doubters = to_int(tracker_row.get("no_doubters")) if tracker_row else None
        doubters = to_int(tracker_row.get("doubters")) if tracker_row else None
        mostly_gone = to_int(tracker_row.get("mostly_gone")) if tracker_row else None
        no_doubter_rate = to_float(tracker_row.get("no_doubter_per")) if tracker_row else None
        if no_doubter_rate is not None:
            no_doubter_rate = no_doubter_rate / 100

        players.append(
            {
                "batter": batter_id,
                "player": str(player),
                "team": team.iloc[-1] if not team.empty else "",
                "bbe": bbe,
                "hr": hr_count,
                "xhr": round(xhr, 1) if xhr is not None else None,
                "xhrPerBbe": round(float(xhr / bbe), 4) if xhr is not None and bbe else None,
                "xhrDiff": round(xhr_diff, 1) if xhr_diff is not None else None,
                "noDoubters": no_doubters,
                "doubters": doubters,
                "mostlyGone": mostly_gone,
                "noDoubterRate": round(no_doubter_rate, 3) if no_doubter_rate is not None else None,
                "barrels": int(len(barrels)),
                "barrelRate": round(float(len(barrels) / bbe), 3),
                "hardHitRate": round(float(hard_hits.sum() / bbe), 3),
                "sweetSpotRate": round(float(sweet_spots.sum() / bbe), 3),
                "avgDistanceOnBarrels": round(float(barrel_distances.mean()), 1)
                if len(barrel_distances) and len(barrels) >= 5
                else None,
                "avgLaunchAngleOnBarrels": round(float(barrel_launch_angles.mean()), 1)
                if len(barrel_launch_angles) and len(barrels) >= 3
                else None,
                "avgDistance": round(float(hr_distances.mean()), 1) if len(hr_distances) else 0,
                "longestHr": round(float(hr_distances.max())) if len(hr_distances) else 0,
                "avgExitVelocity": round(float(launch_speeds.dropna().mean()), 1) if launch_speeds.notna().any() else 0,
            }
        )

    percentile_maps = {
        key: component_percentiles(players, key)
        for key in LBI_COMPONENT_WEIGHTS
    }

    for player in players:
        longball_index, components = lbi_components_for_player(player, percentile_maps)
        player["longballIndex"] = longball_index
        player["lbiVersion"] = LBI_VERSION
        player["lbiComponents"] = components
        player["sampleBadge"] = sample_badge(player, bbe_minimum)
        del player["barrels"]

    source_counts = {
        "qualified": len(players),
        "matchedHomeRunTracker": matched_home_run_tracker,
        "missingHomeRunTracker": missing_home_run_tracker,
    }
    return (
        sorted(players, key=lambda row: (-row["longballIndex"], -row["bbe"], row["player"])),
        bbe_minimum,
        team_games,
        source_counts,
    )


def payload_without_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def write_json(
    path: Path,
    players: list[dict[str, Any]],
    minimum_hr: int,
    minimum_pa: int | None,
    bbe_minimum: int,
    team_games: int,
    raw_cache: Path,
    source_counts: dict[str, int],
    allow_empty: bool,
) -> None:
    if not players and not allow_empty:
        raise RuntimeError(
            f"Refusing to overwrite {path} with an empty players array. "
            "Use --allow-empty only when an empty leaderboard is expected."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": {
            "rawCache": str(raw_cache),
            "fetcher": "canonical pitch cache + Baseball Savant Home Run Tracker",
            "homeRunTrackerMode": HOME_RUN_TRACKER_CAT,
            "longballIndexVersion": LBI_VERSION,
            "methodology": (
                "Adjusted xHR/BBE anchored formula: 60%, Barrel% 20%, "
                "Avg Distance on Barrels 12.5%, Hard Hit% 7.5%; "
                "distance confidence weights apply below 10 barrels"
            ),
            "homeRunTrackerMatchedPlayers": source_counts.get("matchedHomeRunTracker", 0),
            "homeRunTrackerMissingPlayers": source_counts.get("missingHomeRunTracker", 0),
        },
        "qualifiedBy": {
            "minimumHomeRuns": None,
            "frontendMinimumHomeRunsDefault": minimum_hr,
            "minimumPlateAppearances": minimum_pa,
            "minimumBbe": bbe_minimum,
            "estimatedTeamGames": team_games,
        },
        "players": players,
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


def refresh_events(args: argparse.Namespace) -> pd.DataFrame:
    if args.input_csv:
        print(f"Reading local Statcast pitch CSV from {args.input_csv}")
        pitches = pd.read_csv(args.input_csv)
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
        )
        pitches = refresh_pitch_cache(pitch_args)

    events = merge_events(pd.DataFrame(columns=RAW_COLUMNS), normalize_event_frame(pitches))

    if events.empty and not args.allow_empty:
        raise RuntimeError(
            "The pitch cache produced 0 usable batted-ball events. "
            "Refusing to publish an empty leaderboard.\n"
            f"Pitch cache path: {args.raw_cache}\n"
            "If this date range truly has no usable batted balls, rerun with --allow-empty."
        )

    print(f"Derived {len(events)} deduped batted-ball events from {args.raw_cache}")
    return events


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
    print(f"  Hard Hit%: {player.get('hardHitRate')}")
    print(f"  Sweet Spot% reference only, not in LBI v1.2: {player.get('sweetSpotRate')}")
    print(f"  Avg Distance on Barrels: {player.get('avgDistanceOnBarrels')}")
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
    source_counts: dict[str, int],
    old_lbis: dict[str, float],
) -> None:
    print("\n=== LBI v1.2 run diagnostics ===")
    print(f"Qualified players: {source_counts.get('qualified', len(players))}")
    print(f"Matched to Home Run Tracker xHR: {source_counts.get('matchedHomeRunTracker', 0)}")
    print(f"Missing Home Run Tracker xHR: {source_counts.get('missingHomeRunTracker', 0)}")

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

    print("\nTop 20 LBI players:")
    for index, player in enumerate(players[:20], start=1):
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate The Long Ball leaderboard JSON.")
    parser.add_argument("--season", type=int, default=iso_today().year)
    parser.add_argument("--input-csv", type=Path, help="Merge a local Statcast CSV instead of fetching data.")
    parser.add_argument("--raw-cache", type=Path, default=RAW_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr", type=int, default=1)
    parser.add_argument("--min-pa", type=int, help="Optional plate appearance filter for offline analysis.")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--start-date", type=parse_date, help="Override fetch start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", type=parse_date, help="Override fetch end date, YYYY-MM-DD.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow writing an empty leaderboard JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    old_lbis = read_existing_player_lbis(args.output)
    events = refresh_events(args)
    home_run_tracker = fetch_home_run_tracker(args.season)
    players, bbe_minimum, team_games, source_counts = build_leaderboard(
        events,
        home_run_tracker=home_run_tracker,
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
    )
    print_run_diagnostics(players, source_counts, old_lbis)
    write_json(
        args.output,
        players,
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
