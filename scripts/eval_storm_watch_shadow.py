#!/usr/bin/env python3
"""Evaluate internal Storm Watch shadow snapshots against later hitter data.

This is verdict tooling for the internal Young Power Radar workflow. It reads a
retained snapshot and a later/current hitter JSON, then reports forward HR
production by bucket. It does not change production data or public output.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SNAPSHOT_DIR = Path("data/shadow/storm_watch")
DEFAULT_CURRENT_DATA = Path("public/data/hr-distance-latest.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a Storm Watch shadow snapshot.")
    parser.add_argument("snapshot_date", help="Snapshot date YYYY-MM-DD.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR, help="Shadow snapshot directory.")
    parser.add_argument("--current-data", type=Path, default=DEFAULT_CURRENT_DATA, help="Later/current hitter JSON.")
    parser.add_argument("--evaluation-date", help="Evaluation date YYYY-MM-DD. Defaults to current-data generatedAt date.")
    parser.add_argument("--min-forward-days", type=int, default=42, help="Warn if fewer than this many days have elapsed.")
    parser.add_argument("--min-forward-pa", type=int, default=30, help="Flag playing-time issues below this forward PA.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value[:10])


def current_data_date(payload: dict[str, Any], override: str | None) -> str:
    if override:
        datetime.fromisoformat(override)
        return override
    generated_at = str(payload.get("generatedAt") or "")
    if generated_at:
        return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
    return datetime.now().date().isoformat()


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def fmt_rate(value: float | None) -> str:
    return "NA" if value is None else f"{value * 100:.2f}%"


def fmt_pace(value: float | None) -> str:
    return "NA" if value is None else f"{value * 600:.1f}"


def player_lookup(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = payload.get("players") if isinstance(payload, dict) else payload
    output = {}
    for row in rows or []:
        player_id = row.get("batter") or row.get("playerId")
        if player_id is not None:
            output[int(player_id)] = row
    return output


def miss_note(snapshot_row: dict[str, Any], forward_pa: int, produced: bool, min_forward_pa: int) -> str:
    notes = []
    if snapshot_row.get("contactRiskTag") in {"contact-whiff-risk", "mild-contact-risk"}:
        notes.append("contact/whiff risk")
    if "sample caution" in str(snapshot_row.get("bbeConfidenceNote", "")).lower():
        notes.append("BBE sample issue")
    if forward_pa < min_forward_pa:
        notes.append("playing-time issue")
    if produced and number(snapshot_row.get("b6Air")) < 115:
        notes.append("false-negative: power signal was modest")
    if not notes:
        notes.append("random/no obvious pattern")
    return "; ".join(notes)


def evaluate_rows(snapshot_rows: list[dict[str, Any]], current: dict[int, dict[str, Any]], min_forward_pa: int) -> list[dict[str, Any]]:
    rows = []
    for snapshot_row in snapshot_rows:
        player_id = int(snapshot_row["playerId"])
        current_row = current.get(player_id)
        if not current_row:
            rows.append(
                {
                    **snapshot_row,
                    "matched": False,
                    "forwardHr": None,
                    "forwardPa": None,
                    "forwardBbe": None,
                    "futureHrPerPa": None,
                    "futureHr600": None,
                    "hit30Hr600": False,
                    "hit35Hr600": False,
                    "evalNote": "missing from later/current data",
                }
            )
            continue
        forward_hr = max(int(number(current_row.get("hr"))) - int(number(snapshot_row.get("hr"))), 0)
        forward_pa = max(int(number(current_row.get("pa"))) - int(number(snapshot_row.get("pa"))), 0)
        forward_bbe = max(int(number(current_row.get("bbe"))) - int(number(snapshot_row.get("bbe"))), 0)
        future_hr_per_pa = rate(forward_hr, forward_pa)
        future_hr600 = None if future_hr_per_pa is None else future_hr_per_pa * 600
        produced = bool(future_hr600 is not None and future_hr600 >= 30)
        rows.append(
            {
                **snapshot_row,
                "matched": True,
                "forwardHr": forward_hr,
                "forwardPa": forward_pa,
                "forwardBbe": forward_bbe,
                "futureHrPerPa": future_hr_per_pa,
                "futureHr600": future_hr600,
                "hit30Hr600": bool(future_hr600 is not None and future_hr600 >= 30),
                "hit35Hr600": bool(future_hr600 is not None and future_hr600 >= 35),
                "evalNote": miss_note(snapshot_row, forward_pa, produced, min_forward_pa),
            }
        )
    return rows


def top_hit_rates(rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    ranked = sorted([row for row in rows if row.get("matched")], key=lambda row: -number(row.get("b6Air"), -999))[:top_n]
    if not ranked:
        return {"n": 0, "hit30": None, "hit35": None}
    return {
        "n": len(ranked),
        "hit30": sum(1 for row in ranked if row["hit30Hr600"]) / len(ranked),
        "hit35": sum(1 for row in ranked if row["hit35Hr600"]) / len(ranked),
    }


def bucket_result(bucket: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    matched = [row for row in rows if row.get("matched")]
    total_hr = sum(int(row["forwardHr"]) for row in matched)
    total_pa = sum(int(row["forwardPa"]) for row in matched)
    total_bbe = sum(int(row["forwardBbe"]) for row in matched)
    hr_per_pa = rate(total_hr, total_pa)
    return {
        "bucket": bucket,
        "n": len(rows),
        "matched": len(matched),
        "totalForwardHr": total_hr,
        "totalForwardPa": total_pa,
        "totalForwardBbe": total_bbe,
        "futureHrPerPa": hr_per_pa,
        "futureHr600": None if hr_per_pa is None else hr_per_pa * 600,
        "top10": top_hit_rates(rows, 10),
        "top25": top_hit_rates(rows, 25),
        "biggestHits": sorted(matched, key=lambda row: (-(row["futureHr600"] or -1), -number(row.get("b6Air"))))[:10],
        "biggestMisses": sorted(
            [row for row in matched if number(row.get("b6Air")) >= 120 and not row["hit30Hr600"]],
            key=lambda row: (-number(row.get("b6Air")), row.get("player", "")),
        )[:10],
    }


def print_player(row: dict[str, Any]) -> None:
    age = "NA" if row.get("age") is None else f"{row['age']:.1f}"
    print(
        f"{row.get('player', ''):<24} {row.get('team', ''):<3} | age {age} | "
        f"{row.get('bucketLabel', ''):<24} | B6-Air {number(row.get('b6Air')):6.1f} | "
        f"{row.get('forwardHr')} HR / {row.get('forwardPa')} PA | HR/600 {fmt_pace(row.get('futureHrPerPa'))} | "
        f"{row.get('evalNote')}"
    )


def print_bucket(result: dict[str, Any]) -> None:
    print(f"\n{result['bucket']}")
    print(f"Matched: {result['matched']}/{result['n']}")
    print(f"Forward HR/PA: {fmt_rate(result['futureHrPerPa'])} | HR/600: {fmt_pace(result['futureHrPerPa'])}")
    print(f"Totals: {result['totalForwardHr']} HR / {result['totalForwardPa']} PA / {result['totalForwardBbe']} BBE")
    for label in ["top10", "top25"]:
        item = result[label]
        hit30 = "NA" if item["hit30"] is None else f"{item['hit30'] * 100:.1f}%"
        hit35 = "NA" if item["hit35"] is None else f"{item['hit35'] * 100:.1f}%"
        print(f"{label}: n={item['n']} | 30 HR/600 hit rate {hit30} | 35 HR/600 hit rate {hit35}")
    print("Biggest hits:")
    for row in result["biggestHits"]:
        print_player(row)
    print("Biggest misses:")
    for row in result["biggestMisses"]:
        print_player(row)


def main() -> None:
    args = parse_args()
    snapshot_path = args.snapshot_dir / f"snapshot_{args.snapshot_date}.json"
    snapshot = load_json(snapshot_path)
    current_payload = load_json(args.current_data)
    evaluation_date = current_data_date(current_payload, args.evaluation_date)
    elapsed_days = (parse_date(evaluation_date) - parse_date(args.snapshot_date)).days
    print(f"Storm Watch shadow evaluation: {args.snapshot_date} -> {evaluation_date}")
    print(f"Snapshot: {snapshot_path}")
    print(f"Current data: {args.current_data}")
    if elapsed_days < args.min_forward_days:
        print(f"not enough forward window yet: {elapsed_days} days elapsed, need {args.min_forward_days}")
        return
    current = player_lookup(current_payload)
    evaluated = evaluate_rows(snapshot.get("players", []), current, args.min_forward_pa)
    buckets = sorted({row.get("bucketLabel", "Unknown") for row in evaluated})
    for bucket in buckets:
        print_bucket(bucket_result(bucket, [row for row in evaluated if row.get("bucketLabel") == bucket]))


if __name__ == "__main__":
    main()
