#!/usr/bin/env python3
"""Compare two Longball Index JSON files after the pitch-cache refactor."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any


STRESS_PLAYERS = [
    "Kyle Schwarber",
    "Munetaka Murakami",
    "Aaron Judge",
    "Ke'Bryan Hayes",
    "Nico Hoerner",
    "Alex Bregman",
]
IGNORED_TOP_LEVEL_KEYS = {"generatedAt", "source"}


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.replace("’", "'"))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def read_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def comparable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in IGNORED_TOP_LEVEL_KEYS}


def players_by_name(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        normalize_name(str(player.get("player", ""))): player
        for player in payload.get("players", [])
        if player.get("player")
    }


def print_stress_players(before: dict[str, Any], after: dict[str, Any]) -> None:
    before_players = players_by_name(before)
    after_players = players_by_name(after)
    print("\nStress player comparison:")
    for name in STRESS_PLAYERS:
        key = normalize_name(name)
        before_player = before_players.get(key)
        after_player = after_players.get(key)
        if not before_player or not after_player:
            print(f"- {name}: missing from {'before' if not before_player else 'after'}")
            continue
        print(
            f"- {name}: LBI {before_player.get('longballIndex')} -> {after_player.get('longballIndex')}; "
            f"BBE {before_player.get('bbe')} -> {after_player.get('bbe')}; "
            f"HR {before_player.get('hr')} -> {after_player.get('hr')}; "
            f"xHR/BBE {before_player.get('xhrPerBbe')} -> {after_player.get('xhrPerBbe')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare LBI JSON output before and after refactor.")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    before = read_payload(args.before)
    after = read_payload(args.after)
    unchanged = comparable_payload(before) == comparable_payload(after)

    print(f"Before players: {len(before.get('players', []))}")
    print(f"After players: {len(after.get('players', []))}")
    print(f"LBI comparable payload unchanged: {'YES' if unchanged else 'NO'}")
    print_stress_players(before, after)

    if not unchanged:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
