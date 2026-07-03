#!/usr/bin/env bash
set -euo pipefail

REQUESTED_SLATE_DATE="${1:-${SLATE_DATE:-$(TZ=America/Chicago date +%F)}}"
SLATE_DATE="${REQUESTED_SLATE_DATE}"

OUT_DIR="${OUT_DIR:-data/shadow/dfs-salaries}"
DFS_SLATE_INDEX_PATH="${DFS_SLATE_INDEX_PATH:-data/shadow/dfs-slate-index.csv}"
DFS_SLATE_KPI_PATH="${DFS_SLATE_KPI_PATH:-data/shadow/dfs-slate-kpi.json}"
DFS_SLATE_TYPE="${DFS_SLATE_TYPE:-classic}"
MIN_SALARY_ROWS="${MIN_SALARY_ROWS:-50}"
WARN_SALARY_ROWS="${WARN_SALARY_ROWS:-500}"
WARN_REVIEW_ROWS="${WARN_REVIEW_ROWS:-500}"
WARN_REVIEW_RATIO="${WARN_REVIEW_RATIO:-0.50}"
ALLOW_OVERWRITE="${ALLOW_OVERWRITE:-0}"
ALLOW_EXISTING_SLATE="${ALLOW_EXISTING_SLATE:-0}"
ALLOW_NO_SLATE="${ALLOW_NO_SLATE:-0}"
LOOKAHEAD_DAYS="${LOOKAHEAD_DAYS:-0}"
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

validate_salary_csv_structure() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
required_columns = {
    "captureDate",
    "capturedAtUtc",
    "slateDate",
    "source",
    "sourceUrl",
    "draftGroupId",
    "contestTypeId",
    "position",
    "dkName",
    "dkPlayerId",
    "rosterPosition",
    "salary",
    "gameInfo",
    "teamAbbrev",
    "mlbamId",
    "joinStatus",
}

with path.open(newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        print(f"ERROR: salary CSV missing header: {path}", file=sys.stderr)
        sys.exit(12)

    missing = sorted(required_columns - set(reader.fieldnames))
    if missing:
        print(f"ERROR: salary CSV missing required columns: {', '.join(missing)}", file=sys.stderr)
        sys.exit(12)

    try:
        next(reader)
    except StopIteration:
        print(f"ERROR: salary CSV has no data rows: {path}", file=sys.stderr)
        sys.exit(12)
PY
}

write_outputs() {
  local status="$1"
  local selected_date="$2"
  local salary_csv="$3"
  local review_csv="$4"
  local salary_rows="$5"
  local review_rows="$6"

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "capture_status=${status}"
      echo "requested_slate_date=${REQUESTED_SLATE_DATE}"
      echo "selected_slate_date=${selected_date}"
      echo "slate_date=${selected_date}"
      echo "salary_csv=${salary_csv}"
      echo "review_csv=${review_csv}"
      echo "salary_rows=${salary_rows}"
      echo "review_rows=${review_rows}"
    } >> "${GITHUB_OUTPUT}"
  fi
}

write_summary_table() {
  local message="$1"
  local selected_date="$2"
  local salary_csv="$3"
  local review_csv="$4"
  local salary_rows="$5"
  local review_rows="$6"
  local warning="${7:-}"

  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "## DFS Slate Capture"
      echo
      echo "${message}"
      echo
      echo "| Field | Value |"
      echo "|---|---:|"
      echo "| Requested slate date | ${REQUESTED_SLATE_DATE} |"
      echo "| Selected slate date | ${selected_date} |"
      echo "| Salary rows | ${salary_rows} |"
      echo "| Review rows | ${review_rows} |"
      if [[ -n "${warning}" ]]; then
        echo
        echo "Warnings:"
        echo
        echo "- ${warning}"
      fi
      echo
      echo "Files:"
      echo
      echo "- \`${salary_csv}\`"
      echo "- \`${review_csv}\`"
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
}

write_no_slate_summary() {
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "## DFS Slate Capture"
      echo
      echo "No DraftKings Classic regular MLB slate was available in the requested lookahead window."
      echo
      echo "| Field | Value |"
      echo "|---|---:|"
      echo "| Requested slate date | ${REQUESTED_SLATE_DATE} |"
      echo "| Lookahead days | ${LOOKAHEAD_DAYS} |"
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
}

validate_capture() {
  local salary_rows="$1"
  local review_rows="$2"

  "${PYTHON_BIN}" - "$salary_rows" "$review_rows" "$MIN_SALARY_ROWS" "$WARN_SALARY_ROWS" "$WARN_REVIEW_ROWS" "$WARN_REVIEW_RATIO" <<'PY'
import sys

salary_rows = int(sys.argv[1])
review_rows = int(sys.argv[2])
min_salary_rows = int(sys.argv[3])
warn_salary_rows = int(sys.argv[4])
warn_review_rows = int(sys.argv[5])
warn_review_ratio = float(sys.argv[6])

print(f"Salary rows: {salary_rows}")
print(f"Review rows: {review_rows}")

if salary_rows < min_salary_rows:
    print(f"ERROR: salary rows below hard threshold: {salary_rows} < {min_salary_rows}", file=sys.stderr)
    sys.exit(10)

if salary_rows < warn_salary_rows:
    print(f"WARNING: salary rows below warning threshold: {salary_rows} < {warn_salary_rows}")

if review_rows > warn_review_rows:
    print(f"WARNING: review rows above warning threshold: {review_rows} > {warn_review_rows}")

ratio = review_rows / salary_rows if salary_rows else 1.0
print(f"Review ratio: {ratio:.1%}")

if ratio > warn_review_ratio:
    print(f"WARNING: review ratio above warning threshold: {ratio:.1%} > {warn_review_ratio:.0%}")
PY
}

append_slate_index() {
  local selected_date="$1"
  local salary_rows="$2"
  local review_rows="$3"
  local salary_csv="$4"
  local review_csv="$5"
  local captured_at_utc

  captured_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  "${PYTHON_BIN}" - \
    "${DFS_SLATE_INDEX_PATH}" \
    "${selected_date}" \
    "${selected_date}" \
    "${DFS_SLATE_TYPE}" \
    "${salary_rows}" \
    "${review_rows}" \
    "${captured_at_utc}" \
    "${salary_csv}" \
    "${review_csv}" <<'PY'
import csv
import sys
from pathlib import Path

index_path = Path(sys.argv[1])
slate_date = sys.argv[2]
selected_slate_date = sys.argv[3]
slate_type = sys.argv[4]
salary_rows = sys.argv[5]
review_rows = sys.argv[6]
captured_at_utc = sys.argv[7]
salary_csv_path = sys.argv[8]
review_csv_path = sys.argv[9]

fieldnames = [
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

index_path.parent.mkdir(parents=True, exist_ok=True)
needs_header = not index_path.exists() or index_path.stat().st_size == 0

if not needs_header:
    with index_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != fieldnames:
            print(
                f"ERROR: DFS slate index has unexpected columns: {index_path}",
                file=sys.stderr,
            )
            sys.exit(13)

        for row in reader:
            if (
                row.get("selected_slate_date") == selected_slate_date
                and row.get("salary_csv_path") == salary_csv_path
            ):
                print(
                    "DFS slate index already contains "
                    f"{selected_slate_date} / {salary_csv_path}; skipping append."
                )
                sys.exit(0)

with index_path.open("a", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    if needs_header:
        writer.writeheader()
    writer.writerow(
        {
            "slate_date": slate_date,
            "selected_slate_date": selected_slate_date,
            "draft_group_id": "",
            "contest_name": "",
            "slate_type": slate_type,
            "salary_rows": salary_rows,
            "review_rows": review_rows,
            "capture_status": "captured",
            "captured_at_utc": captured_at_utc,
            "salary_csv_path": salary_csv_path,
            "review_csv_path": review_csv_path,
        }
    )

print(f"Appended DFS slate index row: {index_path}")
PY
}

write_slate_kpi() {
  local selected_date="$1"
  local salary_rows="$2"
  local review_rows="$3"
  local salary_row_deviation_from_500="$4"
  local is_low_volume_slate="$5"

  "${PYTHON_BIN}" - \
    "${DFS_SLATE_KPI_PATH}" \
    "${selected_date}" \
    "${selected_date}" \
    "${salary_rows}" \
    "${review_rows}" \
    "${salary_row_deviation_from_500}" \
    "${is_low_volume_slate}" <<'PY'
import json
import sys
from pathlib import Path

kpi_path = Path(sys.argv[1])
kpi_path.parent.mkdir(parents=True, exist_ok=True)

payload = {
    "slate_date": sys.argv[2],
    "selected_slate_date": sys.argv[3],
    "salary_rows": int(sys.argv[4]),
    "review_rows": int(sys.argv[5]),
    "salary_row_deviation_from_500": int(sys.argv[6]),
    "is_low_volume_slate": sys.argv[7] == "true",
}

with kpi_path.open("w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, sort_keys=True)
    f.write("\n")

print(f"Wrote DFS slate KPI file: {kpi_path}")
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

The literal token {date} will be replaced with each candidate slate date.
MSG
  exit 2
fi

mkdir -p "${OUT_DIR}"

CANDIDATE_DATES=()
while IFS= read -r candidate_date; do
  CANDIDATE_DATES+=("${candidate_date}")
done < <("${PYTHON_BIN}" - "${REQUESTED_SLATE_DATE}" "${LOOKAHEAD_DAYS}" <<'PY'
import datetime as dt
import sys

start = dt.date.fromisoformat(sys.argv[1])
lookahead = int(sys.argv[2])
if lookahead < 0:
    raise ValueError("LOOKAHEAD_DAYS must be non-negative")

for offset in range(lookahead + 1):
    print((start + dt.timedelta(days=offset)).isoformat())
PY
)

ALREADY_CAPTURED_COUNT=0
NO_SLATE_COUNT=0
LAST_ALREADY_DATE=""
LAST_ALREADY_SALARY_CSV=""
LAST_ALREADY_REVIEW_CSV=""
LAST_ALREADY_SALARY_ROWS="0"
LAST_ALREADY_REVIEW_ROWS="0"

for CANDIDATE_DATE in "${CANDIDATE_DATES[@]}"; do
  SALARY_CSV="${OUT_DIR}/dk-mlb-${CANDIDATE_DATE}.csv"
  REVIEW_CSV="${OUT_DIR}/dk-mlb-${CANDIDATE_DATE}-review.csv"

  echo "Running DFS slate capture"
  echo "Requested slate date: ${REQUESTED_SLATE_DATE}"
  echo "Candidate slate date: ${CANDIDATE_DATE}"
  echo "Lookahead days: ${LOOKAHEAD_DAYS}"

  if [[ "${ALLOW_OVERWRITE}" != "1" ]]; then
    if [[ -e "${SALARY_CSV}" || -e "${REVIEW_CSV}" ]]; then
      if [[ "${ALLOW_EXISTING_SLATE}" == "1" ]]; then
        if [[ -s "${SALARY_CSV}" && -s "${REVIEW_CSV}" ]]; then
          validate_salary_csv_structure "${SALARY_CSV}"
          SALARY_ROWS="$(count_csv_rows "${SALARY_CSV}")"
          REVIEW_ROWS="$(count_csv_rows "${REVIEW_CSV}")"

          echo "Existing DraftKings slate files found for ${CANDIDATE_DATE}; skipping this candidate."
          echo "capture_status=already_captured"
          echo "Salary rows: ${SALARY_ROWS}"
          echo "Review rows: ${REVIEW_ROWS}"

          ALREADY_CAPTURED_COUNT=$((ALREADY_CAPTURED_COUNT + 1))
          LAST_ALREADY_DATE="${CANDIDATE_DATE}"
          LAST_ALREADY_SALARY_CSV="${SALARY_CSV}"
          LAST_ALREADY_REVIEW_CSV="${REVIEW_CSV}"
          LAST_ALREADY_SALARY_ROWS="${SALARY_ROWS}"
          LAST_ALREADY_REVIEW_ROWS="${REVIEW_ROWS}"
          continue
        fi

        echo "ERROR: Partial or corrupt existing slate output for ${CANDIDATE_DATE}." >&2
        echo "Expected both non-empty files before treating the slate as already captured:" >&2
        echo "  ${SALARY_CSV}" >&2
        echo "  ${REVIEW_CSV}" >&2
        exit 3
      fi

      echo "ERROR: Refusing to overwrite existing slate files for ${CANDIDATE_DATE}." >&2
      echo "Set ALLOW_OVERWRITE=1 to allow regeneration." >&2
      exit 3
    fi
  fi

  RUN_CMD="${DFS_TRACKER_CMD//\{date\}/${CANDIDATE_DATE}}"
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
      echo "No DraftKings slate was available for ${CANDIDATE_DATE}; trying the next candidate if any."
      echo "capture_status=no_slate"
      NO_SLATE_COUNT=$((NO_SLATE_COUNT + 1))
      continue
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

  validate_salary_csv_structure "${SALARY_CSV}"
  SALARY_ROWS="$(count_csv_rows "${SALARY_CSV}")"
  REVIEW_ROWS="$(count_csv_rows "${REVIEW_CSV}")"
  validate_capture "${SALARY_ROWS}" "${REVIEW_ROWS}"

  SALARY_ROW_WARNING=""
  if [[ "${SALARY_ROWS}" -lt "${WARN_SALARY_ROWS}" ]]; then
    SALARY_ROW_WARNING="Salary rows below warning threshold: ${SALARY_ROWS} < ${WARN_SALARY_ROWS}"
  fi

  AVG_SALARY_ROWS="${SALARY_ROWS}"
  SALARY_ROW_DEVIATION_FROM_500=$((SALARY_ROWS - 500))
  IS_LOW_VOLUME_SLATE="false"
  if [[ "${SALARY_ROWS}" -lt 500 ]]; then
    IS_LOW_VOLUME_SLATE="true"
  fi

  echo "DFS slate capture validation passed."
  echo "capture_status=captured"
  echo "selected_slate_date=${CANDIDATE_DATE}"
  echo "Salary CSV: ${SALARY_CSV}"
  echo "Review CSV: ${REVIEW_CSV}"

  append_slate_index "${CANDIDATE_DATE}" "${SALARY_ROWS}" "${REVIEW_ROWS}" "${SALARY_CSV}" "${REVIEW_CSV}"
  write_slate_kpi "${CANDIDATE_DATE}" "${AVG_SALARY_ROWS}" "${REVIEW_ROWS}" "${SALARY_ROW_DEVIATION_FROM_500}" "${IS_LOW_VOLUME_SLATE}"
  write_outputs "captured" "${CANDIDATE_DATE}" "${SALARY_CSV}" "${REVIEW_CSV}" "${SALARY_ROWS}" "${REVIEW_ROWS}"
  write_summary_table "Captured DraftKings Classic MLB slate." "${CANDIDATE_DATE}" "${SALARY_CSV}" "${REVIEW_CSV}" "${SALARY_ROWS}" "${REVIEW_ROWS}" "${SALARY_ROW_WARNING}"
  exit 0
done

TOTAL_CANDIDATES="${#CANDIDATE_DATES[@]}"

if [[ "${ALREADY_CAPTURED_COUNT}" -eq "${TOTAL_CANDIDATES}" && "${TOTAL_CANDIDATES}" -gt 0 ]]; then
  echo "All candidate slate files already exist; treating as an already-captured no-op."
  echo "capture_status=already_captured"
  echo "selected_slate_date=${LAST_ALREADY_DATE}"
  echo "Salary rows: ${LAST_ALREADY_SALARY_ROWS}"
  echo "Review rows: ${LAST_ALREADY_REVIEW_ROWS}"

  write_outputs \
    "already_captured" \
    "${LAST_ALREADY_DATE}" \
    "${LAST_ALREADY_SALARY_CSV}" \
    "${LAST_ALREADY_REVIEW_CSV}" \
    "${LAST_ALREADY_SALARY_ROWS}" \
    "${LAST_ALREADY_REVIEW_ROWS}"
  write_summary_table \
    "All candidate slate files already exist; no new capture was run." \
    "${LAST_ALREADY_DATE}" \
    "${LAST_ALREADY_SALARY_CSV}" \
    "${LAST_ALREADY_REVIEW_CSV}" \
    "${LAST_ALREADY_SALARY_ROWS}" \
    "${LAST_ALREADY_REVIEW_ROWS}"
  exit 0
fi

if [[ "${NO_SLATE_COUNT}" -eq "${TOTAL_CANDIDATES}" && "${TOTAL_CANDIDATES}" -gt 0 ]]; then
  echo "No DraftKings slate was available for any candidate date."
  echo "capture_status=no_slate"

  write_outputs "no_slate" "" "" "" "0" "0"
  write_no_slate_summary
  exit 0
fi

echo "No new DraftKings slate was captured across the lookahead window."
echo "capture_status=already_captured"
write_outputs "already_captured" "${LAST_ALREADY_DATE}" "${LAST_ALREADY_SALARY_CSV}" "${LAST_ALREADY_REVIEW_CSV}" "${LAST_ALREADY_SALARY_ROWS}" "${LAST_ALREADY_REVIEW_ROWS}"
write_summary_table "No new slate was captured across the lookahead window." "${LAST_ALREADY_DATE}" "${LAST_ALREADY_SALARY_CSV}" "${LAST_ALREADY_REVIEW_CSV}" "${LAST_ALREADY_SALARY_ROWS}" "${LAST_ALREADY_REVIEW_ROWS}"
