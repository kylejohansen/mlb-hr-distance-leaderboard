#!/usr/bin/env python3
"""Create date-stamped Tale of the Tape JSON files from daily feature archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATA_DIR = Path("public/data")
OUTPUT_DIR = DATA_DIR / "tale-of-the-tape"
SITE_METADATA = {
    "name": "The Long Ball",
    "url": "https://thelongball.app",
    "tagline": "Digging the data behind the distance.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill date-stamped Tale of the Tape archives.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def infer_season(path: Path, payload: dict[str, Any], event: dict[str, Any]) -> int | None:
    if isinstance(payload.get("season"), int):
        return payload["season"]
    game_date = str(event.get("gameDate") or "")
    if len(game_date) >= 4 and game_date[:4].isdigit():
        return int(game_date[:4])
    digits = "".join(character for character in path.stem if character.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else None


def event_payload(event: dict[str, Any], season: int, generated_at: str, source_archive: Path) -> dict[str, Any]:
    return {
        "generatedAt": generated_at,
        "site": SITE_METADATA,
        "dataset": "Tale of the Tape Daily Features",
        "season": season,
        "gameDate": event.get("gameDate"),
        "description": "Date-stamped Daily Dong, Hot Dog Robbery, and Cheapest Dong selections.",
        "methodologyVersion": "Daily Features v1.0",
        "sourceNotes": "Derived from Statcast and Baseball Savant Home Run Tracker event joins. This file preserves one daily Tale of the Tape row for long-term reference.",
        "fields": {
            "dailyDong": "The day's loudest actual home run.",
            "hotDogRobbery": "The day's strongest HR-capable batted ball that stayed in the yard.",
            "cheapestDong": "The day's flimsiest actual home run that still counted.",
        },
        "sourceArchive": source_archive.as_posix(),
        "dailyDong": event.get("dailyDong"),
        "hotDogRobbery": event.get("hotDogRobbery"),
        "cheapestDong": event.get("cheapestDong"),
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []

    for archive_path in sorted(args.data_dir.glob("daily-features-*.json")):
        archive = read_json(archive_path)
        events = archive.get("events", [])
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict) or not event.get("gameDate"):
                continue
            season = infer_season(archive_path, archive, event)
            if season is None:
                continue
            path = args.output_dir / f"{event['gameDate']}.json"
            payload = event_payload(event, season, archive.get("generatedAt", ""), archive_path)
            text = json.dumps(payload, indent=2) + "\n"
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            path.write_text(text, encoding="utf-8")
            changed.append(path)

    if changed:
        print("Wrote Tale of the Tape archives:")
        for path in changed:
            print(f"- {path}")
    else:
        print("Tale of the Tape archives are already up to date.")


if __name__ == "__main__":
    main()
