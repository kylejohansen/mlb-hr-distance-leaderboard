#!/usr/bin/env python3
"""Inspect inputs used by The Hot Dog Stand.

This diagnostic checks the pitcher-side Baseball Savant Home Run Tracker CSV
and the local pitch cache columns used for Hot Dog Index event context.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from generate_hot_dog_stand import fetch_home_run_tracker_pitchers
from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache


PITCH_CACHE_FIELDS = [
    "game_date",
    "game_pk",
    "pitcher",
    "player_name",
    "batter",
    "events",
    "hit_distance_sc",
    "launch_speed",
    "launch_angle",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Hot Dog Stand data inputs.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--pitch-cache", type=Path, default=PITCH_CACHE_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tracker = fetch_home_run_tracker_pitchers(args.season)
    pitches = read_pitch_cache(args.pitch_cache)

    print("\n=== Home Run Tracker pitcher CSV ===")
    print(f"Rows: {len(tracker)}")
    print(f"Columns: {list(tracker.columns)}")
    if not tracker.empty:
        print("Sample:")
        print(json.dumps(tracker.head(3).to_dict(orient="records"), indent=2, default=str))

    print("\n=== Pitch cache fields ===")
    print(f"Rows: {len(pitches)}")
    for field in PITCH_CACHE_FIELDS:
        print(f"- {field}: {'yes' if field in pitches.columns else 'missing'}")

    home_runs = pitches[pitches["events"].astype("string").str.lower().eq("home_run")].copy()
    print(f"\nHome run events in pitch cache: {len(home_runs)}")
    if not home_runs.empty:
        sample = home_runs[PITCH_CACHE_FIELDS].head(10)
        print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
