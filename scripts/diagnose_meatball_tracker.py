#!/usr/bin/env python3
"""Inspect Statcast fields needed for a future Meatball Tracker.

This is a diagnostic helper only. It does not feed the frontend data pipeline,
does not change the LBI formula, and does not write JSON output.
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from pybaseball import cache, statcast


DEFAULT_START = "2026-05-15"
DEFAULT_END = "2026-05-17"
RAW_CACHE_PATH = Path("data/raw/statcast-bbe-events.csv")
STATCAST_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
SAVANT_HEART_NEW_ZONES = "1|2|3|4|5|6|7|8|9|"

REQUIRED_FIELDS = [
    "attack_zone",
    "zone",
    "plate_x",
    "plate_z",
    "sz_top",
    "sz_bot",
    "pitch_type",
    "release_speed",
    "pitcher",
    "pitcher_id",
    "player_name",
    "pitcher_name",
    "events",
    "launch_speed",
    "hit_distance_sc",
]

PITCH_DETAIL_FIELDS = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "player_name",
    "pitcher_name",
    "pitcher",
    "batter",
    "events",
    "description",
    "des",
    "pitch_type",
    "release_speed",
    "zone",
    "attack_zone",
    "derived_attack_zone",
    "plate_x",
    "plate_z",
    "sz_top",
    "sz_bot",
    "launch_speed",
    "launch_angle",
    "hit_distance_sc",
    "home_team",
    "away_team",
    "inning_topbot",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose whether Statcast has the fields needed for Meatball Tracker."
    )
    parser.add_argument("--start", default=DEFAULT_START, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", default=DEFAULT_END, help="End date, YYYY-MM-DD.")
    parser.add_argument(
        "--enable-cache",
        action="store_true",
        help="Enable pybaseball request caching. Off by default to avoid writing outside the repo.",
    )
    parser.add_argument(
        "--validate-heart-filter",
        action="store_true",
        help="Compare derived Heart classification to Baseball Savant's official Heart attack-zone filter.",
    )
    return parser.parse_args()


def print_heading(title: str) -> None:
    print(f"\n=== {title} ===")


def pitcher_name_column(df: pd.DataFrame) -> str | None:
    for column in ("pitcher_name", "player_name"):
        if column in df.columns:
            return column
    return None


def derive_heart_zone(
    df: pd.DataFrame,
    vertical_margin: float = 0.5,
    horizontal_limit: float = 0.558,
) -> pd.Series:
    """Approximate Savant Heart using pitch coordinates and batter strike zone.

    Baseball Savant's public Statcast export may not include attack_zone. The
    common approximation for the Heart attack region is the central horizontal
    band over the plate and the middle of the batter-specific vertical zone:
    abs(plate_x) <= horizontal_limit and
    sz_bot + vertical_margin <= plate_z <= sz_top - vertical_margin.
    """

    needed = {"plate_x", "plate_z", "sz_bot", "sz_top"}
    if not needed.issubset(df.columns):
        return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")

    plate_x = pd.to_numeric(df["plate_x"], errors="coerce")
    plate_z = pd.to_numeric(df["plate_z"], errors="coerce")
    sz_bot = pd.to_numeric(df["sz_bot"], errors="coerce")
    sz_top = pd.to_numeric(df["sz_top"], errors="coerce")

    is_heart = (
        plate_x.between(-horizontal_limit, horizontal_limit)
        & plate_z.between(sz_bot + vertical_margin, sz_top - vertical_margin)
    )
    return is_heart.map({True: "Heart", False: "Not Heart"}).astype("object")


def fetch_savant_statcast_csv(start: str, end: str, hf_new_zones: str = "") -> pd.DataFrame:
    params = {
        "all": "true",
        "hfPT": "",
        "hfAB": "",
        "hfBBT": "",
        "hfPR": "",
        "hfZ": "",
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": hf_new_zones,
        "hfGT": "R|PO|S|",
        "hfSea": "",
        "hfSit": "",
        "player_type": "pitcher",
        "hfOuts": "",
        "opponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start,
        "game_date_lt": end,
        "team": "",
        "position": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "h_launch_speed",
        "sort_order": "desc",
        "min_abs": "0",
        "type": "details",
    }
    url = f"{STATCAST_CSV_URL}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://baseballsavant.mlb.com/statcast_search",
        },
    )
    with urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    frame = pd.read_csv(io.StringIO(body))
    frame.attrs["url"] = url
    return frame


def pitch_key_frame(df: pd.DataFrame) -> pd.DataFrame:
    key_columns = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"]
    frame = df.copy()
    for column in key_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def official_heart_membership(full: pd.DataFrame, heart: pd.DataFrame) -> pd.Series:
    key_columns = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"]
    full = pitch_key_frame(full)
    heart = pitch_key_frame(heart)
    heart_keys = set(
        heart[key_columns]
        .dropna()
        .astype(int)
        .itertuples(index=False, name=None)
    )
    return full[key_columns].apply(
        lambda row: tuple(int(value) for value in row) in heart_keys if row.notna().all() else False,
        axis=1,
    )


def print_heart_filter_validation(start: str, end: str) -> None:
    print_heading("Savant official Heart filter validation")
    print("Official Heart filter uses Statcast Search parameter hfNewZones=1|2|3|4|5|6|7|8|9|")
    started = time.perf_counter()
    full = fetch_savant_statcast_csv(start, end)
    heart = fetch_savant_statcast_csv(start, end, SAVANT_HEART_NEW_ZONES)
    elapsed = time.perf_counter() - started
    print(f"Fetched full rows: {len(full):,}")
    print(f"Fetched official Heart rows: {len(heart):,}")
    print(f"Fetch time: {elapsed:.1f}s")
    print(f"Full CSV URL: {full.attrs.get('url')}")
    print(f"Heart CSV URL: {heart.attrs.get('url')}")
    print(f"attack_zone column in full CSV: {'attack_zone' in full.columns}")

    full = pitch_key_frame(full)
    full["official_heart"] = official_heart_membership(full, heart)
    full["derived_heart_original"] = derive_heart_zone(full, vertical_margin=0.5).eq("Heart")
    full["derived_heart_savant_fit"] = derive_heart_zone(full, vertical_margin=0.185).eq("Heart")
    valid = full[
        full[["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "plate_x", "plate_z", "sz_bot", "sz_top"]]
        .notna()
        .all(axis=1)
    ].copy()

    for column, label in [
        ("derived_heart_original", "Original rule, vertical margin 0.5 ft"),
        ("derived_heart_savant_fit", "Savant-fit rule, vertical margin 0.185 ft"),
    ]:
        agrees = valid[column].eq(valid["official_heart"])
        tp = int((valid[column] & valid["official_heart"]).sum())
        fp = int((valid[column] & ~valid["official_heart"]).sum())
        fn = int((~valid[column] & valid["official_heart"]).sum())
        print(f"\n{label}")
        print(f"Agreement: {agrees.mean() * 100:.2f}%")
        print(f"Predicted Heart: {int(valid[column].sum()):,}")
        print(f"Official Heart: {int(valid['official_heart'].sum()):,}")
        print(f"TP={tp:,} FP={fp:,} FN={fn:,}")

    disagreements = valid[valid["derived_heart_original"].ne(valid["official_heart"])].copy()
    if not disagreements.empty:
        px = pd.to_numeric(disagreements["plate_x"], errors="coerce")
        pz = pd.to_numeric(disagreements["plate_z"], errors="coerce")
        bot = pd.to_numeric(disagreements["sz_bot"], errors="coerce")
        top = pd.to_numeric(disagreements["sz_top"], errors="coerce")
        disagreements["nearest_original_boundary_ft"] = pd.concat(
            [
                (px.abs() - 0.558).abs(),
                (pz - (bot + 0.5)).abs(),
                (pz - (top - 0.5)).abs(),
            ],
            axis=1,
        ).min(axis=1)
        fields = [
            "game_date",
            "game_pk",
            "at_bat_number",
            "pitch_number",
            "player_name",
            "pitcher",
            "batter",
            "events",
            "description",
            "pitch_type",
            "release_speed",
            "zone",
            "plate_x",
            "plate_z",
            "sz_bot",
            "sz_top",
            "official_heart",
            "derived_heart_original",
            "nearest_original_boundary_ft",
        ]
        print("\nFirst 20 original-rule disagreements:")
        print(disagreements[[field for field in fields if field in disagreements.columns]].head(20).to_string(index=False))


def print_column_report(df: pd.DataFrame, label: str) -> None:
    print_heading(f"{label} columns")
    print(f"Rows: {len(df):,}")
    print(f"Column count: {len(df.columns):,}")
    print(list(df.columns))

    print_heading(f"{label} required field presence")
    for field in REQUIRED_FIELDS:
        present = field in df.columns
        print(f"{field}: {'present' if present else 'missing'}")


def print_sample_home_runs(hr_df: pd.DataFrame) -> None:
    print_heading("Sample 10 home run pitch details")
    if hr_df.empty:
        print("No home runs found in this date window.")
        return

    sample = hr_df.head(10).copy()
    fields = [field for field in PITCH_DETAIL_FIELDS if field in sample.columns]
    print(sample[fields].to_string(index=False))


def print_pitcher_diagnostic(df: pd.DataFrame, hr_df: pd.DataFrame) -> None:
    print_heading("Single-pitcher HR diagnostic")
    if hr_df.empty or "pitcher" not in hr_df.columns:
        print("No pitcher-level HR sample available.")
        return

    hr_counts = hr_df.groupby("pitcher").size().sort_values(ascending=False)
    eligible = hr_counts[hr_counts >= 2]
    if eligible.empty:
        print("No pitcher allowed 2+ HR in this date window. Showing top HR-allowed pitcher instead.")
        pitcher_id = hr_counts.index[0]
    else:
        pitcher_id = eligible.index[0]

    name_col = pitcher_name_column(df)
    pitcher_rows = df[df["pitcher"] == pitcher_id].copy()
    pitcher_hr = hr_df[hr_df["pitcher"] == pitcher_id].copy()
    pitcher_name = str(pitcher_id)
    if name_col and not pitcher_rows.empty:
        names = pitcher_rows[name_col].dropna().astype(str)
        if not names.empty:
            pitcher_name = names.mode().iloc[0]

    print(f"Pitcher: {pitcher_name} ({pitcher_id})")
    print(f"HR allowed in window: {len(pitcher_hr)}")

    detail_fields = [
        field
        for field in [
            "game_date",
            "events",
            "pitch_type",
            "release_speed",
            "plate_x",
            "plate_z",
            "sz_bot",
            "sz_top",
            "attack_zone",
            "derived_attack_zone",
            "launch_speed",
            "hit_distance_sc",
            "des",
        ]
        if field in pitcher_hr.columns
    ]

    print("\nHR allowed details:")
    print(pitcher_hr[detail_fields].to_string(index=False))

    print("\nPitch velocity distribution by pitch type:")
    if {"pitch_type", "release_speed"}.issubset(pitcher_rows.columns):
        speeds = pitcher_rows.dropna(subset=["pitch_type", "release_speed"]).copy()
        speeds["release_speed"] = pd.to_numeric(speeds["release_speed"], errors="coerce")
        summary = (
            speeds.dropna(subset=["release_speed"])
            .groupby("pitch_type")["release_speed"]
            .agg(
                pitches="count",
                mean="mean",
                p25=lambda values: values.quantile(0.25),
                p75=lambda values: values.quantile(0.75),
            )
            .sort_values("pitches", ascending=False)
        )
        if summary.empty:
            print("No release_speed values available for this pitcher.")
        else:
            print(summary.round(1).to_string())
    else:
        print("pitch_type and/or release_speed missing, cannot summarize velocity distribution.")


def print_summary(df: pd.DataFrame) -> None:
    columns = set(df.columns)
    direct_attack_zone = "attack_zone" in columns
    derivable_attack_zone = {"plate_x", "plate_z", "sz_bot", "sz_top"}.issubset(columns)
    must_have = [
        "events",
        "pitch_type",
        "release_speed",
        "pitcher",
        "launch_speed",
        "hit_distance_sc",
    ]
    accessible = all(field in columns for field in must_have) and (
        direct_attack_zone or derivable_attack_zone
    )

    print("\n\n=== TOPLINE FINDINGS ===")
    print(f"All core Meatball Tracker fields accessible: {'YES' if accessible else 'NO'}")
    print(f"attack_zone exposed directly: {'YES' if direct_attack_zone else 'NO'}")
    print(f"Heart zone derivable from plate_x/plate_z/sz_bot/sz_top: {'YES' if derivable_attack_zone else 'NO'}")
    missing = [field for field in must_have if field not in columns]
    if missing:
        print(f"Missing core fields: {', '.join(missing)}")
    else:
        print("Missing core fields: none")

    print(
        "Heart-zone note: attack_zone is absent in the CSV, but Savant's official "
        "Heart filter is available through hfNewZones=1|2|3|4|5|6|7|8|9|. "
        "Use --validate-heart-filter to compare any coordinate approximation "
        "against that official filter before productionizing."
    )
    print(
        "Recommended next step: use the official Heart filter or a validated "
        "Savant-fit coordinate rule, then design a cached pitch-level data job "
        "separate from the current BBE leaderboard cache."
    )


def main() -> None:
    args = parse_args()
    if args.enable_cache:
        cache.enable()

    if RAW_CACHE_PATH.exists():
        cache_sample = pd.read_csv(RAW_CACHE_PATH, nrows=5)
        print_column_report(cache_sample, f"Existing BBE cache ({RAW_CACHE_PATH})")
        print("Cache note: this cache is useful for BBE leaderboard work, but it is too slim for Meatball Tracker velocity/location diagnostics.")
    else:
        print_heading("Existing BBE cache")
        print(f"{RAW_CACHE_PATH} not found.")

    print_heading("Fetching fresh pybaseball Statcast sample")
    print(f"Date range: {args.start} to {args.end}")
    df = statcast(start_dt=args.start, end_dt=args.end)
    if df.empty:
        raise RuntimeError(f"pybaseball.statcast returned 0 rows for {args.start} to {args.end}.")

    df = df.copy()
    df["derived_attack_zone"] = derive_heart_zone(df)
    print_column_report(df, "Fresh pybaseball statcast() sample")

    hr_df = df[df["events"].eq("home_run")].copy() if "events" in df.columns else pd.DataFrame()
    print_heading("Home run count")
    print(f"Home run events in sample: {len(hr_df):,}")
    if "attack_zone" in hr_df.columns:
        print("attack_zone counts on HRs:")
        print(hr_df["attack_zone"].value_counts(dropna=False).to_string())
    if "derived_attack_zone" in hr_df.columns:
        print("derived_attack_zone counts on HRs:")
        print(hr_df["derived_attack_zone"].value_counts(dropna=False).to_string())

    print_sample_home_runs(hr_df)
    print_pitcher_diagnostic(df, hr_df)
    if args.validate_heart_filter:
        print_heart_filter_validation(args.start, args.end)
    print_summary(df)


if __name__ == "__main__":
    main()
