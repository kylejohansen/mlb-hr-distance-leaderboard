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
ALLOW_EXISTING_SLATE="${ALLOW_EXISTING_SLATE:-0}"
ALLOW_NO_SLATE="${ALLOW_NO_SLATE:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NO_SLATE_MESSAGE="No DraftKings Classic regular MLB slate found for"

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
    if [[ "${ALLOW_EXISTING_SLATE}" == "1" ]]; then
      if [[ -s "${SALARY_CSV}" && -s "${REVIEW_CSV}" ]]; then
        SALARY_ROWS="$(count_csv_rows "${SALARY_CSV}")"
        REVIEW_ROWS="$(count_csv_rows "${REVIEW_CSV}")"

        echo "Existing DraftKings slate files found for ${SLATE_DATE}; treating as an already-captured no-op."
        echo "capture_status=already_captured"
        echo "Salary rows: ${SALARY_ROWS}"
        echo "Review rows: ${REVIEW_ROWS}"
        echo "Salary CSV: ${SALARY_CSV}"
        echo "Review CSV: ${REVIEW_CSV}"

        if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
          {
            echo "capture_status=already_captured"
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
            echo "Slate files already exist for \`${SLATE_DATE}\`; no new capture was run."
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

        exit 0
      fi

      echo "ERROR: Partial or corrupt existing slate output for ${SLATE_DATE}." >&2
      echo "Expected both non-empty files before treating the slate as already captured:" >&2
      echo "  ${SALARY_CSV}" >&2
      echo "  ${REVIEW_CSV}" >&2
      exit 3
    fi

    echo "ERROR: Refusing to overwrite existing slate files for ${SLATE_DATE}." >&2
    echo "Set ALLOW_OVERWRITE=1 to allow regeneration." >&2
    exit 3
  fi
fi

RUN_CMD="${DFS_TRACKER_CMD//\{date\}/${SLATE_DATE}}"

echo "Running DFS slate capture"
echo "Slate date: ${SLATE_DATE}"
echo "Command: ${RUN_CMD}"

set +e
TRACKER_OUTPUT="$(bash -lc "${RUN_CMD}" 2>&1)"
TRACKER_STATUS=$?
set -e

if [[ -n "${TRACKER_OUTPUT}" ]]; then
  printf '%s\n' "${TRACKER_OUTPUT}"
fi

if [[ "${TRACKER_STATUS}" -ne 0 ]]; then
  if [[ "${ALLOW_NO_SLATE}" == "1" && "${TRACKER_OUTPUT}" == *"${NO_SLATE_MESSAGE}"* ]]; then
    echo "No DraftKings slate was available for ${SLATE_DATE}; treating as a soft no-slate result."
    echo "capture_status=no_slate"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
      {
        echo "capture_status=no_slate"
        echo "slate_date=${SLATE_DATE}"
        echo "salary_csv=${SALARY_CSV}"
        echo "review_csv=${REVIEW_CSV}"
        echo "salary_rows=0"
        echo "review_rows=0"
      } >> "${GITHUB_OUTPUT}"
    fi

    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
      {
        echo "## DFS Slate Capture"
        echo
        echo "No DraftKings Classic regular MLB slate was available for \`${SLATE_DATE}\`."
        echo
        echo "The collector reported:"
        echo
        echo '```text'
        printf '%s\n' "${TRACKER_OUTPUT}"
        echo '```'
      } >> "${GITHUB_STEP_SUMMARY}"
    fi

    exit 0
  fi

  exit "${TRACKER_STATUS}"
fi

if [[ ! -s "${SALARY_CSV}" ]]; then
  echo "ERROR: Missing or empty salary CSV: ${SALARY_CSV}" >&2
  exit 4
fi

if [[ ! -s "${REVIEW_CSV}" ]]; then
  echo "ERROR: Missing or empty review CSV: ${REVIEW_CSV}" >&2
  exit 5
fi

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
echo "capture_status=captured"
echo "Salary CSV: ${SALARY_CSV}"
echo "Review CSV: ${REVIEW_CSV}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "capture_status=captured"
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
