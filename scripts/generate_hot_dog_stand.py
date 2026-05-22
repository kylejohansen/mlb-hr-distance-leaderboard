#!/usr/bin/env python3
"""Generate frontend-ready Hot Dog Stand pitcher JSON.

The Hot Dog Index is a pitcher-accountability view for The Long Ball. It uses
Baseball Savant Home Run Tracker aggregates plus Statcast event data from the
canonical pitch cache. The frontend reads only the generated static JSON.
"""

from __future__ import annotations

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache


OUTPUT_PATH = Path("public/data/hot-dog-stand-latest.json")
HOME_RUN_TRACKER_URL = "https://baseballsavant.mlb.com/leaderboard/home-runs"
HOME_RUN_TRACKER_CAT = "adj_xhr"
MIN_HR_ALLOWED = 5
MIN_BBE_ALLOWED = 50
HOT_DOG_VERSION = "1.0"
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.9)


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value) or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    parsed = to_float(value)
    return int(parsed) if parsed is not None else None


def pitcher_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def savant_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Referer": HOME_RUN_TRACKER_URL,
    }


def fetch_home_run_tracker_pitchers(season: int, cat: str = HOME_RUN_TRACKER_CAT) -> pd.DataFrame:
    params = {
        "player_type": "Pitcher",
        "year": str(season),
        "cat": cat,
        "min": "0",
        "csv": "true",
    }
    url = f"{HOME_RUN_TRACKER_URL}?{urlencode(params)}"
    print(f"Fetching Baseball Savant Home Run Tracker pitcher CSV ({cat})")
    print(f"Home Run Tracker URL: {url}")
    request = Request(url, headers=savant_headers())
    with urlopen(request, timeout=45) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    frame = pd.read_csv(io.StringIO(body))
    frame.attrs["source_url"] = url
    return frame


def percentile_scores(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    ranks = numeric.rank(method="average", pct=True)
    clipped = ranks.clip(lower=0.01, upper=0.99)
    normal = clipped.apply(lambda value: 100 + NORMAL_SCORE_SCALE * NormalDist().inv_cdf(float(value)) if pd.notna(value) else pd.NA)
    return pd.to_numeric(normal, errors="coerce")


def normalize_tracker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    tracker = frame.copy()
    tracker["pitcher_id"] = pd.to_numeric(tracker.get("player_id"), errors="coerce").astype("Int64")
    tracker["pitcher"] = tracker.get("player", "").map(pitcher_display_name)
    tracker["team"] = tracker.get("team_abbrev", "").astype("string")
    for column in ["doubters", "mostly_gone", "no_doubters", "hr_total", "xhr", "xhr_diff"]:
        tracker[column] = pd.to_numeric(tracker.get(column), errors="coerce")

    tracker["hr_capable_bbe_allowed"] = (
        tracker["doubters"].fillna(0) + tracker["mostly_gone"].fillna(0) + tracker["no_doubters"].fillna(0)
    )
    return tracker.dropna(subset=["pitcher_id"])


def build_statcast_pitcher_context(pitches: pd.DataFrame) -> pd.DataFrame:
    if pitches.empty:
        return pd.DataFrame(columns=["pitcher_id"])

    events = pitches[pitches["events"].notna()].copy()
    events["pitcher_id"] = pd.to_numeric(events["pitcher"], errors="coerce").astype("Int64")
    events["launch_speed"] = pd.to_numeric(events["launch_speed"], errors="coerce")
    events["hit_distance_sc"] = pd.to_numeric(events["hit_distance_sc"], errors="coerce")
    bbe = events[events["launch_speed"].notna() & events["launch_angle"].notna()].copy()
    home_runs = events[events["events"].astype("string").str.lower().eq("home_run")].copy()

    bbe_counts = bbe.groupby("pitcher_id").size().rename("bbe_allowed")
    hr_grouped = home_runs.groupby("pitcher_id")
    hr_stats = hr_grouped.agg(
        avgExitVelocityAllowed=("launch_speed", "mean"),
        maxExitVelocityAllowed=("launch_speed", "max"),
        avgDistanceAllowed=("hit_distance_sc", "mean"),
        maxDistanceAllowed=("hit_distance_sc", "max"),
    )

    worst_rows = []
    if not home_runs.empty:
        scored = home_runs.copy()
        scored["worst_score"] = scored["launch_speed"].fillna(0) * 2 + scored["hit_distance_sc"].fillna(0) / 10
        for pitcher_id, row in scored.sort_values("worst_score", ascending=False).groupby("pitcher_id").head(1).set_index("pitcher_id").iterrows():
            worst_rows.append(
                {
                    "pitcher_id": pitcher_id,
                    "worstServedEvent": {
                        "gameDate": str(row.get("game_date", ""))[:10],
                        "batterId": to_int(row.get("batter")),
                        "pitcherId": to_int(row.get("pitcher")),
                        "description": str(row.get("des") or row.get("description") or "").strip(),
                        "exitVelocity": round(float(row["launch_speed"]), 1) if pd.notna(row.get("launch_speed")) else None,
                        "distance": int(round(float(row["hit_distance_sc"]))) if pd.notna(row.get("hit_distance_sc")) else None,
                        "launchAngle": round(float(row["launch_angle"]), 1) if pd.notna(row.get("launch_angle")) else None,
                    },
                }
            )

    context = pd.concat([bbe_counts, hr_stats], axis=1).reset_index()
    worst = pd.DataFrame(worst_rows)
    if not worst.empty:
        context = context.merge(worst, on="pitcher_id", how="left")
    else:
        context["worstServedEvent"] = None
    return context


def build_hot_dog_rows(
    pitches: pd.DataFrame,
    tracker: pd.DataFrame,
    min_hr_allowed: int,
    min_bbe_allowed: int,
) -> list[dict[str, Any]]:
    tracker = normalize_tracker(tracker)
    context = build_statcast_pitcher_context(pitches)
    if tracker.empty or context.empty:
        return []

    merged = tracker.merge(context, on="pitcher_id", how="left")
    merged["bbe_allowed"] = pd.to_numeric(merged["bbe_allowed"], errors="coerce").fillna(0)
    merged["xhr_per_bbe_allowed"] = merged["xhr"].fillna(0) / merged["bbe_allowed"].where(merged["bbe_allowed"] > 0)
    merged["hr_capable_bbe_rate_allowed"] = merged["hr_capable_bbe_allowed"].fillna(0) / merged["bbe_allowed"].where(merged["bbe_allowed"] > 0)
    merged["no_doubter_rate_allowed"] = merged["no_doubters"].fillna(0) / merged["hr_capable_bbe_allowed"].where(merged["hr_capable_bbe_allowed"] > 0)

    qualified = merged[(merged["hr_total"].fillna(0) >= min_hr_allowed) & (merged["bbe_allowed"] >= min_bbe_allowed)].copy()
    if qualified.empty:
        return []

    qualified["xhr_score"] = percentile_scores(qualified["xhr_per_bbe_allowed"])
    qualified["capable_score"] = percentile_scores(qualified["hr_capable_bbe_rate_allowed"])
    qualified["no_doubter_score"] = percentile_scores(qualified["no_doubter_rate_allowed"])
    qualified["ev_score"] = percentile_scores(qualified["avgExitVelocityAllowed"])
    qualified["distance_score"] = percentile_scores(qualified["avgDistanceAllowed"])
    qualified["hotDogIndex"] = (
        qualified["xhr_score"] * 0.35
        + qualified["capable_score"] * 0.25
        + qualified["no_doubter_score"] * 0.15
        + qualified["ev_score"] * 0.15
        + qualified["distance_score"] * 0.10
    )
    qualified["cooked_per_100_bbe"] = qualified["hotDogIndex"] / qualified["bbe_allowed"].where(qualified["bbe_allowed"] > 0) * 100

    rows = []
    for _, row in qualified.iterrows():
        rows.append(
            {
                "pitcherId": int(row["pitcher_id"]),
                "pitcher": str(row.get("pitcher") or f"MLBAM {int(row['pitcher_id'])}"),
                "team": str(row.get("team") or ""),
                "hotDogIndex": round(float(row["hotDogIndex"]), 1),
                "bbeAllowed": int(row["bbe_allowed"]),
                "totalBbeAllowed": int(row["bbe_allowed"]),
                "cookedPer100Bbe": round(float(row["cooked_per_100_bbe"]), 1) if pd.notna(row.get("cooked_per_100_bbe")) else None,
                "hrsAllowed": int(row["hr_total"]),
                "adjustedXhrAllowed": round(float(row["xhr"]), 1) if pd.notna(row.get("xhr")) else None,
                "adjustedXhrPerBbeAllowed": round(float(row["xhr_per_bbe_allowed"]), 4) if pd.notna(row.get("xhr_per_bbe_allowed")) else None,
                "xhrDiffAllowed": round(float(row["xhr_diff"]), 1) if pd.notna(row.get("xhr_diff")) else None,
                "hrCapableBbeAllowed": int(row["hr_capable_bbe_allowed"]),
                "hrCapableBbeRateAllowed": round(float(row["hr_capable_bbe_rate_allowed"]), 4) if pd.notna(row.get("hr_capable_bbe_rate_allowed")) else None,
                "noDoubtersAllowed": int(row["no_doubters"] or 0),
                "mostlyGoneAllowed": int(row["mostly_gone"] or 0),
                "doubtersAllowed": int(row["doubters"] or 0),
                "noDoubterRateAllowed": round(float(row["no_doubter_rate_allowed"]), 4) if pd.notna(row.get("no_doubter_rate_allowed")) else None,
                "avgExitVelocityAllowed": round(float(row["avgExitVelocityAllowed"]), 1) if pd.notna(row.get("avgExitVelocityAllowed")) else None,
                "avgDistanceAllowed": round(float(row["avgDistanceAllowed"]), 1) if pd.notna(row.get("avgDistanceAllowed")) else None,
                "maxExitVelocityAllowed": round(float(row["maxExitVelocityAllowed"]), 1) if pd.notna(row.get("maxExitVelocityAllowed")) else None,
                "maxDistanceAllowed": int(round(float(row["maxDistanceAllowed"]))) if pd.notna(row.get("maxDistanceAllowed")) else None,
                "worstServedEvent": row.get("worstServedEvent") if isinstance(row.get("worstServedEvent"), dict) else None,
                "hotDogComponents": {
                    "adjustedXhrPerBbeAllowed": round(float(row["xhr_score"]), 1),
                    "hrCapableBbeRateAllowed": round(float(row["capable_score"]), 1),
                    "noDoubterRateAllowed": round(float(row["no_doubter_score"]), 1),
                    "avgExitVelocityAllowed": round(float(row["ev_score"]), 1),
                    "avgDistanceAllowed": round(float(row["distance_score"]), 1),
                },
            }
        )

    return sorted(rows, key=lambda item: (-item["hotDogIndex"], -item["hrCapableBbeAllowed"], item["pitcher"]))


def write_json(path: Path, rows: list[dict[str, Any]], pitch_cache: Path, season: int, min_hr_allowed: int, min_bbe_allowed: int, tracker_url: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "pitchCache": str(pitch_cache),
            "homeRunTracker": tracker_url or HOME_RUN_TRACKER_URL,
            "homeRunTrackerMode": HOME_RUN_TRACKER_CAT,
            "methodology": "Hot Dog Index measures loud, home-run-quality contact allowed by pitchers using Home Run Tracker and Statcast event data.",
        },
        "qualifiedBy": {
            "minimumHrsAllowed": min_hr_allowed,
            "minimumBbeAllowed": min_bbe_allowed,
        },
        "hotDogIndexVersion": HOT_DOG_VERSION,
        "pitchers": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def print_board(title: str, rows: list[dict[str, Any]], key: Any, value: Any) -> None:
    print(f"\n{title}")
    for index, row in enumerate(sorted(rows, key=key)[:10], 1):
        print(f"{index:2}. {row['pitcher']} ({row['team']}) | {value(row)}")


def print_diagnostics(rows: list[dict[str, Any]]) -> None:
    print("\n=== The Hot Dog Stand diagnostics ===")
    print(f"Qualified pitchers: {len(rows)}")
    print_board("Top Dogs: Hot Dog Index", rows, lambda row: (-row["hotDogIndex"], -row["hrCapableBbeAllowed"], row["pitcher"]), lambda row: f"HDI {row['hotDogIndex']} | HR-capable {row['hrCapableBbeAllowed']} | xHR/BBE {row['adjustedXhrPerBbeAllowed']}")
    print_board("Footlongs: HR-capable BBE allowed", rows, lambda row: (-row["hrCapableBbeAllowed"], -row["hotDogIndex"], row["pitcher"]), lambda row: f"HR-capable {row['hrCapableBbeAllowed']} | no-doubters {row['noDoubtersAllowed']}")
    print_board("Extra Mustard: no-doubters allowed", rows, lambda row: (-row["noDoubtersAllowed"], -row["hotDogIndex"], row["pitcher"]), lambda row: f"no-doubters {row['noDoubtersAllowed']} | mostly gone {row['mostlyGoneAllowed']}")
    cooked_rows = [row for row in rows if row["totalBbeAllowed"] >= 40 and row["hrCapableBbeAllowed"] >= 3 and row["cookedPer100Bbe"] is not None]
    print_board("Cooked: Hot Dog damage per 100 BBE", cooked_rows, lambda row: (-(row["cookedPer100Bbe"] or 0), -row["hotDogIndex"], row["pitcher"]), lambda row: f"{row['cookedPer100Bbe']} per 100 BBE | BBE {row['totalBbeAllowed']} | HR-capable {row['hrCapableBbeAllowed']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate The Hot Dog Stand pitcher JSON.")
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--pitch-cache", type=Path, default=PITCH_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--min-hr-allowed", type=int, default=MIN_HR_ALLOWED)
    parser.add_argument("--min-bbe-allowed", type=int, default=MIN_BBE_ALLOWED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pitches = read_pitch_cache(args.pitch_cache)
    tracker = fetch_home_run_tracker_pitchers(args.season)
    rows = build_hot_dog_rows(pitches, tracker, args.min_hr_allowed, args.min_bbe_allowed)
    print_diagnostics(rows)
    write_json(args.output, rows, args.pitch_cache, args.season, args.min_hr_allowed, args.min_bbe_allowed, tracker.attrs.get("source_url"))
    print(f"Wrote {len(rows)} qualified pitchers to {args.output}")


if __name__ == "__main__":
    main()
