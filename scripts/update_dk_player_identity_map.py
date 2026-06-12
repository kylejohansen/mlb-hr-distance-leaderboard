#!/usr/bin/env python3
"""Propose or apply reviewed DraftKings identity-map aliases.

The DK salary collector trusts only reviewed normalized-name/team aliases in
``dk-player-identity-map.csv``. This helper consumes a human-review candidate
CSV and writes either a proposed updated map or, with ``--apply``, updates the
map atomically. Dry-run is the default.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path


DEFAULT_IDENTITY_MAP = Path("data/shadow/dfs-salaries/dk-player-identity-map.csv")

MAP_REQUIRED_FIELDS = [
    "normalizedName",
    "aliasName",
    "teamAbbrev",
    "mlbamId",
    "mlbName",
    "reviewStatus",
    "reviewedAt",
    "reviewNote",
]

CANDIDATE_REQUIRED_FIELDS = [
    "dkName",
    "teamAbbrev",
    "candidateMlbamId",
    "confidence",
]

APPROVAL_FIELDS = (
    "approved",
    "approve",
    "use",
    "include",
    "mapApproved",
    "map_approved",
)

TRUE_VALUES = {"1", "true", "yes", "y", "approved", "approve", "use"}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2, "no_match": 3, "": 9}


def normalize_name(value: str) -> str:
    """Match scripts/collect_dk_salaries.py normalization exactly."""
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", delete=False, dir=path.parent) as file:
        tmp_path = Path(file.name)
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def validate_fields(label: str, fieldnames: list[str], required: list[str]) -> None:
    missing = [field for field in required if field not in fieldnames]
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")


def valid_mlbam_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", (value or "").strip()))


def is_approved(row: dict[str, str]) -> bool:
    for field in APPROVAL_FIELDS:
        if field in row and str(row.get(field, "")).strip().lower() in TRUE_VALUES:
            return True
    return False


def confidence_allowed(row: dict[str, str], args: argparse.Namespace) -> tuple[bool, str]:
    confidence = row.get("confidence", "").strip().lower()
    approved = is_approved(row)
    confidence_rank = CONFIDENCE_ORDER.get(confidence)

    if args.approved_only and not approved:
        return False, "not explicitly approved"

    if confidence_rank is None:
        return False, f"unknown confidence {confidence!r}"

    if confidence in {"high", "medium"}:
        if confidence_rank <= CONFIDENCE_ORDER[args.min_confidence]:
            return True, f"eligible {confidence}-confidence row"
        if args.include_medium:
            return True, "eligible medium row via --include-medium"
        if args.approved_only and approved:
            return True, "eligible medium row via explicit approval"
        return False, "medium confidence requires --include-medium or explicit approval"

    if confidence in {"low", "no_match", ""}:
        return False, f"{confidence or 'blank'} confidence is not eligible"

    return False, f"{confidence} confidence is not eligible"


def candidate_key(row: dict[str, str]) -> tuple[str, str]:
    normalized = row.get("normalizedName", "").strip() or normalize_name(row.get("dkName", ""))
    team = row.get("teamAbbrev", "").strip()
    return normalized, team


def build_new_row(
    fieldnames: list[str],
    candidate: dict[str, str],
    reviewed_at: str,
) -> dict[str, str]:
    normalized, team = candidate_key(candidate)
    mlbam_id = candidate.get("candidateMlbamId", "").strip()
    dk_name = candidate.get("dkName", "").strip()
    candidate_name = candidate.get("candidateName", "").strip() or dk_name
    status_suffix = candidate.get("confidence", "").strip().lower() or "reviewed"

    values = {
        "normalizedName": normalized,
        "aliasName": dk_name,
        "teamAbbrev": team,
        "mlbamId": mlbam_id,
        "mlbName": candidate_name,
        "positionFirstSeen": candidate.get("position", "").strip(),
        "rosterPositionFirstSeen": candidate.get("rosterPosition", "").strip(),
        "firstSeenSlateDate": candidate.get("slateDate", "").strip(),
        "firstSeenDraftGroupId": candidate.get("draftGroupId", "").strip(),
        "firstSeenContestTypeId": candidate.get("contestTypeId", "").strip(),
        "firstSeenDkPlayerId": candidate.get("dkPlayerId", "").strip(),
        "reviewStatus": f"proposed_from_candidate_{status_suffix}",
        "reviewedAt": reviewed_at,
        "reviewNote": (
            "Proposed from review candidates; "
            f"basis={candidate.get('matchBasis', '').strip()}; "
            f"confidence={candidate.get('confidence', '').strip()}; "
            f"sources={candidate.get('candidateSources', '').strip()}"
        ).strip(),
    }
    return {field: values.get(field, "") for field in fieldnames}


def sort_new_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("normalizedName", ""),
            row.get("teamAbbrev", ""),
            row.get("mlbamId", ""),
        ),
    )


def summarize_counter(counter: Counter[str]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter))


def update_map(args: argparse.Namespace) -> int:
    identity_path = Path(args.identity_map)
    candidates_path = Path(args.candidates)
    out_path = Path(args.out) if args.out else identity_path
    report_path = Path(args.report) if args.report else None

    map_fields, existing_rows = read_csv(identity_path)
    candidate_fields, candidate_rows = read_csv(candidates_path)
    validate_fields("identity map", map_fields, MAP_REQUIRED_FIELDS)
    validate_fields("candidate CSV", candidate_fields, CANDIDATE_REQUIRED_FIELDS)

    existing: dict[tuple[str, str], dict[str, str]] = {}
    for row in existing_rows:
        normalized = row.get("normalizedName", "").strip() or normalize_name(row.get("aliasName", ""))
        team = row.get("teamAbbrev", "").strip()
        mlbam_id = row.get("mlbamId", "").strip()
        if not normalized or not team or not mlbam_id:
            raise ValueError(f"Identity map row is missing normalizedName/teamAbbrev/mlbamId: {row}")
        key = (normalized, team)
        if key in existing:
            raise ValueError(f"Duplicate normalizedName/teamAbbrev in identity map: {normalized} / {team}")
        existing[key] = row

    reviewed_at = dt.date.today().isoformat()
    proposed_by_key: dict[tuple[str, str], dict[str, str]] = {}
    proposed_source: dict[tuple[str, str], list[dict[str, str]]] = {}
    counters: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    conflicts: list[str] = []

    for candidate in candidate_rows:
        counters["candidate_rows_read"] += 1
        normalized, team = candidate_key(candidate)
        mlbam_id = candidate.get("candidateMlbamId", "").strip()
        dk_name = candidate.get("dkName", "").strip()

        if not dk_name:
            counters["skipped_missing_name"] += 1
            skip_reasons["missing dkName"] += 1
            continue
        if not team:
            counters["skipped_missing_team"] += 1
            skip_reasons["missing teamAbbrev"] += 1
            continue
        if not valid_mlbam_id(mlbam_id):
            counters["skipped_missing_id"] += 1
            skip_reasons["missing/invalid candidateMlbamId"] += 1
            continue

        allowed, reason = confidence_allowed(candidate, args)
        if not allowed:
            counters["skipped_confidence"] += 1
            skip_reasons[reason] += 1
            continue

        key = (normalized, team)
        existing_row = existing.get(key)
        if existing_row:
            if existing_row.get("mlbamId", "").strip() == mlbam_id:
                counters["skipped_already_present"] += 1
                continue
            counters["conflicts"] += 1
            conflicts.append(
                f"existing conflict: {normalized}/{team} existing={existing_row.get('mlbamId')} "
                f"candidate={mlbam_id} dkName={dk_name}"
            )
            continue

        proposed = proposed_by_key.get(key)
        if proposed:
            if proposed.get("mlbamId") == mlbam_id:
                counters["deduped_duplicate_alias"] += 1
                proposed_source.setdefault(key, []).append(candidate)
                continue
            counters["conflicts"] += 1
            conflicts.append(
                f"candidate conflict: {normalized}/{team} first={proposed.get('mlbamId')} "
                f"candidate={mlbam_id} dkName={dk_name}"
            )
            continue

        new_row = build_new_row(map_fields, candidate, reviewed_at)
        proposed_by_key[key] = new_row
        proposed_source[key] = [candidate]
        counters["proposed_additions"] += 1

    new_rows = sort_new_rows(list(proposed_by_key.values()))
    output_rows = [*existing_rows, *new_rows]

    if args.apply:
        if args.backup:
            timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = identity_path.with_name(f"{identity_path.stem}.{timestamp}.bak{identity_path.suffix}")
            shutil.copy2(identity_path, backup_path)
            counters["backup_created"] += 1
        write_csv_atomic(identity_path, map_fields, output_rows)
        mode = "apply"
        written_map = identity_path
    else:
        write_csv_atomic(out_path, map_fields, output_rows)
        mode = "dry-run"
        written_map = out_path

    report_lines = [
        "DraftKings identity-map update report",
        f"mode: {mode}",
        f"identity_map: {identity_path}",
        f"candidates: {candidates_path}",
        f"written_map: {written_map}",
        f"existing_identity_rows: {len(existing_rows)}",
        f"candidate_rows_read: {len(candidate_rows)}",
        f"proposed_additions: {counters['proposed_additions']}",
        f"skipped_already_present: {counters['skipped_already_present']}",
        f"skipped_confidence: {counters['skipped_confidence']}",
        f"skipped_missing_id: {counters['skipped_missing_id']}",
        f"skipped_missing_name: {counters['skipped_missing_name']}",
        f"skipped_missing_team: {counters['skipped_missing_team']}",
        f"deduped_duplicate_alias: {counters['deduped_duplicate_alias']}",
        f"conflicts: {counters['conflicts']}",
        f"skip_reasons: {summarize_counter(skip_reasons)}",
        "",
        "Proposed additions:",
    ]
    for row in new_rows:
        report_lines.append(
            f"- {row.get('aliasName')} | {row.get('teamAbbrev')} | {row.get('mlbamId')} | "
            f"{row.get('mlbName')} | {row.get('reviewStatus')}"
        )
    if conflicts:
        report_lines.extend(["", "Conflicts:"])
        report_lines.extend(f"- {line}" for line in conflicts)

    report_text = "\n".join(report_lines) + "\n"
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text)
    else:
        print(report_text, end="")

    print(f"Mode: {mode}")
    print(f"Existing identity-map rows: {len(existing_rows)}")
    print(f"Candidate rows read: {len(candidate_rows)}")
    print(f"Proposed additions: {counters['proposed_additions']}")
    print(f"Skipped already present: {counters['skipped_already_present']}")
    print(f"Skipped confidence: {counters['skipped_confidence']}")
    print(f"Skipped missing IDs: {counters['skipped_missing_id']}")
    print(f"Conflicts: {counters['conflicts']}")
    print(f"Wrote map: {written_map}")
    if report_path:
        print(f"Wrote report: {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-map", default=str(DEFAULT_IDENTITY_MAP), help="Reviewed DK identity map CSV.")
    parser.add_argument("--candidates", required=True, help="Reviewed candidate CSV.")
    parser.add_argument("--out", help="Proposed map output path for dry-run mode.")
    parser.add_argument("--report", help="Text report output path.")
    parser.add_argument("--min-confidence", default="high", choices=["high", "medium"], help="Minimum confidence threshold. Conservative default: high.")
    parser.add_argument("--include-medium", action="store_true", help="Allow medium-confidence rows without explicit approval.")
    parser.add_argument("--approved-only", action="store_true", help="Only include rows with an explicit approved/approve/use/include truthy column.")
    parser.add_argument("--apply", action="store_true", help="Modify --identity-map atomically instead of writing a proposed map.")
    parser.add_argument("--backup", action="store_true", help="When applying, create a timestamped backup next to the identity map.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.apply and not args.out:
        parser.error("--out is required unless --apply is passed")
    if args.backup and not args.apply:
        parser.error("--backup is only valid with --apply")
    try:
        return update_map(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
