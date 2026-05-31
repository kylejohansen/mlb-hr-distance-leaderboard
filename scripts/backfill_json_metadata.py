#!/usr/bin/env python3
"""Backfill self-describing metadata into existing static JSON files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path("public/data")
LBI_VERSION = "1.3"
SITE_METADATA = {
    "name": "The Long Ball",
    "url": "https://thelongball.app",
    "tagline": "Digging the data behind the distance.",
}
LBI_FIELD_METADATA = {
    "player": "Hitter display name.",
    "team": "Most recent batting team inferred from Statcast context.",
    "bbe": "Batted-ball events in the cached Statcast sample.",
    "hr": "Actual home runs in the cached Statcast sample.",
    "longballIndex": "LBI v1.3 plus-style score for stadium-neutral home-run contact quality. 100 is league average among qualified hitters.",
    "xhr": "Adjusted expected home runs from Baseball Savant Home Run Tracker.",
    "xhrPerBbe": "Adjusted expected home runs per batted-ball event.",
    "barrelRate": "Share of batted balls classified as barrels.",
    "hrWindowThunderBbe": "Count of batted balls hit 105 mph or harder with launch angle between 25 and 40 degrees.",
    "hrWindowThunderRate": "Share of batted balls hit 105 mph or harder with launch angle between 25 and 40 degrees. LBI v1.3 component.",
    "hardHitRate": "Share of batted balls hit 95 mph or harder.",
    "avgDistanceOnBarrels": "Average projected distance on barreled batted balls. Reference stat only, not part of LBI v1.3.",
    "pullAirRate": "Pull Air percentage from Baseball Savant's batted-ball leaderboard. Reference stat only.",
    "sweetSpotRate": "Share of batted balls launched between 8 and 32 degrees. Reference stat only.",
    "actualDoubterHr": "Actual home runs classified as Doubters by Home Run Tracker detail data.",
    "cheapieRate": "Actual Doubter HR divided by actual HR total.",
    "dailyFeatures": "Latest-date Daily Dong, Hot Dog Robbery, and Cheapest Dong event objects.",
}
LBI_SOURCE_NOTES = (
    "Uses public Statcast pitch data from pybaseball, Baseball Savant Home Run Tracker "
    "Adjusted mode, and Baseball Savant batted-ball leaderboard fields. The frontend reads "
    "this precomputed static JSON and never queries Statcast directly."
)
HOT_DOG_SOURCE_NOTES = (
    "Uses public Statcast pitch data and Baseball Savant Home Run Tracker pitcher aggregates. "
    "The frontend reads this precomputed static JSON and never queries Statcast directly."
)
DAILY_FEATURE_FIELDS = {
    "gameDate": "Latest game date represented by the daily feature row.",
    "dailyDong": "The day's loudest actual home run.",
    "hotDogRobbery": "The day's strongest HR-capable batted ball that stayed in the yard.",
    "cheapestDong": "The day's flimsiest actual home run that still counted.",
}
HOT_DOG_VERSION = "1.1"
HOT_DOG_FIELD_METADATA = {
    "pitcher": "Pitcher display name.",
    "team": "Pitcher's team when reliably available; otherwise an em dash.",
    "hotDogIndex": "HDI v1.1 plus-style pitcher score for total longball damage allowed.",
    "hdiVersion": "Hot Dog Index formula version used for this pitcher row.",
    "gettingCookedPer100Bbe": "Premium longball damage served per 100 batted balls in play.",
    "cookedPer100Bbe": "Backward-compatible alias for Getting Cooked.",
    "cookedPlus": "Internal normalized Getting Cooked index, with 100 equal to league average among qualified pitchers.",
    "legacyCooked": "Previous Cooked calculation preserved for backward compatibility only.",
    "totalBbeAllowed": "Total batted-ball events allowed in the cached Statcast sample.",
    "hrCapableBbeAllowed": "Batted balls allowed that Baseball Savant classifies as having home-run potential in at least one MLB park.",
    "hrWindowThunderBbeAllowed": "Batted balls allowed at 105 mph or harder with launch angle between 25 and 40 degrees.",
    "hrWindowThunderRateAllowed": "Share of BBE allowed at 105 mph or harder with launch angle between 25 and 40 degrees. HDI v1.1 component.",
    "noDoubtersAllowed": "HR-capable batted balls allowed that would clear all 30 MLB parks.",
    "mostlyGoneAllowed": "HR-capable batted balls allowed that would clear many parks, but not all.",
    "doubtersAllowed": "HR-capable batted balls allowed that would clear only a small number of parks.",
    "avgExitVelocityAllowed": "Average exit velocity allowed on HR-capable contact when available.",
    "avgDistanceAllowed": "Average projected distance allowed on HR-capable contact when available. Reference stat only, not part of HDI v1.1.",
    "maxExitVelocityAllowed": "Hardest HR-capable contact allowed.",
    "maxDistanceAllowed": "Longest HR-capable contact allowed.",
    "meatballPitchesThrown": "Heart-zone pitches below the pitcher's 25th-percentile velocity for that pitch type, with the pitch-type sample safeguard applied.",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_if_changed(path: Path, payload: dict[str, Any], original: dict[str, Any]) -> bool:
    if payload == original:
        return False
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


def ordered_payload(metadata: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    if "generatedAt" in payload:
        ordered["generatedAt"] = payload["generatedAt"]
    for key, value in metadata.items():
        ordered[key] = payload.get(key, value)
    for key, value in payload.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def season_from_path(path: Path, payload: dict[str, Any]) -> int | None:
    if isinstance(payload.get("season"), int):
        return payload["season"]
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    try:
        return int(source.get("season"))
    except (TypeError, ValueError):
        pass
    match = re.search(r"(20\d{2})", path.name)
    return int(match.group(1)) if match else None


def backfill_lbi(path: Path) -> bool:
    original = read_json(path)
    season = season_from_path(path, original)
    if season is None:
        return False
    metadata = {
        "site": SITE_METADATA,
        "dataset": "Longball Index",
        "season": season,
        "description": "Stadium-neutral home-run quality leaderboard for qualified MLB hitters.",
        "methodologyVersion": f"LBI v{LBI_VERSION}",
        "sourceNotes": LBI_SOURCE_NOTES,
        "fields": LBI_FIELD_METADATA,
    }
    payload = ordered_payload(metadata, original)
    return write_json_if_changed(path, payload, original)


def backfill_hot_dog(path: Path) -> bool:
    original = read_json(path)
    season = season_from_path(path, original)
    if season is None:
        return False
    metadata = {
        "site": SITE_METADATA,
        "dataset": "Hot Dog Index",
        "season": season,
        "description": "Pitcher-facing longball damage leaderboard for The Hot Dog Stand.",
        "methodologyVersion": f"Hot Dog Index v{HOT_DOG_VERSION}",
        "sourceNotes": HOT_DOG_SOURCE_NOTES,
        "fields": HOT_DOG_FIELD_METADATA,
    }
    payload = ordered_payload(metadata, original)
    return write_json_if_changed(path, payload, original)


def backfill_daily_features(path: Path) -> bool:
    original = read_json(path)
    season = season_from_path(path, original)
    if season is None:
        return False
    metadata = {
        "site": SITE_METADATA,
        "dataset": "Daily Longball Features",
        "season": season,
        "description": "Daily Dong, Hot Dog Robbery, and Cheapest Dong selections by game date.",
        "methodologyVersion": "Daily Features v1.0",
        "sourceNotes": "Derived from the same Statcast and Baseball Savant Home Run Tracker event joins used by the Longball Index data job.",
        "fields": DAILY_FEATURE_FIELDS,
    }
    payload = ordered_payload(metadata, original)
    return write_json_if_changed(path, payload, original)


def main() -> None:
    changed: list[Path] = []
    for path in sorted(DATA_DIR.glob("longball-index-*.json")):
        if backfill_lbi(path):
            changed.append(path)
    for path in sorted((DATA_DIR / "snapshots").glob("lbi-*.json")):
        if backfill_lbi(path):
            changed.append(path)
    for path in [DATA_DIR / "hr-distance-latest.json"]:
        if path.exists() and backfill_lbi(path):
            changed.append(path)
    for path in sorted(DATA_DIR.glob("hot-dog-*.json")):
        if backfill_hot_dog(path):
            changed.append(path)
    for path in sorted(DATA_DIR.glob("daily-features-*.json")):
        if backfill_daily_features(path):
            changed.append(path)

    if changed:
        print("Updated metadata:")
        for path in changed:
            print(f"- {path}")
    else:
        print("All known JSON feeds already include self-describing metadata.")


if __name__ == "__main__":
    main()
