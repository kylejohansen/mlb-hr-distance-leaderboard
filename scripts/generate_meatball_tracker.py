#!/usr/bin/env python3
"""Generate frontend-ready Meatball Tracker JSON.

This is data-only backend work. The frontend does not read this file yet.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache


OUTPUT_PATH = Path("public/data/meatball-tracker-latest.json")
MIN_HR_ALLOWED = 5
RATE_VIEW_MIN_HR_ALLOWED = 8
MIN_PITCH_TYPE_SAMPLE = 15


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value) or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def pitcher_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def add_velocity_context(pitches: pd.DataFrame) -> pd.DataFrame:
    pitches = pitches.copy()
    speeds = pitches.dropna(subset=["pitcher", "pitch_type", "release_speed"]).copy()
    pitch_type_counts = (
        speeds.groupby(["pitcher", "pitch_type"])["release_speed"]
        .size()
        .rename("pitcher_pitch_type_pitch_count")
        .reset_index()
    )
    p25 = (
        speeds.groupby(["pitcher", "pitch_type"])["release_speed"]
        .quantile(0.25)
        .rename("pitcher_pitch_type_p25_velocity")
        .reset_index()
    )
    pitches = pitches.merge(p25, on=["pitcher", "pitch_type"], how="left")
    pitches = pitches.merge(pitch_type_counts, on=["pitcher", "pitch_type"], how="left")
    pitches["below_pitcher_pitch_type_p25"] = (
        pitches["release_speed"].notna()
        & pitches["pitcher_pitch_type_p25_velocity"].notna()
        & pitches["pitcher_pitch_type_pitch_count"].ge(MIN_PITCH_TYPE_SAMPLE)
        & pitches["release_speed"].lt(pitches["pitcher_pitch_type_p25_velocity"])
    )
    return pitches


def build_meatball_rows(pitches: pd.DataFrame, min_hr_allowed: int) -> list[dict[str, Any]]:
    if pitches.empty:
        return []

    pitches = add_velocity_context(pitches)
    home_runs = pitches[pitches["events"].astype("string").str.lower().eq("home_run")].copy()
    if home_runs.empty:
        return []

    home_runs["is_meatball"] = (
        home_runs["is_heart_zone"].fillna(False).astype(bool)
        & home_runs["below_pitcher_pitch_type_p25"].fillna(False).astype(bool)
    )
    rows = []

    for pitcher_id, group in home_runs.groupby("pitcher"):
        total_hrs = int(len(group))
        if total_hrs < min_hr_allowed:
            continue

        pitcher_name_values = group["player_name"].dropna().astype(str)
        pitcher_name = pitcher_display_name(pitcher_name_values.mode().iloc[0]) if not pitcher_name_values.empty else f"MLBAM {pitcher_id}"
        meatballs = int(group["is_meatball"].sum())
        heart_hrs = int(group["is_heart_zone"].fillna(False).astype(bool).sum())
        launch_speeds = pd.to_numeric(group["launch_speed"], errors="coerce").dropna()
        distances = pd.to_numeric(group["hit_distance_sc"], errors="coerce").dropna()

        rows.append(
            {
                "pitcher_id": int(pitcher_id),
                "pitcher": pitcher_name,
                "meatballs_count": meatballs,
                "heart_zone_hr_count": heart_hrs,
                "hrs_allowed": total_hrs,
                "meatballs_allowed": meatballs,
                "total_hrs_allowed": total_hrs,
                "meatball_rate": round(meatballs / total_hrs, 3) if total_hrs else 0,
                "meatball_reliance": round(meatballs / total_hrs, 3) if total_hrs else 0,
                "heart_zone_hr_rate": round(heart_hrs / total_hrs, 3) if total_hrs else 0,
                "avg_ev_on_hrs_allowed": round(float(launch_speeds.mean()), 1) if not launch_speeds.empty else None,
                "max_ev_on_hrs_allowed": round(float(launch_speeds.max()), 1) if not launch_speeds.empty else None,
                "avg_distance_on_hrs_allowed": round(float(distances.mean()), 1) if not distances.empty else None,
                "max_distance_on_hrs_allowed": round(float(distances.max())) if not distances.empty else None,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            -row["meatballs_allowed"],
            -row["meatball_rate"],
            -row["total_hrs_allowed"],
            row["pitcher"],
        ),
    )


def write_json(path: Path, rows: list[dict[str, Any]], pitch_cache: Path, min_hr_allowed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "pitchCache": str(pitch_cache),
            "heartZoneSource": "Baseball Savant Statcast Search hfNewZones=1|2|3|4|5|6|7|8|9|",
            "definition": (
                "Meatball = HR allowed on an official Heart-zone pitch with release_speed "
                "below the pitcher's 25th percentile for that pitch type. Pitcher pitch-type "
                f"samples below {MIN_PITCH_TYPE_SAMPLE} pitches are excluded from velocity-percentile evaluation."
            ),
        },
        "qualifiedBy": {
            "minimumHrsAllowed": min_hr_allowed,
            "viewQualifiers": {
                "hallOfShame": {"minimumHrsAllowed": min_hr_allowed},
                "battingPractice": {"minimumHrsAllowed": min_hr_allowed},
                "overThePlate": {"minimumHrsAllowed": RATE_VIEW_MIN_HR_ALLOWED},
                "cookieReliance": {"minimumHrsAllowed": RATE_VIEW_MIN_HR_ALLOWED},
            },
            "velocityPercentileMinimumPitchTypeSample": MIN_PITCH_TYPE_SAMPLE,
        },
        "pitchers": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def print_diagnostics(rows: list[dict[str, Any]]) -> None:
    print("\n=== Meatball Tracker diagnostics ===")
    print(f"Pitchers meeting 5+ HR qualifier: {len(rows)}")
    rate_rows = [row for row in rows if row["hrs_allowed"] >= RATE_VIEW_MIN_HR_ALLOWED]
    print(f"Pitchers meeting 8+ HR rate-view qualifier: {len(rate_rows)}")

    print("\nHall of Shame: meatballs_allowed")
    for index, row in enumerate(sorted(rows, key=lambda item: (-item["meatballs_allowed"], -item["total_hrs_allowed"], item["pitcher"]))[:10], 1):
        print(f"{index:2}. {row['pitcher']} | meatballs {row['meatballs_count']} | HR {row['hrs_allowed']} | reliance {row['meatball_reliance']}")

    print("\nBatting Practice: avg_ev_on_hrs_allowed")
    for index, row in enumerate(sorted(rows, key=lambda item: (-(to_float(item["avg_ev_on_hrs_allowed"]) or 0), -item["total_hrs_allowed"], item["pitcher"]))[:10], 1):
        print(f"{index:2}. {row['pitcher']} | avg EV {row['avg_ev_on_hrs_allowed']} | max EV {row['max_ev_on_hrs_allowed']} | HR {row['hrs_allowed']}")

    print("\nOver the Plate: heart_zone_hr_rate (8+ HR allowed)")
    for index, row in enumerate(sorted(rate_rows, key=lambda item: (-item["heart_zone_hr_rate"], -item["total_hrs_allowed"], item["pitcher"]))[:10], 1):
        print(f"{index:2}. {row['pitcher']} | Heart HR rate {row['heart_zone_hr_rate']} | Heart HR {row['heart_zone_hr_count']} of {row['hrs_allowed']} | meatballs {row['meatballs_count']}")

    print("\nCookie Reliance: meatball_reliance (8+ HR allowed)")
    for index, row in enumerate(sorted(rate_rows, key=lambda item: (-item["meatball_reliance"], -item["meatballs_allowed"], -item["total_hrs_allowed"], item["pitcher"]))[:10], 1):
        print(f"{index:2}. {row['pitcher']} | reliance {row['meatball_reliance']} | meatballs {row['meatballs_count']} of {row['hrs_allowed']} HR")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Meatball Tracker pitcher JSON.")
    parser.add_argument("--pitch-cache", type=Path, default=PITCH_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr-allowed", type=int, default=MIN_HR_ALLOWED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pitches = read_pitch_cache(args.pitch_cache)
    rows = build_meatball_rows(pitches, min_hr_allowed=args.min_hr_allowed)
    print_diagnostics(rows)
    write_json(args.output, rows, args.pitch_cache, args.min_hr_allowed)
    print(f"Wrote {len(rows)} qualified pitchers to {args.output}")


if __name__ == "__main__":
    main()
