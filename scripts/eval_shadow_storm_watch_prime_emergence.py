#!/usr/bin/env python3
"""Evaluate retained Storm Watch Prime Emergence shadow snapshots.

Given two snapshot dates, this script takes the Prime Emergence watchlists from
the earlier snapshot and measures forward production through the later snapshot.
It is internal-only verdict tooling; it does not change public data or formulas.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SNAPSHOT_DIR = Path("data/shadow/storm_watch_prime_emergence")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Storm Watch Prime Emergence shadow snapshots.")
    parser.add_argument("start_date", help="Earlier snapshot date YYYY-MM-DD.")
    parser.add_argument("end_date", help="Later snapshot date YYYY-MM-DD.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR, help="Shadow snapshot directory.")
    return parser.parse_args()


def load_snapshot(snapshot_dir: Path, snapshot_date: str) -> dict[str, Any]:
    path = snapshot_dir / f"snapshot_{snapshot_date}.json"
    with path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    snapshot["_path"] = str(path)
    return snapshot


def rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value * 100:.2f}%"


def pace_600(value: float | None) -> str:
    return "NA" if value is None else f"{value * 600:.1f}"


def evaluate_watchlist(start: dict[str, Any], end: dict[str, Any], watchlist_key: str) -> dict[str, Any]:
    start_players = {int(player["playerId"]): player for player in start.get("players", [])}
    end_players = {int(player["playerId"]): player for player in end.get("players", [])}
    entries = start.get("watchlists", {}).get(watchlist_key, [])
    rows = []
    missing = []
    total_hr = 0
    total_pa = 0
    total_bbe = 0
    for entry in entries:
        player_id = int(entry["playerId"])
        start_row = start_players.get(player_id)
        end_row = end_players.get(player_id)
        if not start_row or not end_row:
            missing.append(entry)
            continue
        forward_hr = max(int(end_row.get("hr", 0)) - int(start_row.get("hr", 0)), 0)
        forward_pa = max(int(end_row.get("pa", 0)) - int(start_row.get("pa", 0)), 0)
        forward_bbe = max(int(end_row.get("bbe", 0)) - int(start_row.get("bbe", 0)), 0)
        total_hr += forward_hr
        total_pa += forward_pa
        total_bbe += forward_bbe
        rows.append(
            {
                "playerId": player_id,
                "player": entry["player"],
                "team": entry["team"],
                "age": entry.get("age"),
                "priorStatus": entry.get("priorStatus"),
                "startRank": entry.get("primeEmergenceRank") or entry.get("stormWatchRank"),
                "stormWatchB6": entry.get("stormWatchB6"),
                "pulledAirborneConfirmation": entry.get("pulledAirborneConfirmation"),
                "forwardHr": forward_hr,
                "forwardPa": forward_pa,
                "forwardBbe": forward_bbe,
                "forwardHrPerPa": rate(forward_hr, forward_pa),
                "forwardHrPerBbe": rate(forward_hr, forward_bbe),
            }
        )
    return {
        "watchlist": watchlist_key,
        "count": len(entries),
        "matched": len(rows),
        "missing": missing,
        "totalForwardHr": total_hr,
        "totalForwardPa": total_pa,
        "totalForwardBbe": total_bbe,
        "forwardHrPerPa": rate(total_hr, total_pa),
        "forwardHrPerBbe": rate(total_hr, total_bbe),
        "players": rows,
    }


def print_result(result: dict[str, Any]) -> None:
    print(f"\n{result['watchlist']}")
    print(f"Matched: {result['matched']}/{result['count']}")
    print(f"Forward HR/PA: {pct(result['forwardHrPerPa'])} | HR/600: {pace_600(result['forwardHrPerPa'])}")
    print(f"Forward HR/BBE: {pct(result['forwardHrPerBbe'])}")
    print(f"Totals: {result['totalForwardHr']} HR / {result['totalForwardPa']} PA / {result['totalForwardBbe']} BBE")
    for row in sorted(result["players"], key=lambda item: (-(item["forwardHrPerPa"] or -1), item["player"])):
        age = "NA" if row["age"] is None else f"{row['age']:.1f}"
        print(
            f"{row['player']:<24} {row['team']:<3} | age {age} | {row['priorStatus']:<11} | "
            f"start rank {row['startRank']} | B6 {row['stormWatchB6']:.1f} | "
            f"{row['forwardHr']} HR / {row['forwardPa']} PA / {row['forwardBbe']} BBE | "
            f"HR/600 {pace_600(row['forwardHrPerPa'])}"
        )
    if result["missing"]:
        print("Missing in later snapshot:")
        for row in result["missing"]:
            print(f"- {row['player']} ({row['team']})")


def main() -> None:
    args = parse_args()
    start = load_snapshot(args.snapshot_dir, args.start_date)
    end = load_snapshot(args.snapshot_dir, args.end_date)
    print(f"Storm Watch Prime Emergence shadow evaluation: {args.start_date} -> {args.end_date}")
    print(f"Start: {start['_path']}")
    print(f"End: {end['_path']}")
    for key in [
        "primeEmergenceB6",
        "primeEmergenceB6PlusPulledAirborneConfirmation",
        "allPoolB6Reference",
    ]:
        print_result(evaluate_watchlist(start, end, key))
    print("\nVerdict prompt")
    print("Primary read: Prime Emergence B6 forward HR/PA and HR/600.")
    print("Confirmation read: compare B6 list to B6 + pulled-airborne confirmation; use pulled-air as tiebreaker only if it improves the live evidence.")


if __name__ == "__main__":
    main()
