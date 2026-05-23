#!/usr/bin/env python3
"""Prototype actual Cheapie HR classification from Home Run Tracker details.

This diagnostic does not feed the production data pipeline. It fetches
Baseball Savant Home Run Tracker player detail rows and joins them back to the
local Statcast pitch cache to see whether actual home runs can be classified
as Doubters reliably.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd

from diagnose_home_run_tracker import (
    BASE_URL,
    MODE_PARAMS,
    fetch_leaderboard_csv,
    fetch_text,
)


DEFAULT_CACHE = Path("data/raw/statcast-pitches.csv")
DEFAULT_LBI_JSON = Path("public/data/longball-index-2026.json")


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def load_player_hr_totals(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    players = payload.get("players", [])
    rows = [
        {
            "batter_id": int(player["batter"]),
            "player": player["player"],
            "team": player["team"],
            "hr": int(player.get("hr", 0)),
        }
        for player in players
        if player.get("batter")
    ]
    return pd.DataFrame(rows)


def fetch_detail_rows(year: int, cat: str, delay: float = 0.02) -> pd.DataFrame:
    leaderboard_rows = fetch_leaderboard_csv(year, cat, min_hr=0)
    detail_rows: list[dict[str, Any]] = []

    for index, row in enumerate(leaderboard_rows, start=1):
        player_id = row.get("player_id")
        if not player_id:
            continue
        try:
            params = {
                "type": "details",
                "player_id": player_id,
                "year": str(year),
                "player_type": "Batter",
                "cat": cat,
            }
            body, _ = fetch_text(f"{BASE_URL}?{urlencode(params)}", "application/json,text/plain,*/*")
            rows = json.loads(body)
        except Exception as error:  # noqa: BLE001 - diagnostic should keep going.
            print(f"Detail fetch failed for player_id {player_id}: {error}")
            continue
        for detail in rows:
            detail["leaderboard_player"] = row.get("player")
            detail["hrt_hr_total"] = row.get("hr_total")
            detail_rows.append(detail)
        if delay:
            time.sleep(delay)
        if index % 50 == 0:
            print(f"Fetched detail rows for {index} players...")

    return pd.DataFrame(detail_rows)


def classify_detail_rows(details: pd.DataFrame) -> pd.DataFrame:
    frame = details.copy()
    for column in ["game_pk", "batter_id", "pitcher_id", "ct", "hr_distance", "exit_velocity", "launch_angle", "hrt_hr_total"]:
        if column in frame.columns:
            frame[column] = to_numeric(frame[column])

    frame["is_doubter_detail"] = frame["hr_cat"].astype("string").str.lower().eq("doubter")
    frame["is_no_doubter_detail"] = frame["hr_cat"].astype("string").str.lower().eq("no doubter")
    frame.loc[frame["hr_cat"].isna() & frame["ct"].le(7), "is_doubter_detail"] = True
    frame.loc[frame["hr_cat"].isna() & frame["ct"].eq(30), "is_no_doubter_detail"] = True
    frame["is_mostly_gone_detail"] = (
        frame["hr_cat"].astype("string").str.lower().eq("mostly gone")
        | (frame["hr_cat"].isna() & frame["ct"].between(8, 29, inclusive="both"))
    )
    return frame


def load_statcast_cache(path: Path) -> pd.DataFrame:
    columns = [
        "game_date",
        "game_pk",
        "pitcher",
        "batter",
        "events",
        "hit_distance_sc",
        "launch_speed",
        "launch_angle",
    ]
    frame = pd.read_csv(path, usecols=columns, low_memory=False)
    for column in ["game_pk", "pitcher", "batter", "hit_distance_sc", "launch_speed", "launch_angle"]:
        frame[column] = to_numeric(frame[column])
    frame["events"] = frame["events"].astype("string")
    return frame.dropna(subset=["game_pk", "pitcher", "batter"])


def fuzzy_join_details_to_statcast(details: pd.DataFrame, statcast: pd.DataFrame) -> pd.DataFrame:
    left = details.reset_index(names="detail_id")
    merged = left.merge(
        statcast,
        left_on=["game_pk", "batter_id", "pitcher_id"],
        right_on=["game_pk", "batter", "pitcher"],
        how="left",
        suffixes=("_detail", "_statcast"),
    )
    merged["distance_diff"] = (merged["hr_distance"] - merged["hit_distance_sc"]).abs()
    merged["ev_diff"] = (merged["exit_velocity"] - merged["launch_speed"]).abs()
    merged["la_diff"] = (merged["launch_angle_detail"] - merged["launch_angle_statcast"]).abs()

    candidates = merged[
        merged["distance_diff"].le(3)
        & merged["ev_diff"].le(1.0)
        & merged["la_diff"].le(2.0)
    ].copy()
    candidates["match_score"] = (
        candidates["distance_diff"].fillna(999)
        + candidates["ev_diff"].fillna(999)
        + candidates["la_diff"].fillna(999)
    )
    candidates = candidates.sort_values(["detail_id", "match_score"])
    return candidates.drop_duplicates("detail_id", keep="first")


def summarize_actual_cheapies(joined: pd.DataFrame, player_totals: pd.DataFrame) -> pd.DataFrame:
    actual_hrs = joined[joined["events"].astype("string").str.lower().eq("home_run")].copy()
    grouped = actual_hrs.groupby("batter_id", as_index=False).agg(
        actualDoubterHr=("is_doubter_detail", "sum"),
        actualMostlyGoneHr=("is_mostly_gone_detail", "sum"),
        actualNoDoubterHr=("is_no_doubter_detail", "sum"),
        joinedActualHr=("events", "size"),
        hrtHrTotal=("hrt_hr_total", "max"),
    )
    output = player_totals.merge(grouped, on="batter_id", how="left")
    for column in ["actualDoubterHr", "actualMostlyGoneHr", "actualNoDoubterHr", "joinedActualHr", "hrtHrTotal"]:
        output[column] = output[column].fillna(0).astype(int)
    output["cheapieRate"] = output["actualDoubterHr"] / output["hr"].where(output["hr"] > 0)
    return output


def print_detail_schema(details: pd.DataFrame) -> None:
    probes = [
        "game_pk",
        "play_id",
        "batter_id",
        "pitcher_id",
        "hr_cat",
        "ct",
        "hr_distance",
        "exit_velocity",
        "launch_angle",
        "result",
    ]
    print("\n=== Home Run Tracker detail schema ===")
    print(f"Rows: {len(details)}")
    print(f"Columns: {list(details.columns)}")
    for probe in probes:
        print(f"- {probe}: {'yes' if probe in details.columns else 'missing'}")
    if not details.empty:
        print("\nSample detail rows:")
        print(details[probes].head(8).to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose actual Cheapie HR feasibility.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--cat", choices=MODE_PARAMS.keys(), default="adjusted")
    parser.add_argument("--pitch-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--lbi-json", type=Path, default=DEFAULT_LBI_JSON)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cat = MODE_PARAMS[args.cat]
    details = classify_detail_rows(fetch_detail_rows(args.season, cat))
    statcast = load_statcast_cache(args.pitch_cache)
    player_totals = load_player_hr_totals(args.lbi_json)

    print_detail_schema(details)

    joined = fuzzy_join_details_to_statcast(details, statcast)
    actual_joined = joined[joined["events"].astype("string").str.lower().eq("home_run")]
    summary = summarize_actual_cheapies(joined, player_totals)
    eligible = summary[summary["hr"].ge(5)].copy()
    top = eligible.sort_values(
        ["cheapieRate", "actualDoubterHr", "hr"],
        ascending=[False, False, False],
    ).head(20)

    hrt_actual_home_runs = details["result"].astype("string").str.lower().eq("home_run").sum()
    hrt_aggregate_hr_total = int(details.drop_duplicates("batter_id")["hrt_hr_total"].fillna(0).sum())
    player_hr_total = int(player_totals["hr"].sum())
    joined_actual_count = len(actual_joined)
    comparable = summary[summary["hr"].gt(0)]
    exact_player_hr_matches = (comparable["joinedActualHr"] == comparable["hr"]).sum()
    exact_hrt_hr_matches = (comparable["joinedActualHr"] == comparable["hrtHrTotal"]).sum()
    exact_player_to_hrt_matches = (comparable["hr"] == comparable["hrtHrTotal"]).sum()

    print("\n=== Join diagnostics ===")
    print(f"Total Home Run Tracker detail rows: {len(details)}")
    print(f"Total joined to Statcast cache: {len(joined)}")
    print(f"Join rate: {len(joined) / len(details):.1%}" if len(details) else "Join rate: n/a")
    print(f"HRT detail rows with result == home_run: {hrt_actual_home_runs}")
    print(f"HRT aggregate hr_total sum: {hrt_aggregate_hr_total}")
    print(f"Joined rows where Statcast events == home_run: {joined_actual_count}")
    print(f"Player JSON actual HR total: {player_hr_total}")
    print(
        "Players with exact joined HR count vs player hr field: "
        f"{exact_player_hr_matches}/{len(comparable)}"
    )
    print(
        "Players with exact joined HR count vs HRT aggregate hr_total: "
        f"{exact_hrt_hr_matches}/{len(comparable)}"
    )
    print(
        "Players with exact player hr field vs HRT aggregate hr_total: "
        f"{exact_player_to_hrt_matches}/{len(comparable)}"
    )

    print("\n=== Top 20 actual Cheapies prototype (HR >= 5) ===")
    if top.empty:
        print("No eligible rows.")
    else:
        for _, row in top.iterrows():
            print(
                f"{row['player']} ({row['team']}): "
                f"{row['cheapieRate']:.0%} | "
                f"{row['actualDoubterHr']} Doubter HR / {row['hr']} HR "
                f"(joined HR {row['joinedActualHr']}, HRT HR {row['hrtHrTotal']})"
            )

    sanoja = summary[summary["player"].eq("Javier Sanoja")]
    print("\n=== Javier Sanoja check ===")
    if sanoja.empty:
        print("Javier Sanoja not present in player JSON.")
    else:
        row = sanoja.iloc[0]
        print(
            f"Javier Sanoja: HR={row['hr']}, actualDoubterHr={row['actualDoubterHr']}, "
            f"eligible={row['hr'] >= 5}"
        )


if __name__ == "__main__":
    main()
