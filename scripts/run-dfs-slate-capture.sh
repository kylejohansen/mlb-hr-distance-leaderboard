#!/usr/bin/env bash
set -euo pipefail

SLATE_DATE="${1:-${SLATE_DATE:-$(TZ=America/Chicago date +%F)}}"

OUT_DIR="${OUT_DIR:-data/shadow/dfs-salaries}"
SALARY_CSV="${OUT_DIR}/dk-mlb-${SLATE_DATE}.csv"
REVIEW_CSV="${OUT_DIR}/dk-mlb-${SLATE_DATE}-review.csv"

MIN_SALARY_ROWS="${MIN_SALARY_ROWS:-500}"
WARN_REVIEW_ROWS="${WARN_REVIEW_ROWS:-500}"
WARN_REVIEW_RATIO="${WARN_REVIEW_RATIO:-0.50}"
ALLOW_OVERWRITE="${ALLOW_OVERWRITE:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -z "${DFS_TRACKER_CMD:-}" ]]; then
  cat >&2 <<MSG
ERROR: DFS_TRACKER_CMD is required.

Set it to the command that performs the slate capture.

Examples:
  DFS_TRACKER_CMD='python -m your_tracker --date {date}'
  DFS_TRACKER_CMD='npm run dfs:tracker -- --date {date}'
  DFS_TRACKER_CMD='make dfs-slate DATE={date}'

The literal token {date} will be replaced with ${SLATE_DATE}.
MSG
  exit 2
fi

mkdir -p "${OUT_DIR}"

if [[ "${ALLOW_OVERWRITE}" != "1" ]]; then
  if [[ -e "${SALARY_CSV}" || -e "${REVIEW_CSV}" ]]; then
    echo "ERROR: Refusing to overwrite existing slate files for ${SLATE_DATE}." >&2
    echo "Set ALLOW_OVERWRITE=1 to allow regeneration." >&2
    exit 3
  fi
fi

RUN_CMD="${DFS_TRACKER_CMD//\{date\}/${SLATE_DATE}}"

echo "Running DFS slate capture"
echo "Slate date: ${SLATE_DATE}"
echo "Command: ${RUN_CMD}"

bash -lc "${RUN_CMD}"

if [[ ! -s "${SALARY_CSV}" ]]; then
  echo "ERROR: Missing or empty salary CSV: ${SALARY_CSV}" >&2
  exit 4
fi

if [[ ! -s "${REVIEW_CSV}" ]]; then
  echo "ERROR: Missing or empty review CSV: ${REVIEW_CSV}" >&2
  exit 5
fi

count_csv_rows() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(newline="", encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))

# Assumes one header row.
print(max(0, len(rows) - 1))
PY
}

SALARY_ROWS="$(count_csv_rows "${SALARY_CSV}")"
REVIEW_ROWS="$(count_csv_rows "${REVIEW_CSV}")"

"${PYTHON_BIN}" - "$SALARY_ROWS" "$REVIEW_ROWS" "$MIN_SALARY_ROWS" "$WARN_REVIEW_ROWS" "$WARN_REVIEW_RATIO" <<'PY'
import sys

salary_rows = int(sys.argv[1])
review_rows = int(sys.argv[2])
min_salary_rows = int(sys.argv[3])
warn_review_rows = int(sys.argv[4])
warn_review_ratio = float(sys.argv[5])

print(f"Salary rows: {salary_rows}")
print(f"Review rows: {review_rows}")

if salary_rows < min_salary_rows:
    print(f"ERROR: salary rows below threshold: {salary_rows} < {min_salary_rows}", file=sys.stderr)
    sys.exit(10)

if review_rows > warn_review_rows:
    print(f"WARNING: review rows above warning threshold: {review_rows} > {warn_review_rows}")

ratio = review_rows / salary_rows if salary_rows else 1.0
print(f"Review ratio: {ratio:.1%}")

if ratio > warn_review_ratio:
    print(f"WARNING: review ratio above warning threshold: {ratio:.1%} > {warn_review_ratio:.0%}")
PY

echo "DFS slate capture validation passed."
echo "Salary CSV: ${SALARY_CSV}"
echo "Review CSV: ${REVIEW_CSV}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "slate_date=${SLATE_DATE}"
    echo "salary_csv=${SALARY_CSV}"
    echo "review_csv=${REVIEW_CSV}"
    echo "salary_rows=${SALARY_ROWS}"
    echo "review_rows=${REVIEW_ROWS}"
  } >> "${GITHUB_OUTPUT}"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## DFS Slate Capture"
    echo
    echo "| Field | Value |"
    echo "|---|---:|"
    echo "| Slate date | ${SLATE_DATE} |"
    echo "| Salary rows | ${SALARY_ROWS} |"
    echo "| Review rows | ${REVIEW_ROWS} |"
    echo
    echo "Files:"
    echo
    echo "- \`${SALARY_CSV}\`"
    echo "- \`${REVIEW_CSV}\`"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
