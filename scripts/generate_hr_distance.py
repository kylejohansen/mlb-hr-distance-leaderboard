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
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))

import pandas as pd
from pybaseball import playerid_reverse_lookup, statcast


RAW_CACHE_PATH = Path("data/raw/statcast-hr-events.csv")
OUTPUT_PATH = Path("public/data/hr-distance-latest.json")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
FETCH_CHUNK_DAYS = 7
RAW_COLUMNS = [
    "game_date",
    "batter",
    "player_name",
    "bat_team",
    "events",
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
    frame["hit_distance_sc"] = pd.to_numeric(frame["hit_distance_sc"], errors="coerce")
    frame["launch_speed"] = pd.to_numeric(frame["launch_speed"], errors="coerce")
    frame["launch_angle"] = pd.to_numeric(frame["launch_angle"], errors="coerce")
    frame["launch_speed_angle"] = pd.to_numeric(frame["launch_speed_angle"], errors="coerce")
    frame["batter"] = pd.to_numeric(frame["batter"], errors="coerce").astype("Int64")
    frame["pitcher"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["game_pk"] = pd.to_numeric(frame["game_pk"], errors="coerce").astype("Int64")
    frame["at_bat_number"] = pd.to_numeric(frame["at_bat_number"], errors="coerce").astype("Int64")
    frame["pitch_number"] = pd.to_numeric(frame["pitch_number"], errors="coerce").astype("Int64")

    frame = frame[
        frame["events"].str.lower().eq("home_run").fillna(False)
        & frame["hit_distance_sc"].notna()
        & frame["batter"].notna()
    ]

    return frame[RAW_COLUMNS]


def inspect_statcast_columns(frame: pd.DataFrame) -> None:
    columns = set(frame.columns)
    print("Statcast column availability:")
    for label, candidates in STATCAST_FIELD_GROUPS.items():
        present = [candidate for candidate in candidates if candidate in columns]
        status = ", ".join(present) if present else "not found"
        print(f"- {label}: {status}")


def fetch_statcast_events(start_date: date, end_date: date) -> pd.DataFrame:
    chunks = []
    current = start_date

    while current <= end_date:
        chunk_end = min(current + timedelta(days=FETCH_CHUNK_DAYS - 1), end_date)
        start_text = current.isoformat()
        end_text = chunk_end.isoformat()
        print(f"Fetching Statcast events with pybaseball.statcast({start_text}, {end_text})")
        chunk = statcast(start_dt=start_text, end_dt=end_text)

        if chunk is not None and not chunk.empty:
            chunks.append(chunk)

        current = chunk_end + timedelta(days=1)

    if not chunks:
        return pd.DataFrame(columns=RAW_COLUMNS)

    events = pd.concat(chunks, ignore_index=True)
    inspect_statcast_columns(events)
    return normalize_event_frame(events)


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
    marker = " homers "
    if marker not in text:
        return None

    name = text.split(marker, 1)[0].strip()
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


def percentile_map(rows: list[dict[str, Any]], key: str) -> dict[int, float]:
    values = sorted(row[key] for row in rows if row.get(key) is not None)
    if not values:
        return {}

    percentiles = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue

        count_at_or_below = sum(1 for item in values if item <= value)
        percentiles[id(row)] = round((count_at_or_below / len(values)) * 100, 2)

    return percentiles


def sample_badge(player: dict[str, Any]) -> str:
    if player["hr"] >= 10:
        return "Reliable Sample"

    if player["hr"] < 5 and player["longballIndex"] >= 85:
        return "Small Sample Monster"

    if player["avgDistance"] >= 410 and player["avgExitVelocity"] >= 105:
        return "No-Doubter Candidate"

    if player["avgDistance"] <= 390:
        return "Wall-Scraper Watch"

    return "Building Sample"


def build_leaderboard(
    events: pd.DataFrame,
    minimum_hr: int,
    minimum_pa: int | None,
) -> list[dict[str, Any]]:
    if events.empty:
        return []

    grouped = events.groupby(["batter", "player_name"], dropna=False)
    players = []

    for (_batter, player), group in grouped:
        hr_count = int(len(group))

        if hr_count < minimum_hr:
            continue

        plate_appearances = group[["game_pk", "at_bat_number"]].drop_duplicates()
        if minimum_pa is not None and len(plate_appearances) < minimum_pa:
            continue

        team = group["bat_team"].dropna().astype(str)
        launch_angles = pd.to_numeric(group["launch_angle"], errors="coerce")
        barrel_values = pd.to_numeric(group["launch_speed_angle"], errors="coerce")
        barrel_rate = round(float(barrel_values.eq(6).sum() / hr_count), 3) if barrel_values.notna().any() else None
        sweet_spot_rate = round(float(launch_angles.between(8, 32).sum() / hr_count), 3)
        players.append(
            {
                "player": str(player),
                "team": team.iloc[-1] if not team.empty else "",
                "hr": hr_count,
                "avgDistance": round(float(group["hit_distance_sc"].mean()), 1),
                "longestHr": round(float(group["hit_distance_sc"].max())),
                "avgExitVelocity": round(float(group["launch_speed"].dropna().mean()), 1)
                if group["launch_speed"].notna().any()
                else 0,
                "barrelRate": barrel_rate,
                "sweetSpotRate": sweet_spot_rate,
            }
        )

    percentile_weights = [
        ("avgDistance", 0.30),
        ("avgExitVelocity", 0.25),
        ("barrelRate", 0.20),
        ("longestHr", 0.15),
        ("sweetSpotRate", 0.10),
    ]
    percentile_maps = {key: percentile_map(players, key) for key, _weight in percentile_weights}

    for player in players:
        weighted_total = 0.0
        available_weight = 0.0
        for key, weight in percentile_weights:
            percentile = percentile_maps[key].get(id(player))
            if percentile is None:
                continue

            weighted_total += percentile * weight
            available_weight += weight

        player["longballIndex"] = round(weighted_total / available_weight, 1) if available_weight else 0
        player["sampleBadge"] = sample_badge(player)

    return sorted(players, key=lambda row: (-row["longballIndex"], -row["hr"], row["player"]))


def payload_without_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def write_json(
    path: Path,
    players: list[dict[str, Any]],
    minimum_hr: int,
    minimum_pa: int | None,
    raw_cache: Path,
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
            "fetcher": "pybaseball.statcast",
            "longballIndexVersion": "v1-distance-ev-barrel-longest-sweetspot",
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


def refresh_events(args: argparse.Namespace) -> pd.DataFrame:
    existing = read_events(args.raw_cache)
    first_run = existing.empty

    if args.input_csv:
        print(f"Reading local Statcast CSV from {args.input_csv}")
        incoming = normalize_event_frame(pd.read_csv(args.input_csv))
        source = f"local CSV: {args.input_csv}"
        start = args.start_date
        end = args.end_date
    else:
        end = args.end_date or iso_today()
        start = args.start_date

        if start is None:
            start = season_start(args.season) if first_run else end - timedelta(days=args.lookback_days)

        print(f"Fetching Statcast HR events from {start} through {end}")
        incoming = fetch_statcast_events(start, end)
        source = "pybaseball.statcast"

    if first_run and incoming.empty and not args.allow_empty:
        raise RuntimeError(
            "No existing raw cache was found and the data fetch returned 0 home-run events with "
            "Statcast distance. Refusing to publish an empty leaderboard.\n"
            f"Source method: {source}\n"
            f"Date range: {start or 'not specified'} through {end or 'not specified'}\n"
            f"Raw cache path: {args.raw_cache}\n"
            "If this date range truly has no home runs, rerun with --allow-empty."
        )

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
    parser.add_argument("--allow-empty", action="store_true", help="Allow writing an empty leaderboard JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events = refresh_events(args)
    players = build_leaderboard(events, minimum_hr=args.min_hr, minimum_pa=args.min_pa)
    write_json(
        args.output,
        players,
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
        raw_cache=args.raw_cache,
        allow_empty=args.allow_empty,
    )
    print(f"Wrote {len(players)} players to {args.output}")


if __name__ == "__main__":
    main()
