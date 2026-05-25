#!/usr/bin/env python3
"""Generate weekly Longball Index movement reports from snapshots."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CURRENT_PATH = Path("public/data/hr-distance-latest.json")
DEFAULT_SNAPSHOT_DIR = Path("public/data/snapshots")
DEFAULT_OUTPUT_PATH = Path("public/data/weekly-movers-latest.json")
DEFAULT_REPORT_DIR = Path("content/reports")


@dataclass(frozen=True)
class Snapshot:
    path: Path
    date: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly Longball Index movers from saved snapshots.")
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_PATH, help="Current LBI JSON path.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR, help="Directory for weekly snapshots.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Weekly movers JSON output path.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Generated markdown report directory.")
    parser.add_argument("--season", type=int, help="Season for snapshot filename. Defaults to source metadata or generatedAt year.")
    parser.add_argument("--create-snapshot", action="store_true", help="Save the current leaderboard into the snapshot directory before comparing.")
    parser.add_argument("--current-snapshot", type=Path, help="Use a specific current snapshot instead of deriving one from --current.")
    parser.add_argument("--previous-snapshot", type=Path, help="Use a specific previous snapshot instead of finding the prior Monday.")
    parser.add_argument("--limit", type=int, default=10, help="Number of players per movers list.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_generated_date(payload: dict[str, Any]) -> datetime:
    value = str(payload.get("generatedAt") or "")
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def season_from_payload(payload: dict[str, Any], fallback_date: datetime) -> int:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    season = source.get("season")
    try:
        return int(season)
    except (TypeError, ValueError):
        return fallback_date.year


def snapshot_name(season: int, generated_date: datetime) -> str:
    return f"lbi-{season}-{generated_date.date().isoformat()}.json"


def create_snapshot(current_path: Path, snapshot_dir: Path, season: int, generated_date: datetime) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    destination = snapshot_dir / snapshot_name(season, generated_date)
    shutil.copyfile(current_path, destination)
    print(f"Saved current snapshot: {destination}")
    return destination


def snapshot_from_path(path: Path) -> Snapshot | None:
    parts = path.stem.split("-")
    if len(parts) < 4 or parts[0] != "lbi":
        return None
    try:
        date_text = "-".join(parts[-3:])
        parsed = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return Snapshot(path=path, date=parsed)


def find_current_snapshot(snapshot_dir: Path, current_path: Path, season: int, generated_date: datetime) -> Path:
    expected = snapshot_dir / snapshot_name(season, generated_date)
    if expected.exists():
        return expected
    return current_path


def find_previous_monday_snapshot(snapshot_dir: Path, current_snapshot: Path, current_date: datetime) -> Path | None:
    snapshots: list[Snapshot] = []
    for path in snapshot_dir.glob("lbi-*.json"):
        if path.resolve() == current_snapshot.resolve():
            continue
        snapshot = snapshot_from_path(path)
        if snapshot and snapshot.date.date() < current_date.date() and snapshot.date.weekday() == 0:
            snapshots.append(snapshot)

    if not snapshots:
        return None

    return max(snapshots, key=lambda item: item.date).path


def stable_key(player: dict[str, Any]) -> str:
    player_id = player.get("batter") or player.get("playerId") or player.get("player_id")
    if player_id not in (None, ""):
        return f"id:{player_id}"
    return f"name:{player.get('player', '')}|{player.get('team', '')}".lower()


def ranked_players(payload: dict[str, Any]) -> list[dict[str, Any]]:
    players = payload.get("players")
    if not isinstance(players, list):
        raise RuntimeError("Snapshot is missing a players array.")

    ranked = []
    for index, player in enumerate(players, start=1):
        row = dict(player)
        row["rank"] = index
        row["qualified"] = True
        ranked.append(row)
    return ranked


def number(value: Any, default: float = 0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(round(number(value, default)))


def movement_note(row: dict[str, Any]) -> str:
    lbi_change = row["lbiChange"]
    rank_change = row["rankChange"]
    parts = []
    if abs(lbi_change) >= 10:
        direction = "up" if lbi_change > 0 else "down"
        parts.append(f"LBI {direction} {abs(lbi_change):.1f}")
    if abs(rank_change) >= 10:
        direction = "climbed" if rank_change > 0 else "fell"
        parts.append(f"{direction} {abs(rank_change)} spots")
    if row["barrelRateChange"] >= 0.03:
        parts.append("barrels trending up")
    if row["xhrPerBbeChange"] >= 0.015:
        parts.append("xHR/BBE jump")
    return "; ".join(parts) or "Notable week-over-week movement"


def movement_row(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    row = {
        "player": current.get("player", ""),
        "team": current.get("team", ""),
        "playerId": current.get("batter") or current.get("playerId") or current.get("player_id"),
        "currentLbi": round(number(current.get("longballIndex")), 1),
        "previousLbi": round(number(previous.get("longballIndex")), 1),
        "lbiChange": round(number(current.get("longballIndex")) - number(previous.get("longballIndex")), 1),
        "currentRank": integer(current.get("rank")),
        "previousRank": integer(previous.get("rank")),
        "rankChange": integer(previous.get("rank")) - integer(current.get("rank")),
        "currentBbe": integer(current.get("bbe")),
        "previousBbe": integer(previous.get("bbe")),
        "bbeChange": integer(current.get("bbe")) - integer(previous.get("bbe")),
        "xhrPerBbeChange": round(number(current.get("xhrPerBbe")) - number(previous.get("xhrPerBbe")), 4),
        "barrelRateChange": round(number(current.get("barrelRate")) - number(previous.get("barrelRate")), 4),
        "hardHitRateChange": round(number(current.get("hardHitRate")) - number(previous.get("hardHitRate")), 4),
        "hrChange": integer(current.get("hr")) - integer(previous.get("hr")),
    }
    row["note"] = movement_note(row)
    return row


def compare_snapshots(current_payload: dict[str, Any], previous_payload: dict[str, Any], limit: int) -> dict[str, list[dict[str, Any]]]:
    current_players = ranked_players(current_payload)
    previous_players = ranked_players(previous_payload)
    previous_by_key = {stable_key(player): player for player in previous_players}
    previous_top25 = {stable_key(player) for player in previous_players[:25]}

    shared_rows = []
    new_qualifiers = []
    new_top25 = []

    for current in current_players:
        key = stable_key(current)
        previous = previous_by_key.get(key)
        if previous is None:
            new_row = {
                "player": current.get("player", ""),
                "team": current.get("team", ""),
                "playerId": current.get("batter") or current.get("playerId") or current.get("player_id"),
                "currentLbi": round(number(current.get("longballIndex")), 1),
                "previousLbi": None,
                "lbiChange": None,
                "currentRank": integer(current.get("rank")),
                "previousRank": None,
                "rankChange": None,
                "currentBbe": integer(current.get("bbe")),
                "previousBbe": None,
                "bbeChange": None,
                "xhrPerBbeChange": None,
                "barrelRateChange": None,
                "hardHitRateChange": None,
                "hrChange": None,
                "note": "Newly qualified for the LBI leaderboard",
            }
            new_qualifiers.append(new_row)
            if integer(current.get("rank")) <= 25:
                new_top25.append({**new_row, "note": "New Top 25 entrant"})
            continue

        row = movement_row(current, previous)
        if integer(current.get("rank")) <= 25 and key not in previous_top25:
            new_top25.append({**row, "note": "Entered the Top 25"})

        if row["bbeChange"] >= 10:
            shared_rows.append(row)

    return {
        "biggestLbiRisers": sorted(shared_rows, key=lambda row: (-row["lbiChange"], row["player"]))[:limit],
        "biggestLbiFallers": sorted(shared_rows, key=lambda row: (row["lbiChange"], row["player"]))[:limit],
        "biggestRankClimbers": sorted(shared_rows, key=lambda row: (-row["rankChange"], row["player"]))[:limit],
        "biggestRankFallers": sorted(shared_rows, key=lambda row: (row["rankChange"], row["player"]))[:limit],
        "newTop25Entrants": sorted(new_top25, key=lambda row: (row["currentRank"] or 9999, row["player"]))[:limit],
        "newQualifiers": sorted(new_qualifiers, key=lambda row: (row["currentRank"] or 9999, row["player"]))[:limit],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]], include_previous: bool = True) -> str:
    if not rows:
        return "_None this week._\n"

    header = "| Player | Team | LBI | Change | Rank | Note |\n|---|---:|---:|---:|---:|---|\n"
    body = []
    for row in rows:
        change = row.get("lbiChange")
        change_text = "new" if change is None else f"{change:+.1f}"
        previous = row.get("previousRank")
        rank_text = str(row.get("currentRank"))
        if include_previous and previous is not None:
            rank_text = f"{previous} -> {row.get('currentRank')}"
        body.append(
            f"| {row.get('player', '')} | {row.get('team', '')} | {row.get('currentLbi', '')} | "
            f"{change_text} | {rank_text} | {row.get('note', '')} |"
        )
    return header + "\n".join(body) + "\n"


def write_markdown_report(report_dir: Path, current_date: datetime, movers: dict[str, list[dict[str, Any]]], current_snapshot: Path, previous_snapshot: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{current_date.date().isoformat()}-weekly-longball-movers.md"
    content = f"""---
title: Monday Morning Movement Report
date: {current_date.date().isoformat()}
description: Weekly Longball Index movers generated from saved leaderboard snapshots.
---

# Monday Morning Movement Report

Generated from weekly LBI snapshots:

- Current: `{current_snapshot.as_posix()}`
- Previous: `{previous_snapshot.as_posix()}`

## Biggest LBI Risers

{markdown_table(movers["biggestLbiRisers"])}
## Biggest LBI Fallers

{markdown_table(movers["biggestLbiFallers"])}
## New Top 25 Entrants

{markdown_table(movers["newTop25Entrants"])}
## New Qualifiers

{markdown_table(movers["newQualifiers"], include_previous=False)}
"""
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    current_payload = load_json(args.current)
    generated_date = parse_generated_date(current_payload)
    season = args.season or season_from_payload(current_payload, generated_date)

    current_snapshot = args.current_snapshot
    if args.create_snapshot:
        current_snapshot = create_snapshot(args.current, args.snapshot_dir, season, generated_date)
    if current_snapshot is None:
        current_snapshot = find_current_snapshot(args.snapshot_dir, args.current, season, generated_date)

    previous_snapshot = args.previous_snapshot or find_previous_monday_snapshot(
        args.snapshot_dir,
        current_snapshot,
        parse_generated_date(load_json(current_snapshot)),
    )
    if previous_snapshot is None:
        print("No previous snapshot found; create first weekly snapshot and rerun next week.")
        return

    current_snapshot_payload = load_json(current_snapshot)
    previous_snapshot_payload = load_json(previous_snapshot)
    movers = compare_snapshots(current_snapshot_payload, previous_snapshot_payload, args.limit)
    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "currentSnapshot": current_snapshot.as_posix(),
        "previousSnapshot": previous_snapshot.as_posix(),
        **movers,
    }

    write_json(args.output, output)
    report_path = write_markdown_report(
        args.report_dir,
        parse_generated_date(current_snapshot_payload),
        movers,
        current_snapshot,
        previous_snapshot,
    )
    print(f"Wrote weekly movers JSON: {args.output}")
    print(f"Wrote markdown draft: {report_path}")


if __name__ == "__main__":
    main()
