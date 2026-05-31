#!/usr/bin/env python3
"""Refresh complete Home Run Tracker detail caches from Savant aggregate rows.

The old diagnostic cache was accidentally built from a candidate subset and
then reused as season-wide truth. This script fetches the full Batter min=0
aggregate list for each season, pulls detail rows for every aggregate player,
and verifies that detail coverage is close to the aggregate player count.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from data_integrity import validate_hrt_detail_completeness
from generate_hr_distance import (
    HOME_RUN_TRACKER_CAT,
    fetch_home_run_tracker,
    fetch_home_run_tracker_detail_rows,
)


CACHE_DIR = Path("data/cache/longball-threat-backtest")
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]


def detail_cache_path(season: int, cat: str = HOME_RUN_TRACKER_CAT) -> Path:
    return CACHE_DIR / f"hrt-details-{season}-{cat}.csv"


def refresh_season(season: int, *, force: bool) -> dict[str, int | str]:
    tracker = fetch_home_run_tracker(season)
    aggregate_count = int(pd.to_numeric(tracker.get("player_id"), errors="coerce").dropna().nunique())
    path = detail_cache_path(season)

    if path.exists() and not force:
        details = pd.read_csv(path)
        print(f"Using existing {path}; pass --force to refetch")
    else:
        details = fetch_home_run_tracker_detail_rows(tracker, season)
        path.parent.mkdir(parents=True, exist_ok=True)
        details.to_csv(path, index=False)

    validate_hrt_detail_completeness(details, season, label=str(path))
    detail_count = int(pd.to_numeric(details.get("batter_id"), errors="coerce").dropna().nunique())
    if detail_count < aggregate_count * 0.95:
        raise RuntimeError(
            f"{path} is incomplete: {detail_count} detail batters vs {aggregate_count} aggregate batters."
        )

    return {
        "season": season,
        "aggregateBatters": aggregate_count,
        "detailBatters": detail_count,
        "detailRows": len(details),
        "path": str(path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh complete HRT detail caches.")
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--force", action="store_true", help="Refetch even if a cache file exists.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries = [refresh_season(season, force=args.force) for season in args.seasons]
    print("\n=== HRT detail cache coverage ===")
    for summary in summaries:
        print(
            f"{summary['season']}: {summary['detailBatters']} detail batters / "
            f"{summary['aggregateBatters']} aggregate batters | {summary['detailRows']} rows | {summary['path']}"
        )


if __name__ == "__main__":
    main()
