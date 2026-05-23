#!/usr/bin/env python3
"""Refresh the canonical pitch-level Statcast cache.

This cache is the backend foundation for both the Longball Index and The Hot
Dog Stand. The frontend still reads precomputed static JSON only.
"""

from __future__ import annotations

import argparse
import io
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))

import pandas as pd
from pybaseball import statcast


PITCH_CACHE_PATH = Path("data/raw/statcast-pitches.csv")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
FETCH_CHUNK_DAYS = 7
STATCAST_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
SAVANT_HEART_NEW_ZONES = "1|2|3|4|5|6|7|8|9|"
PITCH_COLUMNS = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "player_name",
    "batter",
    "events",
    "type",
    "description",
    "des",
    "pitch_type",
    "release_speed",
    "zone",
    "plate_x",
    "plate_z",
    "sz_top",
    "sz_bot",
    "hit_distance_sc",
    "launch_speed",
    "launch_angle",
    "launch_speed_angle",
    "bb_type",
    "hc_x",
    "home_team",
    "away_team",
    "inning_topbot",
    "p_throws",
    "stand",
    "balls",
    "strikes",
    "is_heart_zone",
]
KEY_COLUMNS = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"]


def parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected date format YYYY-MM-DD.") from error


def iso_today() -> date:
    return datetime.now(timezone.utc).date()


def season_start(season: int) -> date:
    return date(season, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY)


def empty_pitch_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=PITCH_COLUMNS)


def read_pitch_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return empty_pitch_frame()
    return normalize_pitch_frame(pd.read_csv(path))


def coerce_pitch_types(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    integer_columns = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "balls", "strikes"]
    numeric_columns = [
        "release_speed",
        "zone",
        "plate_x",
        "plate_z",
        "sz_top",
        "sz_bot",
        "hit_distance_sc",
        "launch_speed",
        "launch_angle",
        "launch_speed_angle",
        "hc_x",
    ]

    for column in integer_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in [
        "events",
        "type",
        "description",
        "des",
        "pitch_type",
        "player_name",
        "bb_type",
        "home_team",
        "away_team",
        "inning_topbot",
        "p_throws",
        "stand",
    ]:
        frame[column] = frame[column].astype("string")

    if "is_heart_zone" in frame.columns:
        frame["is_heart_zone"] = frame["is_heart_zone"].fillna(False).astype(bool)
    else:
        frame["is_heart_zone"] = False
    return frame


def normalize_pitch_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    for column in PITCH_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame = coerce_pitch_types(frame)
    has_key = frame[KEY_COLUMNS].notna().all(axis=1)
    frame = frame[has_key].copy()
    return frame[PITCH_COLUMNS]


def pitch_keys(frame: pd.DataFrame) -> pd.Series:
    normalized = frame.copy()
    for column in KEY_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").astype("Int64")

    return (
        normalized["game_pk"].astype("string")
        + ":"
        + normalized["at_bat_number"].astype("string")
        + ":"
        + normalized["pitch_number"].astype("string")
        + ":"
        + normalized["pitcher"].astype("string")
        + ":"
        + normalized["batter"].astype("string")
    )


def savant_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Referer": "https://baseballsavant.mlb.com/statcast_search",
    }


def fetch_savant_statcast_csv(start: date, end: date, hf_new_zones: str) -> pd.DataFrame:
    params = {
        "all": "true",
        "hfPT": "",
        "hfAB": "",
        "hfBBT": "",
        "hfPR": "",
        "hfZ": "",
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": hf_new_zones,
        "hfGT": "R|PO|S|",
        "hfSea": "",
        "hfSit": "",
        "player_type": "pitcher",
        "hfOuts": "",
        "opponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start.isoformat(),
        "game_date_lt": end.isoformat(),
        "team": "",
        "position": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "h_launch_speed",
        "sort_order": "desc",
        "min_abs": "0",
        "type": "details",
    }
    url = f"{STATCAST_CSV_URL}?{urlencode(params)}"
    request = Request(url, headers=savant_headers())
    with urlopen(request, timeout=90) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(body))


def fetch_statcast_pitches(start_date: date, end_date: date) -> pd.DataFrame:
    chunks = []
    current = start_date

    while current <= end_date:
        chunk_end = min(current + timedelta(days=FETCH_CHUNK_DAYS - 1), end_date)
        print(f"Fetching pitch-level Statcast with pybaseball.statcast({current}, {chunk_end})")
        chunk = statcast(start_dt=current.isoformat(), end_dt=chunk_end.isoformat())
        if chunk is not None and not chunk.empty:
            chunks.append(chunk)
        current = chunk_end + timedelta(days=1)

    if not chunks:
        return empty_pitch_frame()

    return normalize_pitch_frame(pd.concat(chunks, ignore_index=True))


def add_official_heart_flags(pitches: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    pitches = normalize_pitch_frame(pitches)
    if pitches.empty:
        return pitches

    heart_chunks = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=FETCH_CHUNK_DAYS - 1), end_date)
        print(f"Fetching official Savant Heart-zone filter from {current} through {chunk_end}")
        heart_chunk = fetch_savant_statcast_csv(current, chunk_end, SAVANT_HEART_NEW_ZONES)
        if heart_chunk is not None and not heart_chunk.empty:
            heart_chunks.append(heart_chunk)
        current = chunk_end + timedelta(days=1)

    if not heart_chunks:
        print("Warning: official Heart-zone fetch returned no rows; keeping is_heart_zone=False for incoming pitches.")
        pitches["is_heart_zone"] = False
        return pitches

    heart = pd.concat(heart_chunks, ignore_index=True)
    heart_keys = set(pitch_keys(heart).dropna().astype(str).tolist())
    pitches["is_heart_zone"] = pitch_keys(pitches).isin(heart_keys)
    print(f"Tagged {int(pitches['is_heart_zone'].sum()):,} of {len(pitches):,} incoming pitches as official Heart zone")
    return pitches


def merge_pitch_cache(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    pitches = pd.concat([existing, incoming], ignore_index=True)
    pitches = normalize_pitch_frame(pitches)
    if pitches.empty:
        return pitches

    pitches["dedupe_key"] = pitch_keys(pitches)
    pitches = pitches.drop_duplicates(subset=["dedupe_key"], keep="last")
    pitches = pitches.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])
    return pitches[PITCH_COLUMNS]


def write_pitch_cache(path: Path, pitches: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_pitch_frame(pitches).to_csv(path, index=False, columns=PITCH_COLUMNS)


def refresh_pitch_cache(args: argparse.Namespace) -> pd.DataFrame:
    existing = read_pitch_cache(args.output)
    first_run = existing.empty
    end_date = args.end_date or iso_today()
    start_date = args.start_date

    if start_date is None:
        start_date = season_start(args.season) if first_run else end_date - timedelta(days=args.lookback_days)

    incoming = fetch_statcast_pitches(start_date, end_date)
    if getattr(args, "skip_heart_zones", False):
        print("Skipping official Heart-zone tagging for this cache refresh.")
        incoming["is_heart_zone"] = False
    else:
        incoming = add_official_heart_flags(incoming, start_date, end_date)

    if first_run and incoming.empty and not args.allow_empty:
        raise RuntimeError(
            "No existing pitch cache was found and the data fetch returned 0 pitches.\n"
            f"Date range: {start_date} through {end_date}\n"
            f"Pitch cache path: {args.output}\n"
            "If this date range truly has no pitches, rerun with --allow-empty."
        )

    merged = merge_pitch_cache(existing, incoming)
    write_pitch_cache(args.output, merged)
    print(f"Cached {len(merged):,} deduped pitches at {args.output}")
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the canonical pitch-level Statcast cache.")
    parser.add_argument("--season", type=int, default=iso_today().year)
    parser.add_argument("--output", type=Path, default=PITCH_CACHE_PATH)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--start-date", type=parse_date, help="Override fetch start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", type=parse_date, help="Override fetch end date, YYYY-MM-DD.")
    parser.add_argument("--skip-heart-zones", action="store_true", help="Skip Heart-zone tagging when building LBI-only caches.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow writing an empty pitch cache.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refresh_pitch_cache(args)


if __name__ == "__main__":
    main()
