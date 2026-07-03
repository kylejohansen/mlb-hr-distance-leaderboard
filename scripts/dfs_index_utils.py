#!/usr/bin/env python3
"""Small read-only utilities for the DFS slate capture index."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean


DEFAULT_INDEX_PATH = Path("data/shadow/dfs-slate-index.csv")
INDEX_COLUMNS = [
    "slate_date",
    "selected_slate_date",
    "draft_group_id",
    "contest_name",
    "slate_type",
    "salary_rows",
    "review_rows",
    "capture_status",
    "captured_at_utc",
    "salary_csv_path",
    "review_csv_path",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the DFS slate capture index.")
    parser.add_argument(
        "--index",
        default=os.environ.get("DFS_SLATE_INDEX_PATH", str(DEFAULT_INDEX_PATH)),
        help=f"Path to DFS slate index CSV. Defaults to {DEFAULT_INDEX_PATH}.",
    )
    parser.add_argument(
        "command",
        choices=("list", "latest", "gaps", "summary"),
        help="Index query to run.",
    )
    return parser.parse_args()


def read_rows(index_path: Path) -> list[dict[str, str]]:
    if not index_path.exists() or index_path.stat().st_size == 0:
        return []

    with index_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != INDEX_COLUMNS:
            print(f"ERROR: unexpected DFS slate index columns: {index_path}", file=sys.stderr)
            raise SystemExit(2)
        return list(reader)


def slate_date(row: dict[str, str]) -> date:
    return date.fromisoformat(row["slate_date"])


def sorted_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: (slate_date(row), row["salary_csv_path"]))


def print_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    writer = csv.DictWriter(sys.stdout, fieldnames=INDEX_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def print_latest(rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    latest = max(rows, key=lambda row: (slate_date(row), row["captured_at_utc"]))
    print_rows([latest])


def print_gaps(rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    dates = {slate_date(row) for row in rows}
    current = min(dates)
    end = max(dates)
    while current <= end:
        if current not in dates:
            print(current.isoformat())
        current += timedelta(days=1)


def int_values(rows: list[dict[str, str]], column: str) -> list[int]:
    values = []
    for row in rows:
        try:
            values.append(int(row[column]))
        except (KeyError, TypeError, ValueError):
            print(f"ERROR: invalid integer in column {column!r}", file=sys.stderr)
            raise SystemExit(2)
    return values


def print_summary(rows: list[dict[str, str]]) -> None:
    print(f"total slates: {len(rows)}")
    if not rows:
        print("date range covered: n/a")
        print("average salary rows: n/a")
        print("min salary rows: n/a")
        print("max salary rows: n/a")
        print("average review rows: n/a")
        return

    dates = [slate_date(row) for row in rows]
    salary_rows = int_values(rows, "salary_rows")
    review_rows = int_values(rows, "review_rows")

    print(f"date range covered: {min(dates).isoformat()} to {max(dates).isoformat()}")
    print(f"average salary rows: {mean(salary_rows):.1f}")
    print(f"min salary rows: {min(salary_rows)}")
    print(f"max salary rows: {max(salary_rows)}")
    print(f"average review rows: {mean(review_rows):.1f}")


def main() -> int:
    args = parse_args()
    rows = read_rows(Path(args.index))

    if args.command == "list":
        print_rows(sorted_rows(rows))
    elif args.command == "latest":
        print_latest(rows)
    elif args.command == "gaps":
        print_gaps(rows)
    elif args.command == "summary":
        print_summary(rows)
    else:
        raise AssertionError(f"Unhandled command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
