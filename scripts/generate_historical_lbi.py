#!/usr/bin/env python3
"""Generate historical Longball Index JSON files.

Historical LBI runs are manual by design. The scheduled GitHub Action should
continue refreshing only the current-season/latest files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate historical Longball Index seasons.")
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--min-hr", type=int, default=1)
    parser.add_argument("--force", action="store_true", help="Regenerate even if the output JSON already exists.")
    return parser.parse_args()


def run_season(season: int, min_hr: int, force: bool) -> dict[str, object]:
    output = Path(f"public/data/longball-index-{season}.json")
    raw_cache = Path(f"data/raw/statcast-bbe-events-{season}.csv")

    if output.exists() and not force:
        print(f"Skipping {season}: {output} already exists. Use --force to regenerate.")
    else:
        command = [
            sys.executable,
            "scripts/generate_hr_distance.py",
            "--season",
            str(season),
            "--min-hr",
            str(min_hr),
            "--raw-cache",
            str(raw_cache),
            "--output",
            str(output),
            "--start-date",
            f"{season}-03-01",
            "--end-date",
            f"{season}-11-30",
            "--skip-heart-zones",
        ]
        print(f"\n=== Generating {season} Longball Index ===")
        subprocess.run(command, check=True)

    payload = json.loads(output.read_text(encoding="utf-8"))
    players = payload.get("players", [])
    source = payload.get("source", {})
    return {
        "season": season,
        "players": len(players),
        "missingHomeRunTracker": source.get("homeRunTrackerMissingPlayers"),
        "file": str(output),
        "sizeBytes": output.stat().st_size,
        "top10": [
            {
                "rank": index,
                "player": player.get("player"),
                "team": player.get("team"),
                "longballIndex": player.get("longballIndex"),
            }
            for index, player in enumerate(players[:10], start=1)
        ],
    }


def main() -> None:
    args = parse_args()
    summaries = [run_season(season, args.min_hr, args.force) for season in args.seasons]

    print("\n=== Historical LBI Summary ===")
    for summary in summaries:
        size_kb = summary["sizeBytes"] / 1024
        print(
            f"{summary['season']}: {summary['players']} qualified players, "
            f"{summary['missingHomeRunTracker']} missing HRT matches, {size_kb:.1f} KB"
        )
        for player in summary["top10"]:
            print(
                f"  {player['rank']:2}. {player['player']} ({player['team']}) "
                f"LBI {player['longballIndex']}"
            )


if __name__ == "__main__":
    main()
