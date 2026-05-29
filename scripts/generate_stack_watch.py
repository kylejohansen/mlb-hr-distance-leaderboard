#!/usr/bin/env python3
"""Generate an internal single-day Stack Watch probable-starter prototype.

Stack Watch is an internal daily probable-starter/slate prototype, not a public
formula. It pulls one MLB schedule date at a time and includes every probable
starter slot returned by the schedule feed.

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
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd

import diagnose_hot_dog_index_vnext as hdi
import generate_hot_dog_stand as hot_dog


DATA_DIR = Path("public/data")
RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("/tmp")


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
            venue = (game.get("venue") or {}).get("name", "")
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
                        "gamePk": game.get("gamePk"),
                        "pitcherId": int(pitcher["id"]),
                        "pitcher": pitcher.get("fullName", ""),
                        "team": team.get("abbreviation", ""),
                        "opponent": opponent_team.get("abbreviation", ""),
                        "homeAway": home_away,
                        "venue": venue,
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


def sample_tag(row: pd.Series) -> str:
    if pd.isna(row.get("bbe_allowed")):
        return "No current data"
    if row.get("pitcherRole") != "SP":
        return f"Role tag: {row.get('pitcherRole') or 'unknown'}"
    if row["bbe_allowed"] < 75:
        return "Very limited sample"
    if row["bbe_allowed"] < 175:
        return "Limited sample"
    return "Eligible"


def number_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def note(row: pd.Series, cooked_cutoff: float) -> str:
    tag = row["sampleTag"]
    if tag != "Eligible":
        return tag
    score = number_or_none(row.get("stackWatchScore"))
    if score is None:
        return "Incomplete Stack Watch inputs"
    hdi_value = number_or_none(row.get("current_hdi", row.get("hdi_v1_1_proxy"))) or 0
    thunder_percentile = number_or_none(row.get("thunderPercentile")) or 0
    adjusted_xhr_percentile = number_or_none(row.get("adjustedXhrPercentile")) or 0
    cooked_per_100 = number_or_none(row.get("cooked_per_100_bbe")) or 0
    if score >= 85 and hdi_value >= 125:
        return "HDI backs the attack signal"
    if thunder_percentile >= 85:
        return "Attackable thunder profile"
    if adjusted_xhr_percentile >= 85:
        return "xHR support is there"
    if cooked_per_100 >= cooked_cutoff and score < 75:
        return "Cooked rate spike"
    return "Starter workload profile"


def match_status(row: pd.Series) -> tuple[str, str]:
    if pd.isna(row.get("bbe_allowed")):
        return "noCurrentData", "No current season Statcast BBE sample"
    if bool(row.get("publishedHotDogData")):
        return "publishedHotDogMatch", ""
    bbe_allowed = number_or_none(row.get("bbe_allowed")) or 0
    hr_allowed = number_or_none(row.get("hr_total")) or 0
    if bbe_allowed < hot_dog.MIN_BBE_ALLOWED or hr_allowed < hot_dog.MIN_HR_ALLOWED:
        return "rawStatcastFallback", "Present in raw Statcast cache but below public Hot Dog qualification"
    if pd.isna(row.get("adjusted_xhr_proxy_per_bbe_allowed")) or pd.isna(row.get("hr_capable_bbe_rate_allowed")):
        return "missingRequiredInputs", "Present in raw Statcast cache but missing HRT-derived Stack Watch components"
    return "rawStatcastFallback", "Present in raw Statcast cache and scored with broader internal HRT lookup"


def joined_slate(date: str, data_dir: Path, raw_dir: Path, output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    schedule = fetch_schedule(date, output_dir)
    starters = probable_starters(schedule)
    pitchers, eligible_count = current_pitchers(data_dir, raw_dir, output_dir)
    joined = starters.merge(pitchers, on="pitcherId", how="left", suffixes=("", "_hotDog"))

    eligible_pitchers = pitchers[pitchers["pitcherRole"].eq("SP") & pitchers["bbe_allowed"].ge(175)]
    cooked_cutoff = float(eligible_pitchers["cooked_per_100_bbe"].quantile(0.9)) if not eligible_pitchers.empty else 0
    joined["sampleTag"] = joined.apply(sample_tag, axis=1)
    joined["note"] = joined.apply(lambda row: note(row, cooked_cutoff), axis=1)
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

    games = sum(len(date_block.get("games", [])) for date_block in schedule.get("dates", []))
    summary = {
        "date": date,
        "games": games,
        "probableStarterSlots": len(starters),
        "publishedHotDogMatches": int(published_mask.sum()),
        "matchedAnyCurrentData": int(joined["bbe_allowed"].notna().sum()),
        "fullScoreAvailableStarters": int(score_available.sum()),
        "scoreableFullSampleStarters": int(
            (score_available & joined["sampleTag"].eq("Eligible")).sum()
        ),
        "fullSampleEligibleStarters": int(joined["sampleTag"].eq("Eligible").sum()),
        "limitedSampleStarters": int(joined["sampleTag"].eq("Limited sample").sum()),
        "veryLimitedSampleStarters": int(joined["sampleTag"].eq("Very limited sample").sum()),
        "noDataStarters": int(joined["sampleTag"].eq("No current data").sum()),
        "rawStatcastFallbackStarters": int(joined["rawStatcastFallback"].sum()),
        "missingRequiredInputStarters": int(joined["missingRequiredInputs"].sum()),
        "publishedHotDogStarters": int(joined["publishedHotDogMatch"].sum()),
        "eligiblePercentilePool": eligible_count,
    }
    return joined, summary


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
        "team": row.get("team"),
        "opponent": row.get("opponent"),
        "homeAway": row.get("homeAway"),
        "venue": row.get("venue"),
        "stackWatchScore": maybe_float(row.get("stackWatchScore"), 1),
        "hrWindowThunderRateAllowed": maybe_float(row.get("hr_window_thunder_rate_allowed"), 4),
        "adjustedXhrPerBbeAllowed": maybe_float(row.get("adjusted_xhr_proxy_per_bbe_allowed"), 4),
        "hrCapableRateAllowed": maybe_float(row.get("hr_capable_bbe_rate_allowed"), 4),
        "hotDogIndex": maybe_float(row.get("current_hdi"), 1),
        "cookedPer100Bbe": maybe_float(row.get("cooked_per_100_bbe"), 1),
        "bbeAllowed": maybe_float(row.get("bbe_allowed"), 0),
        "hrAllowed": maybe_float(row.get("hr_total"), 0),
        "sampleTag": row.get("sampleTag"),
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
        "pitcherId",
        "probablePitcherId",
        "hotDogPitcherId",
        "pitcher",
        "team",
        "opponent",
        "homeAway",
        "venue",
        "stackWatchScore",
        "hr_window_thunder_rate_allowed",
        "adjusted_xhr_proxy_per_bbe_allowed",
        "hr_capable_bbe_rate_allowed",
        "current_hdi",
        "cooked_per_100_bbe",
        "bbe_allowed",
        "hr_total",
        "matchStatus",
        "publishedHotDogMatch",
        "rawStatcastFallback",
        "fullScoreAvailable",
        "noCurrentData",
        "missingRequiredInputs",
        "sampleTag",
        "unmatchedReason",
        "note",
    ]
    joined.sort_values("stackWatchScore", ascending=False, na_position="last")[display_columns].to_csv(
        csv_path, index=False
    )
    records = [clean_record(row) for _, row in joined.sort_values("stackWatchScore", ascending=False).iterrows()]
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
        f"very limited: {summary['veryLimitedSampleStarters']} | no current data: {summary['noDataStarters']}"
    )
    print(
        f"Raw Statcast fallback starters: {summary['rawStatcastFallbackStarters']} | "
        f"missing required inputs: {summary['missingRequiredInputStarters']} | "
        f"published Hot Dog starters: {summary['publishedHotDogStarters']}"
    )
    print(f"Eligible percentile pool: {summary['eligiblePercentilePool']} SP with BBE >= 175")
    print("\nTop Stack Watch probable starters")
    for _, row in joined.sort_values("stackWatchScore", ascending=False, na_position="last").head(15).iterrows():
        score = row.get("stackWatchScore")
        score_text = "n/a" if pd.isna(score) else f"{score:.1f}"
        thunder = row.get("hr_window_thunder_rate_allowed")
        thunder_text = "n/a" if pd.isna(thunder) else f"{thunder * 100:.1f}%"
        hdi_value = row.get("current_hdi")
        hdi_text = "n/a" if pd.isna(hdi_value) else f"{hdi_value:.1f}"
        bbe = row.get("bbe_allowed")
        bbe_text = "n/a" if pd.isna(bbe) else f"{bbe:.0f}"
        print(
            f"- {row['pitcher']} ({row['team']} {row['homeAway']} vs {row['opponent']}, {row['venue']}): "
            f"Stack {score_text} | Thunder {thunder_text} | HDI {hdi_text} | BBE {bbe_text} | "
            f"{row['sampleTag']} | {row['note']}"
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
