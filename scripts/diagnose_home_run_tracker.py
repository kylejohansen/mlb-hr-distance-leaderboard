#!/usr/bin/env python3
"""Inspect Baseball Savant Home Run Tracker fields.

This is a diagnostic helper only. It does not feed the frontend data pipeline.
It checks the leaderboard CSV and the player detail JSON used by the expanded
rows on https://baseballsavant.mlb.com/leaderboard/home-runs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import unicodedata
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://baseballsavant.mlb.com/leaderboard/home-runs"
MODE_PARAMS = {
    "adjusted": "adj_xhr",
    "standard": "xhr",
}
TEST_PLAYERS = [
    "Ke'Bryan Hayes",
    "Alex Bregman",
    "Kyle Schwarber",
    "Aaron Judge",
    "Isaac Paredes",
]
TEAM_PARK_FIELDS = [
    "laa",
    "bal",
    "bos",
    "cws",
    "cle",
    "kc",
    "oak",
    "tb",
    "tex",
    "tor",
    "ari",
    "chc",
    "col",
    "lad",
    "pit",
    "mil",
    "sea",
    "hou",
    "det",
    "sf",
    "cin",
    "sd",
    "phi",
    "stl",
    "nym",
    "wsh",
    "min",
    "nyy",
    "mia",
    "atl",
]
INTERESTING_FIELDS = [
    "player",
    "player_id",
    "team_abbrev",
    "type",
    "doubters",
    "mostly_gone",
    "no_doubters",
    "no_doubter_per",
    "hr_total",
    "xhr",
    "xhr_diff",
    "non_hr_ct",
    "non_hr_would_have_left",
    "perfect_timing",
    "ct",
    "hr_cat",
    "hr_type",
    "result",
    "game_date",
    "play_id",
    "batter_id",
    "batter_name",
    "pitcher_id",
    "pitcher_name",
    "hr_distance",
    "exit_velocity",
    "launch_angle",
]


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.replace("’", "'"))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def display_name_from_savant_name(name: str) -> str:
    if "," not in name:
        return name.strip()
    last, first = [part.strip() for part in name.split(",", 1)]
    return f"{first} {last}".strip()


def to_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def browser_headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": accept,
        "Referer": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }


def fetch_text(url: str, accept: str) -> tuple[str, str]:
    request = Request(url, headers=browser_headers(accept))
    with urlopen(request, timeout=45) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
        return body, response.headers.get("content-type", "")


def print_row_sample(row: dict[str, object], fields: Iterable[str]) -> None:
    sample = {field: row.get(field) for field in fields if field in row}
    print(json.dumps(sample, indent=2, ensure_ascii=False))


def fetch_leaderboard_csv(year: int, cat: str, min_hr: int) -> list[dict[str, str]]:
    params = {
        "player_type": "Batter",
        "year": str(year),
        "cat": cat,
        "min": str(min_hr),
        "csv": "true",
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    body, content_type = fetch_text(url, "text/csv,text/plain,*/*")
    reader = csv.DictReader(io.StringIO(body))
    rows = list(reader)

    print(f"\n=== Batter {year} {cat} min HR {min_hr} CSV ===")
    print(f"URL: {url}")
    print(f"Content-Type: {content_type}")
    print(f"Rows: {len(rows)}")
    if rows:
        print(f"Columns: {list(rows[0].keys())}")
        print("Sample row:")
        print_row_sample(rows[0], INTERESTING_FIELDS)
    return rows


def fetch_player_details(
    player_id: str,
    year: int,
    cat: str,
    player_type: str = "Batter",
) -> list[dict[str, object]]:
    params = {
        "type": "details",
        "player_id": player_id,
        "year": str(year),
        "player_type": player_type,
        "cat": cat,
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    body, content_type = fetch_text(url, "application/json,text/plain,*/*")
    rows = json.loads(body)

    print(f"\n=== Detail JSON player_id {player_id} {year} {cat} ===")
    print(f"URL: {url}")
    print(f"Content-Type: {content_type}")
    print(f"Rows: {len(rows)}")
    if rows:
        print(f"Columns: {list(rows[0].keys())}")
        print("Sample row:")
        print_row_sample(rows[0], INTERESTING_FIELDS + TEAM_PARK_FIELDS)
    return rows


def summarize_field_presence(rows: list[dict[str, object]], label: str) -> None:
    columns = set(rows[0].keys()) if rows else set()
    probes = {
        "parks-out-of-30 single field": ["parks_out_of_30", "hr_stadiums", "expected_hr"],
        "home-run park count": ["ct"],
        "no doubters": ["no_doubters", "no_doubter_per"],
        "mostly gone": ["mostly_gone"],
        "doubters": ["doubters"],
        "expected home runs": ["xhr"],
        "actual HR vs expected HR": ["hr_total", "xhr", "xhr_diff"],
        "per-park columns": TEAM_PARK_FIELDS,
        "pitcher fields": ["pitcher_id", "pitcher_name"],
    }

    print(f"\n=== Field presence: {label} ===")
    for name, fields in probes.items():
        found = [field for field in fields if field in columns]
        print(f"{name}: {', '.join(found) if found else 'not found'}")


def compare_csv_modes(
    adjusted_rows: list[dict[str, str]],
    standard_rows: list[dict[str, str]],
) -> None:
    adjusted_columns = list(adjusted_rows[0].keys()) if adjusted_rows else []
    standard_columns = list(standard_rows[0].keys()) if standard_rows else []

    adjusted_by_player = {
        normalize_name(display_name_from_savant_name(row.get("player", ""))): row
        for row in adjusted_rows
    }
    standard_by_player = {
        normalize_name(display_name_from_savant_name(row.get("player", ""))): row
        for row in standard_rows
    }

    print("\n=== Adjusted vs Standard CSV comparison ===")
    print("Adjusted parameter: cat=adj_xhr")
    print("Standard parameter: cat=xhr")
    print(f"Returned columns identical: {adjusted_columns == standard_columns}")
    if adjusted_columns != standard_columns:
        print(f"Adjusted-only columns: {sorted(set(adjusted_columns) - set(standard_columns))}")
        print(f"Standard-only columns: {sorted(set(standard_columns) - set(adjusted_columns))}")

    print("\nKey player xHR comparison:")
    print("Player | HR | Adjusted xHR | Standard xHR | Adjusted - Standard")
    for player in TEST_PLAYERS:
        key = normalize_name(player)
        adjusted = adjusted_by_player.get(key)
        standard = standard_by_player.get(key)
        if not adjusted or not standard:
            print(f"{player} | not present in both views")
            continue
        adjusted_xhr = to_float(adjusted.get("xhr"))
        standard_xhr = to_float(standard.get("xhr"))
        adjusted_text = f"{adjusted_xhr:.1f}" if adjusted_xhr is not None else "n/a"
        standard_text = f"{standard_xhr:.1f}" if standard_xhr is not None else "n/a"
        diff_text = "n/a"
        if adjusted_xhr is not None and standard_xhr is not None:
            diff_text = f"{adjusted_xhr - standard_xhr:+.1f}"
        print(
            f"{player} | {adjusted.get('hr_total')} | "
            f"{adjusted_text} | {standard_text} | {diff_text}"
        )


def validate_xhr_population(rows: list[dict[str, str]], label: str) -> None:
    zero_hr_positive_xhr = [
        row
        for row in rows
        if to_float(row.get("hr_total")) == 0 and (to_float(row.get("xhr")) or 0) > 0
    ]
    print(f"\n=== xHR population check: {label} ===")
    print(f"Players with hr_total == 0 and xhr > 0: {len(zero_hr_positive_xhr)}")
    if zero_hr_positive_xhr:
        print("Sample zero-HR players with positive xHR:")
        for row in zero_hr_positive_xhr[:8]:
            print(
                f"- {display_name_from_savant_name(row.get('player', ''))} "
                f"({row.get('team_abbrev')}): HR {row.get('hr_total')}, "
                f"xHR {row.get('xhr')}, HR-xHR {row.get('xhr_diff')}"
            )
        print(
            "Conclusion: Home Run Tracker xHR is not HR-only; it includes "
            "non-HR batted balls that would have cleared at least one park."
        )
    else:
        print(
            "Conclusion: no zero-HR players had positive xHR in this pull. "
            "Treat Home Run Tracker xHR as likely HR-only until proven otherwise."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--min-hr", type=int, default=0)
    parser.add_argument(
        "--player-id",
        default=None,
        help="Player id for detail JSON. Defaults to the top adjusted CSV row.",
    )
    args = parser.parse_args()

    adjusted_rows = fetch_leaderboard_csv(args.year, MODE_PARAMS["adjusted"], args.min_hr)
    standard_rows = fetch_leaderboard_csv(args.year, MODE_PARAMS["standard"], args.min_hr)
    summarize_field_presence(adjusted_rows, "adjusted CSV")
    summarize_field_presence(standard_rows, "standard CSV")
    compare_csv_modes(adjusted_rows, standard_rows)
    validate_xhr_population(adjusted_rows, "adjusted CSV")
    validate_xhr_population(standard_rows, "standard CSV")

    player_id = args.player_id
    if not player_id and adjusted_rows:
        player_id = adjusted_rows[0].get("player_id")

    if player_id:
        adjusted_details = fetch_player_details(player_id, args.year, "adj_xhr")
        standard_details = fetch_player_details(player_id, args.year, "xhr")
        summarize_field_presence(adjusted_details, "adjusted detail JSON")
        summarize_field_presence(standard_details, "standard detail JSON")


if __name__ == "__main__":
    main()
