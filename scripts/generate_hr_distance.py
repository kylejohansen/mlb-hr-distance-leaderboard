#!/usr/bin/env python3
"""Generate frontend-ready Longball Index JSON.

This script is the only Statcast access layer. The frontend reads static JSON
from public/data and never calls Baseball Savant, pybaseball, or any live API.

Default behavior:
- Keep raw batted-ball events in data/raw/statcast-bbe-events.csv.
- On the first run, backfill the current season to date.
- On later runs, fetch the last few days, merge, dedupe, and rebuild JSON.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))

import pandas as pd
from pybaseball import playerid_reverse_lookup, statcast


RAW_CACHE_PATH = Path("data/raw/statcast-bbe-events.csv")
OUTPUT_PATH = Path("public/data/hr-distance-latest.json")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
FETCH_CHUNK_DAYS = 7
LBI_VERSION = "1.0-provisional"
NORMAL_SCORE_SCALE = 31.4
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
    "barrelRate": 0.40,
    "hardHitRate": 0.20,
    "avgDistanceOnBarrels": 0.20,
    "sweetSpotRate": 0.20,
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
    chunks = []
    current = start_date

    while current <= end_date:
        chunk_end = min(current + timedelta(days=FETCH_CHUNK_DAYS - 1), end_date)
        start_text = current.isoformat()
        end_text = chunk_end.isoformat()
        print(f"Fetching Statcast batted-ball events with pybaseball.statcast({start_text}, {end_text})")
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

    for key, base_weight in LBI_COMPONENT_WEIGHTS.items():
        if key == "avgDistanceOnBarrels" and player["barrels"] < 10:
            components[key] = {
                "value": None,
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
    minimum_hr: int,
    minimum_pa: int | None,
) -> tuple[list[dict[str, Any]], int, int]:
    if events.empty:
        return [], 0, 0

    team_games = estimated_team_games(events)
    bbe_minimum = max(50, round(team_games * 1.5))
    grouped = events.groupby(["batter", "player_name"], dropna=False)
    players = []

    for (_batter, player), group in grouped:
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
        hr_distances = pd.to_numeric(home_runs["hit_distance_sc"], errors="coerce").dropna()

        players.append(
            {
                "player": str(player),
                "team": team.iloc[-1] if not team.empty else "",
                "bbe": bbe,
                "hr": hr_count,
                "barrels": int(len(barrels)),
                "barrelRate": round(float(len(barrels) / bbe), 3),
                "hardHitRate": round(float(hard_hits.sum() / bbe), 3),
                "sweetSpotRate": round(float(sweet_spots.sum() / bbe), 3),
                "avgDistanceOnBarrels": round(float(barrel_distances.mean()), 1)
                if len(barrel_distances) and len(barrels) >= 10
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

    return sorted(players, key=lambda row: (-row["longballIndex"], -row["bbe"], row["player"])), bbe_minimum, team_games


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
            "longballIndexVersion": LBI_VERSION,
            "methodology": "Barrel% 40%, Hard Hit% 20%, Avg Distance on Barrels 20%, Sweet Spot% 20%",
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

        print(f"Fetching Statcast batted-ball events from {start} through {end}")
        incoming = fetch_statcast_events(start, end)
        source = "pybaseball.statcast"

    if first_run and incoming.empty and not args.allow_empty:
        raise RuntimeError(
            "No existing raw cache was found and the data fetch returned 0 usable batted-ball events. "
            "Refusing to publish an empty leaderboard.\n"
            f"Source method: {source}\n"
            f"Date range: {start or 'not specified'} through {end or 'not specified'}\n"
            f"Raw cache path: {args.raw_cache}\n"
            "If this date range truly has no usable batted balls, rerun with --allow-empty."
        )

    merged = merge_events(existing, incoming)
    write_events(args.raw_cache, merged)
    print(f"Cached {len(merged)} deduped batted-ball events at {args.raw_cache}")
    return merged


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
    events = refresh_events(args)
    players, bbe_minimum, team_games = build_leaderboard(
        events,
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
    )
    write_json(
        args.output,
        players,
        minimum_hr=args.min_hr,
        minimum_pa=args.min_pa,
        bbe_minimum=bbe_minimum,
        team_games=team_games,
        raw_cache=args.raw_cache,
        allow_empty=args.allow_empty,
    )
    print(f"Wrote {len(players)} players to {args.output}")


if __name__ == "__main__":
    main()
