#!/usr/bin/env python3
"""Evaluate retained internal T6040 shadow snapshots.

Given two snapshot dates, this script takes the divergence lists from the
earlier snapshot and measures forward HR/BBE and HR/PA through the later
snapshot. It is the verdict tool for whether T6040's elevated group actually
out-homers its faded group on live data.

Current classification is two-way: real_signal / visible_noise. A three-way
split adding "real_power_wrong_mechanism" (xHR >= pool median but Thunder rate
< pool median, the Hicks case) is a planned refinement. It is computable from
stored snapshot fields (xHR/BBE, Thunder rate, Thunder share) at eval time
without re-snapshotting; the baseline raw data is captured and sufficient for
either classification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SNAPSHOT_DIR = Path("data/shadow/lbi_t6040")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate T6040 shadow divergence lists between two retained snapshots.")
    parser.add_argument("start_date", help="Earlier snapshot date YYYY-MM-DD.")
    parser.add_argument("end_date", help="Later snapshot date YYYY-MM-DD.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR, help="Shadow snapshot directory.")
    return parser.parse_args()


def load_snapshot(snapshot_dir: Path, date: str) -> dict[str, Any]:
    path = snapshot_dir / f"snapshot_{date}.json"
    with path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    snapshot["_path"] = str(path)
    return snapshot


def rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value * 100:.2f}%"


def evaluate_group(
    start: dict[str, Any],
    end: dict[str, Any],
    list_key: str,
    signal_bucket: str | None = None,
) -> dict[str, Any]:
    start_players = {int(player["playerId"]): player for player in start.get("players", [])}
    end_players = {int(player["playerId"]): player for player in end.get("players", [])}
    group_rows = start["divergenceLists"][list_key]
    if signal_bucket:
        group_rows = [row for row in group_rows if row.get("t6040SignalBucket") == signal_bucket]
    rows = []
    total_hr = 0
    total_bbe = 0
    total_pa = 0
    missing = []
    for entry in group_rows:
        player_id = int(entry["playerId"])
        start_row = start_players.get(player_id)
        end_row = end_players.get(player_id)
        if not start_row or not end_row:
            missing.append(entry)
            continue
        forward_hr = int(end_row.get("hr", 0)) - int(start_row.get("hr", 0))
        forward_bbe = int(end_row.get("bbe", 0)) - int(start_row.get("bbe", 0))
        forward_pa = int(end_row.get("pa", 0)) - int(start_row.get("pa", 0))
        total_hr += max(forward_hr, 0)
        total_bbe += max(forward_bbe, 0)
        total_pa += max(forward_pa, 0)
        rows.append(
            {
                "playerId": player_id,
                "player": entry["player"],
                "team": entry["team"],
                "rankDelta": entry["rankDelta"],
                "t6040SignalBucket": entry.get("t6040SignalBucket", ""),
                "t6040SignalLabel": entry.get("t6040SignalLabel", ""),
                "forwardHr": forward_hr,
                "forwardBbe": forward_bbe,
                "forwardPa": forward_pa,
                "forwardHrPerBbe": rate(forward_hr, forward_bbe),
                "forwardHrPerPa": rate(forward_hr, forward_pa),
            }
        )
    return {
        "group": list_key,
        "signalBucket": signal_bucket,
        "count": len(group_rows),
        "matched": len(rows),
        "missing": missing,
        "totalForwardHr": total_hr,
        "totalForwardBbe": total_bbe,
        "totalForwardPa": total_pa,
        "forwardHrPerBbe": rate(total_hr, total_bbe),
        "forwardHrPerPa": rate(total_hr, total_pa),
        "players": rows,
    }


def print_group(result: dict[str, Any]) -> None:
    title = "Elevated by T6040" if result["group"] == "elevatedByT6040" else "Faded by T6040"
    if result.get("signalBucket") == "real_signal":
        title += " — real signal only"
    elif result.get("signalBucket"):
        title += f" — {result['signalBucket']}"
    print(f"\n{title}")
    print(f"Matched: {result['matched']}/{result['count']}")
    print(f"Forward HR/BBE: {pct(result['forwardHrPerBbe'])}")
    print(f"Forward HR/PA: {pct(result['forwardHrPerPa'])}")
    print(f"Totals: {result['totalForwardHr']} HR / {result['totalForwardBbe']} BBE / {result['totalForwardPa']} PA")
    for row in sorted(result["players"], key=lambda item: (-(item["forwardHrPerBbe"] or -1), item["player"])):
        print(
            f"{row['player']} ({row['team']}): {row['forwardHr']} HR / "
            f"{row['forwardBbe']} BBE / {row['forwardPa']} PA | "
            f"HR/BBE {pct(row['forwardHrPerBbe'])} | HR/PA {pct(row['forwardHrPerPa'])}"
        )
    if result["missing"]:
        print("Missing in later snapshot:")
        for row in result["missing"]:
            print(f"- {row['player']} ({row['team']})")


def main() -> None:
    args = parse_args()
    start = load_snapshot(args.snapshot_dir, args.start_date)
    end = load_snapshot(args.snapshot_dir, args.end_date)
    elevated_real = evaluate_group(start, end, "elevatedByT6040", "real_signal")
    elevated = evaluate_group(start, end, "elevatedByT6040")
    faded = evaluate_group(start, end, "fadedByT6040")

    print(f"T6040 shadow evaluation: {args.start_date} -> {args.end_date}")
    print(f"Start: {start['_path']}")
    print(f"End: {end['_path']}")
    print("\nPrimary thesis test")
    print_group(elevated_real)
    print_group(faded)
    print("\nSecondary full-list context")
    print_group(elevated)

    elevated_hr_bbe = elevated_real["forwardHrPerBbe"]
    faded_hr_bbe = faded["forwardHrPerBbe"]
    elevated_hr_pa = elevated_real["forwardHrPerPa"]
    faded_hr_pa = faded["forwardHrPerPa"]
    print("\nVerdict")
    if elevated_hr_bbe is None or faded_hr_bbe is None:
        print("Not enough forward BBE to compare real-signal elevated HR/BBE yet.")
    else:
        diff = elevated_hr_bbe - faded_hr_bbe
        print(f"Real-signal elevated minus faded HR/BBE: {diff * 100:+.2f} pct points")
    if elevated_hr_pa is None or faded_hr_pa is None:
        print("Not enough forward PA to compare real-signal elevated HR/PA yet.")
    else:
        diff = elevated_hr_pa - faded_hr_pa
        print(f"Real-signal elevated minus faded HR/PA: {diff * 100:+.2f} pct points")


if __name__ == "__main__":
    main()
