#!/usr/bin/env python3
"""Generate the static HR distance leaderboard JSON.

This script is the only data-fetch layer. The browser reads the generated JSON
file from public/data/hr-distance-latest.json and never calls Baseball Savant.

Default behavior:
- Keep raw home-run events in data/raw/statcast-hr-events.csv.
- On the first run, backfill the current season to date.
- On later runs, fetch the last few days, merge, dedupe, and rebuild JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


RAW_CACHE_PATH = Path("data/raw/statcast-hr-events.csv")
OUTPUT_PATH = Path("public/data/hr-distance-latest.json")
SAVANT_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://baseballsavant.mlb.com/statcast_search",
}


def number(value: str | None) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def iso_today() -> date:
    return datetime.now(timezone.utc).date()


def season_start(season: int) -> date:
    return date(season, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY)


def fetch_statcast_csv(season: int, start_date: date, end_date: date) -> list[dict[str, str]]:
    params = {
        "all": "true",
        "hfPT": "",
        "hfAB": "home.|",
        "hfGT": "R|",
        "hfPR": "",
        "hfZ": "",
        "hfStadium": "",
        "hfBBL": "",
        "hfNewZones": "",
        "hfPull": "",
        "hfC": "",
        "hfSea": f"{season}|",
        "hfSit": "",
        "player_type": "batter",
        "hfOuts": "",
        "opponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start_date.isoformat(),
        "game_date_lt": end_date.isoformat(),
        "hfInfield": "",
        "team": "",
        "position": "",
        "hfOutfield": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "game_date",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
        "min_pas": "0",
        "type": "details",
    }
    url = f"{SAVANT_URL}?{urlencode(params)}"
    request = Request(url, headers=REQUEST_HEADERS)

    try:
        with urlopen(request, timeout=45) as response:
            text = response.read().decode("utf-8")
    except HTTPError as error:
        print(
            "Baseball Savant request failed.\n"
            f"Status: {error.code} {error.reason}\n"
            f"Season: {season}\n"
            f"Date range: {start_date.isoformat()} through {end_date.isoformat()}\n"
            f"URL: {url}"
        )

        if error.code == 403:
            print(
                "Baseball Savant returned 403 Forbidden. This often means the "
                "request was blocked by upstream anti-bot or rate-limit rules. "
                "The script now sends browser-like headers, but GitHub Actions "
                "may still need a retry later if Baseball Savant blocks hosted runners."
            )

        raise

    return list(csv.DictReader(text.splitlines()))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def event_key(row: dict[str, str]) -> tuple[str, ...]:
    if row.get("sv_id"):
        return ("sv_id", row["sv_id"])

    return (
        "fallback",
        row.get("game_pk", ""),
        row.get("at_bat_number", ""),
        row.get("pitch_number", ""),
        row.get("player_name", "") or row.get("batter_name", "") or row.get("player", ""),
        row.get("game_date", ""),
    )


def has_distance(row: dict[str, str]) -> bool:
    return number(row.get("hit_distance_sc") or row.get("distance")) is not None


def is_home_run(row: dict[str, str]) -> bool:
    event = (row.get("events") or row.get("event") or "").strip().lower()
    return event in {"home_run", "home run"} or has_distance(row)


def merge_events(existing: list[dict[str, str]], incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, ...], dict[str, str]] = {}

    for row in existing + incoming:
        if not is_home_run(row) or not has_distance(row):
            continue

        key = event_key(row)
        if key == ("fallback", "", "", "", "", ""):
            continue

        merged[key] = row

    return sorted(
        merged.values(),
        key=lambda row: (
            parse_date(row.get("game_date")) or date.min,
            row.get("game_pk", ""),
            row.get("at_bat_number", ""),
            row.get("pitch_number", ""),
        ),
    )


def write_events(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    if not fieldnames:
        fieldnames = [
            "game_date",
            "player_name",
            "bat_team",
            "events",
            "hit_distance_sc",
            "launch_speed",
            "game_pk",
            "at_bat_number",
            "pitch_number",
            "sv_id",
        ]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_leaderboard(
    rows: list[dict[str, str]],
    minimum_hr: int,
    minimum_pa: int | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"distances": [], "exit_velocities": [], "team": "", "pa": set()}
    )

    for row in rows:
        player = (row.get("player_name") or row.get("batter_name") or row.get("player") or "").strip()
        team = (row.get("bat_team") or row.get("team") or "").strip()
        distance = number(row.get("hit_distance_sc") or row.get("distance"))
        exit_velocity = number(row.get("launch_speed") or row.get("exit_velocity"))
        plate_appearance = f"{row.get('game_pk', '')}:{row.get('at_bat_number', '')}"

        if not player or distance is None:
            continue

        grouped[player]["team"] = team or grouped[player]["team"]
        grouped[player]["distances"].append(distance)

        if exit_velocity is not None:
            grouped[player]["exit_velocities"].append(exit_velocity)

        if plate_appearance != ":":
            grouped[player]["pa"].add(plate_appearance)

    leaderboard = []
    for player, values in grouped.items():
        hr_count = len(values["distances"])
        pa_count = len(values["pa"])

        if hr_count < minimum_hr:
            continue

        if minimum_pa is not None and pa_count < minimum_pa:
            continue

        leaderboard.append(
            {
                "player": player,
                "team": values["team"],
                "hr": hr_count,
                "avgDistance": round(mean(values["distances"]), 1),
                "longestHr": round(max(values["distances"])),
                "avgExitVelocity": round(mean(values["exit_velocities"]), 1)
                if values["exit_velocities"]
                else 0,
            }
        )

    return sorted(leaderboard, key=lambda row: (-row["avgDistance"], -row["hr"], row["player"]))


def payload_without_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def write_json(
    path: Path,
    players: list[dict[str, Any]],
    minimum_hr: int,
    minimum_pa: int | None,
    raw_cache: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": {
            "rawCache": str(raw_cache),
        },
        "qualifiedBy": {
            "minimumHomeRuns": minimum_hr,
            "minimumPlateAppearances": minimum_pa,
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


def refresh_events(args: argparse.Namespace) -> list[dict[str, str]]:
    existing = read_csv(args.raw_cache)

    if args.input_csv:
        incoming = read_csv(args.input_csv)
        print(f"Read {len(incoming)} events from {args.input_csv}")
    else:
        today = args.end_date or iso_today()
        first_run = len(existing) == 0
        start = args.start_date

        if start is None:
            start = season_start(args.season) if first_run else today - timedelta(days=args.lookback_days)

        print(f"Fetching Statcast HR events from {start} through {today}")
        incoming = fetch_statcast_csv(args.season, start, today)
        print(f"Fetched {len(incoming)} events")

    merged = merge_events(existing, incoming)
    write_events(args.raw_cache, merged)
    print(f"Cached {len(merged)} deduped HR events at {args.raw_cache}")
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MLB HR distance leaderboard JSON.")
    parser.add_argument("--season", type=int, default=iso_today().year)
    parser.add_argument("--input-csv", type=Path, help="Merge a local Statcast CSV instead of fetching data.")
    parser.add_argument("--raw-cache", type=Path, default=RAW_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr", type=int, default=1)
    parser.add_argument("--min-pa", type=int, help="Optional plate appearance filter for offline analysis.")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--start-date", type=parse_date, help="Override fetch start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", type=parse_date, help="Override fetch end date, YYYY-MM-DD.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events = refresh_events(args)
    players = build_leaderboard(events, minimum_hr=args.min_hr, minimum_pa=args.min_pa)
    write_json(args.output, players, minimum_hr=args.min_hr, minimum_pa=args.min_pa, raw_cache=args.raw_cache)
    print(f"Wrote {len(players)} players to {args.output}")


if __name__ == "__main__":
    main()
