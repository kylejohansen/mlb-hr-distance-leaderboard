#!/usr/bin/env python3
"""Backfill the DFS slate index from committed DraftKings salary files."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


SALARY_DIR = Path("data/shadow/dfs-salaries")
INDEX_PATH = Path("data/shadow/dfs-slate-index.csv")
SALARY_FILE_RE = re.compile(r"^dk-mlb-(\d{4}-\d{2}-\d{2})\.csv$")
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
    parser = argparse.ArgumentParser(description="Backfill the DFS slate index from existing salary CSVs.")
    parser.add_argument("--dry-run", action="store_true", help="Print rows that would be added without writing.")
    parser.add_argument(
        "--salary-dir",
        default=str(SALARY_DIR),
        help=f"Directory containing DK salary CSVs. Defaults to {SALARY_DIR}.",
    )
    parser.add_argument(
        "--index",
        default=str(INDEX_PATH),
        help=f"DFS slate index CSV path. Defaults to {INDEX_PATH}.",
    )
    return parser.parse_args()


def count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    return max(0, len(rows) - 1)


def read_existing_keys(index_path: Path) -> set[tuple[str, str]]:
    if not index_path.exists() or index_path.stat().st_size == 0:
        return set()

    with index_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != INDEX_COLUMNS:
            raise SystemExit(f"ERROR: unexpected DFS slate index columns: {index_path}")
        return {
            (row.get("selected_slate_date", ""), row.get("salary_csv_path", ""))
            for row in reader
        }


def discover_rows(salary_dir: Path) -> list[dict[str, str]]:
    rows = []
    for salary_path in sorted(salary_dir.glob("dk-mlb-*.csv")):
        match = SALARY_FILE_RE.match(salary_path.name)
        if not match:
            continue

        slate_date = match.group(1)
        review_path = salary_dir / f"dk-mlb-{slate_date}-review.csv"
        if not review_path.exists():
            print(f"Skipping {slate_date}: missing review CSV {review_path}")
            continue

        rows.append(
            {
                "slate_date": slate_date,
                "selected_slate_date": slate_date,
                "draft_group_id": "",
                "contest_name": "",
                "slate_type": "classic",
                "salary_rows": str(count_csv_rows(salary_path)),
                "review_rows": str(count_csv_rows(review_path)),
                "capture_status": "captured",
                "captured_at_utc": "",
                "salary_csv_path": str(salary_path),
                "review_csv_path": str(review_path),
            }
        )
    return sorted(rows, key=lambda row: row["selected_slate_date"])


def write_rows(index_path: Path, rows: list[dict[str, str]]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not index_path.exists() or index_path.stat().st_size == 0
    with index_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_COLUMNS, lineterminator="\n")
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    salary_dir = Path(args.salary_dir)
    index_path = Path(args.index)

    if not salary_dir.exists():
        raise SystemExit(f"ERROR: salary directory does not exist: {salary_dir}")

    existing_keys = read_existing_keys(index_path)
    discovered_rows = discover_rows(salary_dir)
    rows_to_add = [
        row for row in discovered_rows
        if (row["selected_slate_date"], row["salary_csv_path"]) not in existing_keys
    ]

    if args.dry_run:
        print(f"Discovered salary slates: {len(discovered_rows)}")
        print(f"Existing indexed slates: {len(existing_keys)}")
        print(f"Rows that would be added: {len(rows_to_add)}")
        for row in rows_to_add:
            print(
                f"{row['selected_slate_date']}: "
                f"salary_rows={row['salary_rows']} review_rows={row['review_rows']}"
            )
        return 0

    if rows_to_add:
        write_rows(index_path, rows_to_add)

    print(f"Discovered salary slates: {len(discovered_rows)}")
    print(f"Added index rows: {len(rows_to_add)}")
    print(f"Skipped existing rows: {len(discovered_rows) - len(rows_to_add)}")
    print(f"Index path: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
