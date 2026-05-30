#!/usr/bin/env python3
"""Generate an internal single-day Stack Watch probable-starter prototype.

Stack Watch is an internal daily probable-starter/slate prototype, not a public
formula. It pulls one MLB schedule date at a time and includes every probable
starter slot returned by the schedule feed.

Stack Score remains pitcher-specific. Opponent lineup LBI, park, and weather
fields are context only and must not be blended into the score. Weather fields
are included in CSV/JSON output, but weather notes are only shown when real
weather is available. Park factors are currently scaffolded/pending:
parkHrTag should use an HR-specific park factor, not an overall/run park
factor, and parkCarryTag should use a separate carry/distance factor if one is
available.

Public Hot Dog JSON is qualified-only, so this script uses a broader internal
Home Run Tracker lookup for probable starters. That broader lookup does not
change public Hot Dog leaderboard eligibility.

Full Stack Watch scores require adjusted xHR/BBE Allowed, HR-Capable Rate
Allowed, and HR-Window Thunder Rate Allowed. If a starter has raw Statcast data
but lacks required HRT inputs, the script keeps the starter visible with a
limited/no-score status rather than fabricating a score.

Current Stack Watch score:

70% HR-Window Thunder Allowed percentile
20% adjusted xHR/BBE Allowed percentile
10% HR-Capable Rate Allowed percentile

HDI v1.1 and Cooked / 100 BBE are context fields, not the score spine.
Rows are labeled with scoreStatus: Full score, Limited sample, Very limited
sample, Missing inputs, or No current data.
Percentiles are calculated from the current eligible SP workload pool:
pitcherRole == "SP" and BBE allowed >= 175.
"""

from __future__ import annotations

import argparse
import bisect
import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd

import diagnose_hot_dog_index_vnext as hdi
import generate_hot_dog_stand as hot_dog


DATA_DIR = Path("public/data")
RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("/tmp")
PARK_FACTORS_PATH = Path("data/park-factors.json")
REQUIRED_SCORE_COLUMNS = [
    "stackWatchScore",
    "hr_window_thunder_rate_allowed",
    "adjusted_xhr_proxy_per_bbe_allowed",
    "hr_capable_bbe_rate_allowed",
]
SCORE_STATUS_ORDER = {
    "Full score": 0,
    "Limited sample": 1,
    "Very limited sample": 2,
    "Missing inputs": 3,
    "No current data": 4,
}
VENUE_COORDINATES = {
    "American Family Field": (43.0280, -87.9712),
    "Angel Stadium": (33.8003, -117.8827),
    "Busch Stadium": (38.6226, -90.1928),
    "Chase Field": (33.4455, -112.0667),
    "Citi Field": (40.7571, -73.8458),
    "Citizens Bank Park": (39.9061, -75.1665),
    "Comerica Park": (42.3390, -83.0485),
    "Coors Field": (39.7559, -104.9942),
    "Daikin Park": (29.7573, -95.3555),
    "Dodger Stadium": (34.0739, -118.2400),
    "Fenway Park": (42.3467, -71.0972),
    "Globe Life Field": (32.7473, -97.0842),
    "Great American Ball Park": (39.0979, -84.5066),
    "Kauffman Stadium": (39.0517, -94.4803),
    "loanDepot park": (25.7781, -80.2197),
    "Nationals Park": (38.8730, -77.0074),
    "Oracle Park": (37.7786, -122.3893),
    "Oriole Park at Camden Yards": (39.2840, -76.6217),
    "Petco Park": (32.7073, -117.1573),
    "PNC Park": (40.4469, -80.0057),
    "Progressive Field": (41.4962, -81.6852),
    "Rate Field": (41.8300, -87.6338),
    "Rogers Centre": (43.6414, -79.3894),
    "Sutter Health Park": (38.5804, -121.5136),
    "T-Mobile Park": (47.5914, -122.3325),
    "Truist Park": (33.8908, -84.4678),
    "Tropicana Field": (27.7683, -82.6534),
    "UNIQLO Field at Dodger Stadium": (34.0739, -118.2400),
    "Wrigley Field": (41.9484, -87.6553),
    "Yankee Stadium": (40.8296, -73.9262),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate internal Stack Watch probable-starter slate.")
    parser.add_argument("--date", required=True, help="Single slate date in YYYY-MM-DD format.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def fetch_schedule(date: str, output_dir: Path) -> dict[str, Any]:
    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={date}&hydrate=probablePitcher,team,venue"
    )
    cache_path = output_dir / f"mlb_schedule_{date}.json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            schedule = json.load(response)
            cache_path.write_text(json.dumps(schedule))
            return schedule
    except (OSError, urllib.error.URLError, TimeoutError):
        try:
            result = subprocess.run(
                ["curl", "-fsSL", url],
                check=True,
                capture_output=True,
                text=True,
            )
            cache_path.write_text(result.stdout)
            return json.loads(result.stdout)
        except (OSError, subprocess.CalledProcessError):
            if cache_path.exists():
                return json.loads(cache_path.read_text())
            raise RuntimeError(
                f"Could not fetch MLB schedule for {date}. If network is sandboxed, "
                f"prefetch {url} to {cache_path} and rerun."
            )


def probable_starters(schedule: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for date_block in schedule.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams", {})
            venue_info = game.get("venue") or {}
            venue = venue_info.get("name", "")
            for side, opponent_side, home_away in (("away", "home", "away"), ("home", "away", "home")):
                entry = teams.get(side, {})
                opponent = teams.get(opponent_side, {})
                pitcher = entry.get("probablePitcher") or {}
                if not pitcher.get("id"):
                    continue
                team = entry.get("team", {})
                opponent_team = opponent.get("team", {})
                rows.append(
                    {
                        "date": date_block.get("date"),
                        "gameDate": game.get("gameDate"),
                        "gameTime": game.get("gameDate"),
                        "gamePk": game.get("gamePk"),
                        "pitcherId": int(pitcher["id"]),
                        "pitcher": pitcher.get("fullName", ""),
                        "team": team.get("abbreviation", ""),
                        "opponent": opponent_team.get("abbreviation", ""),
                        "homeAway": home_away,
                        "venue": venue,
                        "venueId": venue_info.get("id"),
                        "game": f"{team.get('abbreviation', '')} @ {opponent_team.get('abbreviation', '')}"
                        if home_away == "away"
                        else f"{opponent_team.get('abbreviation', '')} @ {team.get('abbreviation', '')}",
                    }
                )
    return pd.DataFrame(rows)


def percentile_from_pool(values: list[float], value: Any) -> float | None:
    if pd.isna(value) or not values:
        return None
    return bisect.bisect_right(values, float(value)) / len(values) * 100


def fetch_json_with_cache(url: str, cache_path: Path) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
            cache_path.write_text(json.dumps(payload))
            return payload
    except (OSError, urllib.error.URLError, TimeoutError):
        try:
            result = subprocess.run(["curl", "-fsSL", url], check=True, capture_output=True, text=True)
            cache_path.write_text(result.stdout)
            return json.loads(result.stdout)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            if cache_path.exists():
                return json.loads(cache_path.read_text())
            return {}


def hitter_context(data_dir: Path) -> tuple[dict[int, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    path = data_dir / "hr-distance-latest.json"
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text())
    hitters = data.get("players", [])
    by_id: dict[int, dict[str, Any]] = {}
    by_team: dict[str, list[dict[str, Any]]] = {}
    for hitter in hitters:
        hitter_id = hitter.get("batter")
        if hitter_id is not None:
            by_id[int(hitter_id)] = hitter
        team = str(hitter.get("team") or "")
        if team:
            by_team.setdefault(team, []).append(hitter)
    for team, rows in by_team.items():
        playing_time_key = "pa" if any(row.get("pa") for row in rows) else "bbe"
        by_team[team] = sorted(
            rows,
            key=lambda row: (
                number_or_none(row.get(playing_time_key)) or 0,
                number_or_none(row.get("longballIndex")) or 0,
            ),
            reverse=True,
        )
    return by_id, by_team


def confirmed_lineup_ids(game_pk: Any, side: str, output_dir: Path) -> list[int]:
    if pd.isna(game_pk):
        return []
    cache_path = output_dir / f"mlb_boxscore_{int(game_pk)}.json"
    url = f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/boxscore"
    boxscore = fetch_json_with_cache(url, cache_path)
    players = (((boxscore.get("teams") or {}).get(side) or {}).get("players") or {})
    lineup = []
    for player in players.values():
        batting_order = player.get("battingOrder")
        person = player.get("person") or {}
        if batting_order and person.get("id"):
            lineup.append((str(batting_order), int(person["id"])))
    return [player_id for _, player_id in sorted(lineup)[:9]]


def lineup_metrics(selected: list[dict[str, Any]], source: str) -> dict[str, Any]:
    if not selected:
        return {
            "opponentLineupSource": "unavailable",
            "opponentLineupAvgLbi": None,
            "opponentLineupTop3Lbi": None,
            "opponentLineupLbi120Count": None,
            "opponentLineupLbi140Count": None,
            "opponentLineupHrWindowThunderAvg": None,
            "lineupNames": [],
        }
    lbi_values = [number_or_none(hitter.get("longballIndex")) for hitter in selected]
    lbi_values = [value for value in lbi_values if value is not None]
    thunder_values = [number_or_none(hitter.get("hrWindowThunderRate")) for hitter in selected]
    thunder_values = [value for value in thunder_values if value is not None]
    top3 = sorted(lbi_values, reverse=True)[:3]
    return {
        "opponentLineupSource": source,
        "opponentLineupAvgLbi": round(sum(lbi_values) / len(lbi_values), 1) if lbi_values else None,
        "opponentLineupTop3Lbi": round(sum(top3) / len(top3), 1) if top3 else None,
        "opponentLineupLbi120Count": sum(1 for value in lbi_values if value >= 120),
        "opponentLineupLbi140Count": sum(1 for value in lbi_values if value >= 140),
        "opponentLineupHrWindowThunderAvg": round(sum(thunder_values) / len(thunder_values), 4) if thunder_values else None,
        "lineupNames": [str(hitter.get("player") or "") for hitter in selected],
    }


def opponent_lineup_context(row: pd.Series, by_id: dict[int, dict[str, Any]], by_team: dict[str, list[dict[str, Any]]], output_dir: Path) -> dict[str, Any]:
    opponent_side = "home" if row.get("homeAway") == "away" else "away"
    confirmed_ids = confirmed_lineup_ids(row.get("gamePk"), opponent_side, output_dir)
    confirmed_hitters = [by_id[player_id] for player_id in confirmed_ids if player_id in by_id]
    if confirmed_hitters:
        return lineup_metrics(confirmed_hitters, "confirmed")
    team_hitters = by_team.get(str(row.get("opponent") or ""), [])[:9]
    if team_hitters:
        return lineup_metrics(team_hitters, "team proxy")
    return lineup_metrics([], "unavailable")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value or pd.isna(value):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def weather_cache_name(venue: str, game_time: Any) -> str:
    game_dt = parse_iso_datetime(game_time)
    date_part = game_dt.date().isoformat() if game_dt else "unknown-date"
    safe_venue = "".join(char.lower() if char.isalnum() else "_" for char in venue).strip("_")
    return f"open_meteo_{safe_venue}_{date_part}.json"


def fetch_open_meteo_weather(venue: str, game_time: Any, output_dir: Path) -> dict[str, Any]:
    coordinates = VENUE_COORDINATES.get(str(venue or ""))
    if not coordinates:
        return {"weatherStatus": "Venue coordinates unavailable"}
    game_dt = parse_iso_datetime(game_time)
    if game_dt is None:
        return {"weatherStatus": "Game time unavailable"}

    latitude, longitude = coordinates
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation_probability",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "UTC",
        "start_date": game_dt.date().isoformat(),
        "end_date": game_dt.date().isoformat(),
    }
    url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
    weather = fetch_json_with_cache(url, output_dir / weather_cache_name(venue, game_time))
    hourly = weather.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return {"weatherStatus": "Not available", "weatherSource": "Open-Meteo"}

    parsed_times = [parse_iso_datetime(time_value) for time_value in times]
    indexed_times = [(idx, time_value) for idx, time_value in enumerate(parsed_times) if time_value is not None]
    if not indexed_times:
        return {"weatherStatus": "Not available", "weatherSource": "Open-Meteo"}
    closest_idx, _ = min(indexed_times, key=lambda item: abs((item[1] - game_dt).total_seconds()))

    def hourly_value(key: str) -> Any:
        values = hourly.get(key) or []
        return values[closest_idx] if closest_idx < len(values) else None

    return {
        "weatherStatus": "Available",
        "weatherSource": "Open-Meteo",
        "temperature": hourly_value("temperature_2m"),
        "windSpeed": hourly_value("wind_speed_10m"),
        "windDirection": hourly_value("wind_direction_10m"),
        "precipitationRisk": hourly_value("precipitation_probability"),
    }


def weather_context(row: pd.Series, output_dir: Path) -> dict[str, Any]:
    return fetch_open_meteo_weather(str(row.get("venue") or ""), row.get("gameTime"), output_dir)


def load_park_factors(path: Path = PARK_FACTORS_PATH) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text())
    parks = data.get("parks") or []
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for park in parks:
        venue_id = park.get("venueId")
        venue_name = str(park.get("venueName") or "")
        if venue_id is not None:
            try:
                by_id[int(venue_id)] = park
            except (TypeError, ValueError):
                pass
        if venue_name:
            by_name[venue_name.lower()] = park
    return by_id, by_name


def park_factor_context(row: pd.Series, by_id: dict[int, dict[str, Any]], by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    park: dict[str, Any] | None = None
    venue_id = row.get("venueId")
    if not pd.isna(venue_id):
        try:
            park = by_id.get(int(venue_id))
        except (TypeError, ValueError):
            park = None
    if park is None:
        park = by_name.get(str(row.get("venue") or "").lower())
    if park is None:
        return {
            "parkHrFactor": None,
            "parkHrTag": None,
            "parkCarryFactor": None,
            "parkCarryTag": None,
            "parkFactorSource": None,
        }
    return {
        "parkHrFactor": park.get("hrFactor"),
        "parkHrTag": park.get("hrTag"),
        "parkCarryFactor": park.get("carryFactor"),
        "parkCarryTag": park.get("carryTag"),
        "parkFactorSource": park.get("source"),
    }


def add_context_fields(joined: pd.DataFrame, data_dir: Path, output_dir: Path) -> pd.DataFrame:
    by_id, by_team = hitter_context(data_dir)
    contexts = joined.apply(lambda row: opponent_lineup_context(row, by_id, by_team, output_dir), axis=1)
    for key in [
        "opponentLineupSource",
        "opponentLineupAvgLbi",
        "opponentLineupTop3Lbi",
        "opponentLineupLbi120Count",
        "opponentLineupLbi140Count",
        "opponentLineupHrWindowThunderAvg",
        "lineupNames",
    ]:
        joined[key] = contexts.map(lambda context: context.get(key))
    weather_contexts = joined.apply(lambda row: weather_context(row, output_dir), axis=1)
    for key in ["weatherStatus", "weatherSource", "temperature", "windSpeed", "windDirection", "precipitationRisk"]:
        joined[key] = weather_contexts.map(lambda context: context.get(key))
    joined["weatherStatus"] = joined["weatherStatus"].fillna("Not available")
    park_by_id, park_by_name = load_park_factors()
    park_contexts = joined.apply(lambda row: park_factor_context(row, park_by_id, park_by_name), axis=1)
    for key in ["parkHrFactor", "parkHrTag", "parkCarryFactor", "parkCarryTag", "parkFactorSource"]:
        joined[key] = park_contexts.map(lambda context: context.get(key))
    return joined


def raw_statcast_pitcher_context(raw_dir: Path) -> pd.DataFrame:
    path = hdi.pitch_cache_path(raw_dir, 2026)
    pitches = pd.read_csv(path)
    context = hot_dog.build_statcast_pitcher_context(pitches)
    if context.empty:
        return pd.DataFrame(columns=["pitcherId"])
    context = context.rename(
        columns={
            "pitcher_id": "pitcherId",
            "pitcher_role": "rawPitcherRole",
            "appearances": "rawAppearances",
            "games_started": "rawGamesStarted",
            "relief_appearances": "rawReliefAppearances",
            "bbe_allowed": "rawBbeAllowed",
            "hr_window_thunder_bbe_allowed": "rawHrWindowThunderBbeAllowed",
            "hr_window_thunder_rate_allowed": "rawHrWindowThunderRateAllowed",
        }
    )
    context["pitcherId"] = pd.to_numeric(context["pitcherId"], errors="coerce").astype("Int64")

    # Best-effort current team and display name from the raw pitch cache.
    frame = pitches.dropna(subset=["pitcher"]).copy()
    frame["pitcherId"] = pd.to_numeric(frame["pitcher"], errors="coerce").astype("Int64")
    frame["game_date"] = pd.to_datetime(frame.get("game_date"), errors="coerce")
    frame["events"] = frame.get("events", pd.Series(pd.NA, index=frame.index)).astype("string").str.lower()
    frame["pitchingTeam"] = pd.NA
    inning = frame.get("inning_topbot", pd.Series("", index=frame.index)).astype("string").str.lower()
    frame.loc[inning.eq("top"), "pitchingTeam"] = frame.loc[inning.eq("top"), "home_team"]
    frame.loc[inning.eq("bot"), "pitchingTeam"] = frame.loc[inning.eq("bot"), "away_team"]
    identity = (
        frame.sort_values(["pitcherId", "game_date"])
        .dropna(subset=["pitcherId"])
        .groupby("pitcherId", as_index=False)
        .tail(1)[["pitcherId", "player_name", "pitchingTeam"]]
        .rename(columns={"player_name": "rawPitcherName", "pitchingTeam": "rawTeam"})
    )
    context = context.merge(identity, on="pitcherId", how="left")
    hr_counts = (
        frame[frame["events"].eq("home_run")]
        .groupby("pitcherId")
        .size()
        .rename("rawHrAllowed")
        .reset_index()
    )
    context = context.merge(hr_counts, on="pitcherId", how="left")
    context["rawHrAllowed"] = context["rawHrAllowed"].fillna(0).astype(int)
    context["rawHrWindowThunderRateAllowed"] = (
        context["rawHrWindowThunderBbeAllowed"] / context["rawBbeAllowed"].where(context["rawBbeAllowed"] > 0)
    )
    return context


def fetch_internal_tracker_context(output_dir: Path) -> pd.DataFrame:
    params = {
        "player_type": "Pitcher",
        "year": "2026",
        "cat": hot_dog.HOME_RUN_TRACKER_CAT,
        "min": "0",
        "csv": "true",
    }
    url = f"{hot_dog.HOME_RUN_TRACKER_URL}?{urlencode(params)}"
    cache_path = output_dir / "stack_watch_hrt_pitchers_2026_adj_xhr.csv"
    try:
        frame = hot_dog.fetch_home_run_tracker_pitchers(2026)
        cache_path.write_text(frame.to_csv(index=False))
    except (OSError, urllib.error.URLError, TimeoutError):
        try:
            curl = ["curl", "-fsSL", "-A", hot_dog.savant_headers()["User-Agent"], "-e", hot_dog.HOME_RUN_TRACKER_URL, url]
            result = subprocess.run(curl, check=True, capture_output=True, text=True)
            cache_path.write_text(result.stdout)
            frame = pd.read_csv(io.StringIO(result.stdout))
        except (OSError, subprocess.CalledProcessError):
            if not cache_path.exists():
                return pd.DataFrame(columns=["pitcherId"])
            frame = pd.read_csv(cache_path)

    tracker = hot_dog.normalize_tracker(frame)
    if tracker.empty:
        return pd.DataFrame(columns=["pitcherId"])
    tracker = tracker.rename(
        columns={
            "pitcher_id": "pitcherId",
            "pitcher": "trackerPitcher",
            "team": "trackerTeam",
            "xhr": "trackerAdjustedXhrAllowed",
            "hr_capable_bbe_allowed": "trackerHrCapableBbeAllowed",
            "no_doubters": "trackerNoDoubtersAllowed",
            "mostly_gone": "trackerMostlyGoneAllowed",
            "doubters": "trackerDoubtersAllowed",
            "hr_total": "trackerHrAllowed",
            "xhr_diff": "trackerXhrDiffAllowed",
        }
    )
    return tracker[
        [
            "pitcherId",
            "trackerPitcher",
            "trackerTeam",
            "trackerAdjustedXhrAllowed",
            "trackerHrCapableBbeAllowed",
            "trackerNoDoubtersAllowed",
            "trackerMostlyGoneAllowed",
            "trackerDoubtersAllowed",
            "trackerHrAllowed",
            "trackerXhrDiffAllowed",
        ]
    ].copy()


def write_internal_pitcher_components(frame: pd.DataFrame, output_dir: Path) -> None:
    columns = [
        "pitcherId",
        "pitcher",
        "team",
        "pitcherRole",
        "publishedHotDogData",
        "bbe_allowed",
        "hr_total",
        "hr_window_thunder_bbe_allowed",
        "hr_window_thunder_rate_allowed",
        "adjusted_xhr_proxy_allowed",
        "adjusted_xhr_proxy_per_bbe_allowed",
        "hr_capable_bbe_allowed",
        "hr_capable_bbe_rate_allowed",
        "no_doubters_allowed",
        "no_doubter_rate_allowed",
        "current_hdi",
        "cooked_per_100_bbe",
        "stackWatchScore",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    available = [column for column in columns if column in frame.columns]
    frame[available].sort_values("stackWatchScore", ascending=False, na_position="last").to_csv(
        output_dir / "stack_watch_pitcher_components_2026.csv",
        index=False,
    )


def current_pitchers(data_dir: Path, raw_dir: Path, output_dir: Path) -> tuple[pd.DataFrame, int]:
    published = hdi.add_variant_scores(hdi.season_frame(data_dir, raw_dir, 2026))
    published["publishedHotDogData"] = True
    published["adjusted_xhr_proxy_allowed"] = published["adjusted_xhr_allowed"]
    published["adjusted_xhr_proxy_per_bbe_allowed"] = published["adjusted_xhr_per_bbe_allowed"]
    published["no_doubter_rate_allowed"] = published["no_doubter_rate_allowed"].fillna(0)
    if "pitcherRole" not in published.columns and "role" in published.columns:
        published["pitcherRole"] = published["role"]

    raw = raw_statcast_pitcher_context(raw_dir)
    tracker = fetch_internal_tracker_context(output_dir)
    frame = raw.merge(published, on="pitcherId", how="left", suffixes=("", "_published"))
    if not tracker.empty:
        frame = frame.merge(tracker, on="pitcherId", how="left")
    frame["publishedHotDogData"] = frame["publishedHotDogData"].where(frame["publishedHotDogData"].notna(), False).astype(bool)
    frame["pitcher"] = frame["pitcher"].fillna(frame["rawPitcherName"])
    if "trackerPitcher" in frame.columns:
        frame["pitcher"] = frame["pitcher"].fillna(frame["trackerPitcher"])
    frame["team"] = frame["team"].fillna(frame["rawTeam"])
    if "trackerTeam" in frame.columns:
        frame["team"] = frame["team"].fillna(frame["trackerTeam"])
    frame["pitcherRole"] = frame["pitcherRole"].fillna(frame["rawPitcherRole"])
    frame["bbe_allowed"] = frame["bbe_allowed"].fillna(frame["rawBbeAllowed"])
    if "hr_total" not in frame.columns:
        frame["hr_total"] = pd.NA
    frame["hr_total"] = frame["hr_total"].where(frame["hr_total"].notna(), frame["rawHrAllowed"])
    if "trackerHrAllowed" in frame.columns:
        frame["hr_total"] = frame["hr_total"].where(frame["hr_total"].notna(), frame["trackerHrAllowed"])
    frame["hr_window_thunder_bbe_allowed"] = frame["hr_window_thunder_bbe_allowed"].fillna(
        frame["rawHrWindowThunderBbeAllowed"]
    )
    frame["hr_window_thunder_rate_allowed"] = frame["hr_window_thunder_rate_allowed"].fillna(
        frame["rawHrWindowThunderRateAllowed"]
    )

    numeric_defaults = {
        "adjusted_xhr_proxy_allowed": pd.NA,
        "adjusted_xhr_proxy_per_bbe_allowed": pd.NA,
        "hr_capable_bbe_allowed": pd.NA,
        "hr_capable_bbe_rate_allowed": pd.NA,
        "no_doubter_rate_allowed": 0,
        "avg_ev_allowed": frame.get("avgExitVelocityAllowed", pd.Series(pd.NA, index=frame.index)),
        "hard_hit_rate_allowed": pd.NA,
        "barrel_rate_allowed": pd.NA,
        "current_hdi": pd.NA,
    }
    for column, default in numeric_defaults.items():
        if column not in frame.columns:
            frame[column] = default
    if "trackerAdjustedXhrAllowed" in frame.columns:
        frame["adjusted_xhr_proxy_allowed"] = frame["adjusted_xhr_proxy_allowed"].where(
            frame["adjusted_xhr_proxy_allowed"].notna(), frame["trackerAdjustedXhrAllowed"]
        )
    if "trackerHrCapableBbeAllowed" in frame.columns:
        frame["hr_capable_bbe_allowed"] = frame["hr_capable_bbe_allowed"].where(
            frame["hr_capable_bbe_allowed"].notna(), frame["trackerHrCapableBbeAllowed"]
        )
    if "trackerNoDoubtersAllowed" in frame.columns:
        if "no_doubters_allowed" not in frame.columns:
            frame["no_doubters_allowed"] = pd.NA
        frame["no_doubters_allowed"] = frame["no_doubters_allowed"].where(
            frame["no_doubters_allowed"].notna(), frame["trackerNoDoubtersAllowed"]
        )
    if "no_doubters_allowed" not in frame.columns:
        frame["no_doubters_allowed"] = pd.NA
    frame["adjusted_xhr_proxy_allowed"] = pd.to_numeric(frame["adjusted_xhr_proxy_allowed"], errors="coerce")
    frame["hr_capable_bbe_allowed"] = pd.to_numeric(frame["hr_capable_bbe_allowed"], errors="coerce")
    frame["no_doubters_allowed"] = pd.to_numeric(frame.get("no_doubters_allowed"), errors="coerce")
    frame["adjusted_xhr_proxy_per_bbe_allowed"] = frame["adjusted_xhr_proxy_per_bbe_allowed"].where(
        frame["adjusted_xhr_proxy_per_bbe_allowed"].notna(),
        frame["adjusted_xhr_proxy_allowed"] / frame["bbe_allowed"].where(frame["bbe_allowed"] > 0),
    )
    frame["hr_capable_bbe_rate_allowed"] = frame["hr_capable_bbe_rate_allowed"].where(
        frame["hr_capable_bbe_rate_allowed"].notna(),
        frame["hr_capable_bbe_allowed"] / frame["bbe_allowed"].where(frame["bbe_allowed"] > 0),
    )
    frame["no_doubter_rate_allowed"] = frame["no_doubter_rate_allowed"].where(
        frame["no_doubter_rate_allowed"].notna(),
        frame["no_doubters_allowed"] / frame["hr_capable_bbe_allowed"].where(frame["hr_capable_bbe_allowed"] > 0),
    )
    frame["adjusted_xhr_proxy_per_bbe_allowed"] = pd.to_numeric(
        frame["adjusted_xhr_proxy_per_bbe_allowed"], errors="coerce"
    )
    frame["hr_capable_bbe_rate_allowed"] = pd.to_numeric(frame["hr_capable_bbe_rate_allowed"], errors="coerce")
    frame["no_doubter_rate_allowed"] = pd.to_numeric(frame["no_doubter_rate_allowed"], errors="coerce").fillna(0)
    frame = hdi.add_stack_watch_scores(frame)

    eligible = frame[frame["pitcherRole"].eq("SP") & frame["bbe_allowed"].ge(175)].copy()
    pools = {
        "thunder": sorted(eligible["hr_window_thunder_rate_allowed"].dropna().astype(float).tolist()),
        "xhr": sorted(eligible["adjusted_xhr_proxy_per_bbe_allowed"].dropna().astype(float).tolist()),
        "hrCapable": sorted(eligible["hr_capable_bbe_rate_allowed"].dropna().astype(float).tolist()),
    }

    frame["thunderPercentile"] = frame["hr_window_thunder_rate_allowed"].map(
        lambda value: percentile_from_pool(pools["thunder"], value)
    )
    frame["adjustedXhrPercentile"] = frame["adjusted_xhr_proxy_per_bbe_allowed"].map(
        lambda value: percentile_from_pool(pools["xhr"], value)
    )
    frame["hrCapablePercentile"] = frame["hr_capable_bbe_rate_allowed"].map(
        lambda value: percentile_from_pool(pools["hrCapable"], value)
    )
    frame["stackWatchScore"] = pd.NA
    complete = frame[["thunderPercentile", "adjustedXhrPercentile", "hrCapablePercentile"]].notna().all(axis=1)
    frame.loc[complete, "stackWatchScore"] = (
        frame.loc[complete, "thunderPercentile"] * 0.70
        + frame.loc[complete, "adjustedXhrPercentile"] * 0.20
        + frame.loc[complete, "hrCapablePercentile"] * 0.10
    )
    write_internal_pitcher_components(frame, output_dir)
    return frame, len(eligible)


def score_status(row: pd.Series) -> str:
    if pd.isna(row.get("bbe_allowed")):
        return "No current data"
    has_required_inputs = all(not pd.isna(row.get(column)) for column in REQUIRED_SCORE_COLUMNS)
    if not has_required_inputs:
        return "Missing inputs"
    bbe_allowed = number_or_none(row.get("bbe_allowed")) or 0
    if bbe_allowed < 75:
        return "Very limited sample"
    if bbe_allowed < 175:
        return "Limited sample"
    return "Full score"


def sample_tag(row: pd.Series) -> str:
    return score_status(row)


def number_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def note(row: pd.Series, cooked_cutoff: float) -> str:
    status = row["scoreStatus"]
    if status in {"No current data", "Missing inputs", "Limited sample", "Very limited sample"}:
        pitcher_note = status
    else:
        score = number_or_none(row.get("stackWatchScore"))
        if score is None:
            pitcher_note = "Missing inputs"
        else:
            hdi_value = number_or_none(row.get("current_hdi", row.get("hdi_v1_1_proxy"))) or 0
            thunder_percentile = number_or_none(row.get("thunderPercentile")) or 0
            adjusted_xhr_percentile = number_or_none(row.get("adjustedXhrPercentile")) or 0
            cooked_per_100 = number_or_none(row.get("cooked_per_100_bbe")) or 0
            if score >= 85 and hdi_value >= 125:
                pitcher_note = "HDI backs the signal"
            elif thunder_percentile >= 85:
                pitcher_note = "Attackable thunder profile"
            elif adjusted_xhr_percentile >= 85:
                pitcher_note = "xHR support is there"
            elif cooked_per_100 >= cooked_cutoff and score < 75:
                pitcher_note = "Cooked rate spike"
            else:
                pitcher_note = "Starter workload profile"

    context_notes = []
    lineup_source = row.get("opponentLineupSource")
    avg_lbi = number_or_none(row.get("opponentLineupAvgLbi"))
    if lineup_source == "confirmed":
        context_notes.append("Confirmed lineup")
    elif lineup_source == "team proxy":
        context_notes.append("Team proxy lineup")
    if avg_lbi is not None:
        if avg_lbi >= 115:
            context_notes.append("Strong opponent LBI context")
        elif avg_lbi < 95:
            context_notes.append("Lineup power lighter")
    if row.get("weatherStatus") == "Available":
        if not pd.isna(row.get("windSpeed")):
            context_notes.append("Wind context available")
        if not pd.isna(row.get("precipitationRisk")) and (number_or_none(row.get("precipitationRisk")) or 0) >= 25:
            context_notes.append("Rain risk context available")
    return "; ".join([pitcher_note, *context_notes])


def match_status(row: pd.Series) -> tuple[str, str]:
    if pd.isna(row.get("bbe_allowed")):
        return "noCurrentData", "No current season Statcast BBE sample"
    if bool(row.get("publishedHotDogData")):
        return "publishedHotDogMatch", ""
    bbe_allowed = number_or_none(row.get("bbe_allowed")) or 0
    hr_allowed = number_or_none(row.get("hr_total")) or 0
    if pd.isna(row.get("adjusted_xhr_proxy_per_bbe_allowed")) or pd.isna(row.get("hr_capable_bbe_rate_allowed")):
        return "missingRequiredInputs", "Present in raw Statcast cache but missing HRT-derived Stack Watch components"
    if bbe_allowed < hot_dog.MIN_BBE_ALLOWED or hr_allowed < hot_dog.MIN_HR_ALLOWED:
        return "rawStatcastFallback", "Scored with broader internal HRT lookup; below public Hot Dog qualification"
    return "rawStatcastFallback", "Present in raw Statcast cache and scored with broader internal HRT lookup"


def joined_slate(date: str, data_dir: Path, raw_dir: Path, output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    schedule = fetch_schedule(date, output_dir)
    starters = probable_starters(schedule)
    pitchers, eligible_count = current_pitchers(data_dir, raw_dir, output_dir)
    joined = starters.merge(pitchers, on="pitcherId", how="left", suffixes=("", "_hotDog"))

    eligible_pitchers = pitchers[pitchers["pitcherRole"].eq("SP") & pitchers["bbe_allowed"].ge(175)]
    cooked_cutoff = float(eligible_pitchers["cooked_per_100_bbe"].quantile(0.9)) if not eligible_pitchers.empty else 0
    match_pairs = joined.apply(match_status, axis=1)
    joined["matchStatus"] = match_pairs.map(lambda pair: pair[0])
    joined["unmatchedReason"] = match_pairs.map(lambda pair: pair[1])
    joined["probablePitcherId"] = joined["pitcherId"]
    published_mask = joined["publishedHotDogData"].where(joined["publishedHotDogData"].notna(), False).astype(bool)
    score_available = joined["stackWatchScore"].notna()
    joined["hotDogPitcherId"] = joined["pitcherId"].where(published_mask, pd.NA)
    joined["publishedHotDogMatch"] = published_mask
    joined["rawStatcastFallback"] = joined["matchStatus"].eq("rawStatcastFallback")
    joined["fullScoreAvailable"] = score_available
    joined["noCurrentData"] = joined["matchStatus"].eq("noCurrentData")
    joined["missingRequiredInputs"] = joined["matchStatus"].eq("missingRequiredInputs")
    joined["scoreStatus"] = joined.apply(score_status, axis=1)
    joined["sampleTag"] = joined["scoreStatus"]
    joined = add_context_fields(joined, data_dir, output_dir)
    joined["note"] = joined.apply(lambda row: note(row, cooked_cutoff), axis=1)
    joined["sortBucket"] = joined["scoreStatus"].map(SCORE_STATUS_ORDER).fillna(99).astype(int)

    games = sum(len(date_block.get("games", [])) for date_block in schedule.get("dates", []))
    summary = {
        "date": date,
        "games": games,
        "probableStarterSlots": len(starters),
        "publishedHotDogMatches": int(published_mask.sum()),
        "matchedAnyCurrentData": int(joined["bbe_allowed"].notna().sum()),
        "fullScoreAvailableStarters": int(score_available.sum()),
        "scoreableFullSampleStarters": int(
            (score_available & joined["scoreStatus"].eq("Full score")).sum()
        ),
        "fullSampleEligibleStarters": int(joined["scoreStatus"].eq("Full score").sum()),
        "limitedSampleStarters": int(joined["scoreStatus"].eq("Limited sample").sum()),
        "veryLimitedSampleStarters": int(joined["scoreStatus"].eq("Very limited sample").sum()),
        "missingInputStarters": int(joined["scoreStatus"].eq("Missing inputs").sum()),
        "noDataStarters": int(joined["scoreStatus"].eq("No current data").sum()),
        "rawStatcastFallbackStarters": int(joined["rawStatcastFallback"].sum()),
        "missingRequiredInputStarters": int(joined["missingRequiredInputs"].sum()),
        "publishedHotDogStarters": int(joined["publishedHotDogMatch"].sum()),
        "confirmedLineups": int(joined["opponentLineupSource"].eq("confirmed").sum()),
        "teamProxyLineups": int(joined["opponentLineupSource"].eq("team proxy").sum()),
        "unavailableLineups": int(joined["opponentLineupSource"].eq("unavailable").sum()),
        "parkFactorMatched": int(joined["parkFactorSource"].notna().sum()),
        "parkFactorUnmatched": int(joined["parkFactorSource"].isna().sum()),
        "unmatchedParkVenues": sorted(joined.loc[joined["parkFactorSource"].isna(), "venue"].dropna().unique().tolist()),
        "weatherAvailable": int(joined["weatherStatus"].eq("Available").sum()),
        "weatherUnavailable": int(joined["weatherStatus"].ne("Available").sum()),
        "eligiblePercentilePool": eligible_count,
    }
    return joined, summary


def sorted_slate(joined: pd.DataFrame) -> pd.DataFrame:
    return joined.sort_values(
        ["sortBucket", "stackWatchScore", "pitcher"],
        ascending=[True, False, True],
        na_position="last",
    )


def clean_record(row: pd.Series) -> dict[str, Any]:
    def maybe_float(value: Any, digits: int | None = None) -> float | None:
        if pd.isna(value):
            return None
        number = float(value)
        return round(number, digits) if digits is not None else number

    return {
        "date": row.get("date"),
        "gamePk": int(row["gamePk"]) if not pd.isna(row.get("gamePk")) else None,
        "pitcherId": int(row["pitcherId"]),
        "probablePitcherId": int(row["probablePitcherId"]) if not pd.isna(row.get("probablePitcherId")) else None,
        "hotDogPitcherId": int(row["hotDogPitcherId"]) if not pd.isna(row.get("hotDogPitcherId")) else None,
        "pitcher": row.get("pitcher"),
        "pitcherTeam": row.get("team"),
        "opponentTeam": row.get("opponent"),
        "homeAway": row.get("homeAway"),
        "venue": row.get("venue"),
        "venueId": int(row["venueId"]) if not pd.isna(row.get("venueId")) else None,
        "gameTime": row.get("gameTime"),
        "stackWatchScore": maybe_float(row.get("stackWatchScore"), 1),
        "scoreStatus": row.get("scoreStatus"),
        "sampleTag": row.get("sampleTag"),
        "hrWindowThunderRateAllowed": maybe_float(row.get("hr_window_thunder_rate_allowed"), 4),
        "adjustedXhrPerBbeAllowed": maybe_float(row.get("adjusted_xhr_proxy_per_bbe_allowed"), 4),
        "hrCapableRateAllowed": maybe_float(row.get("hr_capable_bbe_rate_allowed"), 4),
        "hdi": maybe_float(row.get("current_hdi"), 1),
        "cookedPer100Bbe": maybe_float(row.get("cooked_per_100_bbe"), 1),
        "bbeAllowed": maybe_float(row.get("bbe_allowed"), 0),
        "hrAllowed": maybe_float(row.get("hr_total"), 0),
        "opponentLineupSource": row.get("opponentLineupSource"),
        "opponentLineupAvgLbi": maybe_float(row.get("opponentLineupAvgLbi"), 1),
        "opponentLineupTop3Lbi": maybe_float(row.get("opponentLineupTop3Lbi"), 1),
        "opponentLineupLbi120Count": int(row["opponentLineupLbi120Count"]) if not pd.isna(row.get("opponentLineupLbi120Count")) else None,
        "opponentLineupLbi140Count": int(row["opponentLineupLbi140Count"]) if not pd.isna(row.get("opponentLineupLbi140Count")) else None,
        "opponentLineupHrWindowThunderAvg": maybe_float(row.get("opponentLineupHrWindowThunderAvg"), 4),
        "lineupNames": row.get("lineupNames") if isinstance(row.get("lineupNames"), list) else [],
        "parkHrFactor": maybe_float(row.get("parkHrFactor"), 1),
        "parkHrTag": row.get("parkHrTag"),
        "parkCarryFactor": maybe_float(row.get("parkCarryFactor"), 1),
        "parkCarryTag": row.get("parkCarryTag"),
        "parkFactorSource": row.get("parkFactorSource"),
        "weatherStatus": row.get("weatherStatus"),
        "weatherSource": row.get("weatherSource"),
        "temperature": maybe_float(row.get("temperature"), 1),
        "windSpeed": maybe_float(row.get("windSpeed"), 1),
        "windDirection": row.get("windDirection") if not pd.isna(row.get("windDirection")) else None,
        "precipitationRisk": maybe_float(row.get("precipitationRisk"), 3),
        "matchStatus": row.get("matchStatus"),
        "publishedHotDogMatch": bool(row.get("publishedHotDogMatch")),
        "rawStatcastFallback": bool(row.get("rawStatcastFallback")),
        "fullScoreAvailable": bool(row.get("fullScoreAvailable")),
        "noCurrentData": bool(row.get("noCurrentData")),
        "missingRequiredInputs": bool(row.get("missingRequiredInputs")),
        "unmatchedReason": row.get("unmatchedReason") or "",
        "note": row.get("note"),
    }


def write_outputs(joined: pd.DataFrame, summary: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    date = summary["date"]
    csv_path = output_dir / f"stack_watch_{date}.csv"
    json_path = output_dir / f"stack_watch_{date}.json"

    display_columns = [
        "date",
        "gamePk",
        "pitcher",
        "pitcherTeam",
        "opponentTeam",
        "venue",
        "venueId",
        "gameTime",
        "homeAway",
        "stackWatchScore",
        "scoreStatus",
        "sampleTag",
        "bbe_allowed",
        "hr_window_thunder_rate_allowed",
        "adjusted_xhr_proxy_per_bbe_allowed",
        "hr_capable_bbe_rate_allowed",
        "hdi",
        "cooked_per_100_bbe",
        "opponentLineupSource",
        "opponentLineupAvgLbi",
        "opponentLineupTop3Lbi",
        "opponentLineupLbi120Count",
        "opponentLineupLbi140Count",
        "opponentLineupHrWindowThunderAvg",
        "parkHrFactor",
        "parkHrTag",
        "parkCarryFactor",
        "parkCarryTag",
        "parkFactorSource",
        "weatherStatus",
        "weatherSource",
        "temperature",
        "windSpeed",
        "windDirection",
        "precipitationRisk",
        "note",
        "pitcherId",
        "probablePitcherId",
        "hotDogPitcherId",
        "hr_total",
        "lineupNames",
        "matchStatus",
        "publishedHotDogMatch",
        "rawStatcastFallback",
        "fullScoreAvailable",
        "noCurrentData",
        "missingRequiredInputs",
        "unmatchedReason",
    ]
    ordered = sorted_slate(joined)
    export = ordered.rename(columns={"team": "pitcherTeam", "opponent": "opponentTeam", "current_hdi": "hdi"}).copy()
    export["lineupNames"] = export["lineupNames"].map(
        lambda names: "; ".join(names) if isinstance(names, list) else ""
    )
    export[display_columns].to_csv(csv_path, index=False)
    records = [clean_record(row) for _, row in ordered.iterrows()]
    json_path.write_text(json.dumps({"summary": summary, "probableStarters": records}, indent=2) + "\n")
    return csv_path, json_path


def print_report(joined: pd.DataFrame, summary: dict[str, Any], csv_path: Path, json_path: Path) -> None:
    print("Stack Watch probable-starter prototype")
    print(f"Date: {summary['date']}")
    print(
        f"Games: {summary['games']} | probable starter slots: {summary['probableStarterSlots']} | "
        f"published Hot Dog matches: {summary['publishedHotDogMatches']} | any current data: "
        f"{summary['matchedAnyCurrentData']} | full score available: {summary['fullScoreAvailableStarters']} | full-sample eligible: "
        f"{summary['fullSampleEligibleStarters']} | limited sample: {summary['limitedSampleStarters']} | "
        f"very limited: {summary['veryLimitedSampleStarters']} | missing inputs: {summary['missingInputStarters']} | "
        f"no current data: {summary['noDataStarters']}"
    )
    print(
        f"Raw Statcast fallback starters: {summary['rawStatcastFallbackStarters']} | "
        f"missing required inputs: {summary['missingRequiredInputStarters']} | "
        f"published Hot Dog starters: {summary['publishedHotDogStarters']}"
    )
    print(
        f"Lineups: confirmed {summary['confirmedLineups']} | team proxy {summary['teamProxyLineups']} | "
        f"unavailable {summary['unavailableLineups']} | weather unavailable {summary['weatherUnavailable']}"
    )
    print(
        f"Park factors: matched {summary['parkFactorMatched']} | unmatched {summary['parkFactorUnmatched']}"
    )
    print(f"Eligible percentile pool: {summary['eligiblePercentilePool']} SP with BBE >= 175")
    print("\nTop Stack Watch probable starters")
    for _, row in sorted_slate(joined).head(15).iterrows():
        score = row.get("stackWatchScore")
        score_text = "n/a" if pd.isna(score) else f"{score:.1f}"
        thunder = row.get("hr_window_thunder_rate_allowed")
        thunder_text = "n/a" if pd.isna(thunder) else f"{thunder * 100:.1f}%"
        hdi_value = row.get("current_hdi")
        hdi_text = "n/a" if pd.isna(hdi_value) else f"{hdi_value:.1f}"
        bbe = row.get("bbe_allowed")
        bbe_text = "n/a" if pd.isna(bbe) else f"{bbe:.0f}"
        lineup_lbi = row.get("opponentLineupAvgLbi")
        lineup_text = "n/a" if pd.isna(lineup_lbi) else f"{lineup_lbi:.1f}"
        print(
            f"- {row['pitcher']} ({row['team']} {row['homeAway']} vs {row['opponent']}, {row['venue']}): "
            f"Stack {score_text} | Opp LBI {lineup_text} | Thunder {thunder_text} | HDI {hdi_text} | BBE {bbe_text} | "
            f"{row['scoreStatus']} | {row['note']}"
        )
    print(f"\nCSV: {csv_path}")
    print(f"JSON: {json_path}")


def main() -> None:
    args = parse_args()
    joined, summary = joined_slate(args.date, args.data_dir, args.raw_dir, args.output_dir)
    if joined.empty:
        print(f"No probable starters found for {args.date}.", file=sys.stderr)
        sys.exit(1)
    csv_path, json_path = write_outputs(joined, summary, args.output_dir)
    print_report(joined, summary, csv_path, json_path)


if __name__ == "__main__":
    main()
