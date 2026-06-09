#!/usr/bin/env python3
"""Collect a point-in-time DraftKings MLB salary CSV for shadow analysis.

This script is intentionally internal/shadow-only. It downloads the official
DraftKings CSV for the selected Classic main slate, joins only through the
reviewed DK-to-MLBAM map, and writes immutable dated files.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback, kept defensive.
    ZoneInfo = None  # type: ignore[assignment]


LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=MLB"
CSV_URL = "https://www.draftkings.com/lineup/getavailableplayerscsv"
DEFAULT_CONTEST_TYPE_ID = "9"
DEFAULT_MAP_PATH = Path("data/shadow/dfs-salaries/dk-player-map.csv")
DEFAULT_OUTPUT_DIR = Path("data/shadow/dfs-salaries")


OUTPUT_FIELDS = [
    "captureDate",
    "capturedAtUtc",
    "slateDate",
    "source",
    "sourceUrl",
    "draftGroupId",
    "contestTypeId",
    "selectionReason",
    "position",
    "namePlusId",
    "dkName",
    "dkPlayerId",
    "rosterPosition",
    "salary",
    "gameInfo",
    "gameDateTimeEt",
    "teamAbbrev",
    "opponent",
    "homeAway",
    "avgPointsPerGame",
    "mlbamId",
    "mlbName",
    "joinStatus",
    "joinMethod",
    "joinNote",
]


REVIEW_FIELDS = [
    "slateDate",
    "draftGroupId",
    "contestTypeId",
    "dkPlayerId",
    "dkName",
    "position",
    "rosterPosition",
    "teamAbbrev",
    "salary",
    "gameInfo",
    "reviewReason",
    "mapDkName",
    "mapMlbamId",
    "mapMlbName",
]


MAP_REQUIRED_FIELDS = [
    "dkPlayerId",
    "dkName",
    "mlbamId",
    "mlbName",
    "reviewStatus",
    "reviewedAt",
    "reviewNote",
]


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def eastern_zone() -> dt.tzinfo:
    if ZoneInfo is not None:
        return ZoneInfo("America/New_York")
    return dt.timezone(dt.timedelta(hours=-4), name="ET")


def parse_dk_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    match = re.search(r"/Date\((\d+)\)/", value)
    if not match:
        return None
    timestamp = int(match.group(1)) / 1000
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone(eastern_zone())


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "TheLongBall DFS salary collector"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def regular_contest_name(name: str) -> bool:
    lowered = name.lower()
    excluded = (
        "turbo",
        "night",
        "showdown",
        "qualifier",
        "satellite",
        "snake",
        "single stat",
        "arcade",
    )
    return not any(term in lowered for term in excluded)


def select_main_slate(lobby: dict[str, Any], target_date: dt.date | None) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for contest in lobby.get("Contests", []):
        if contest.get("gameType") != "Classic":
            continue
        if str(contest.get("gameTypeId")) != "2":
            continue
        draft_group = contest.get("dg")
        if not draft_group:
            continue
        start = parse_dk_date(contest.get("sd"))
        if start is None:
            continue
        if target_date is not None and start.date() != target_date:
            continue
        contest["_startEt"] = start
        groups[str(draft_group)].append(contest)

    candidates: list[dict[str, Any]] = []
    for draft_group, contests in groups.items():
        regular = [contest for contest in contests if regular_contest_name(contest.get("n", ""))]
        if not regular:
            continue
        start = min(contest["_startEt"] for contest in contests)
        max_prize = max(float(contest.get("po") or 0) for contest in regular)
        max_entries = max(int(contest.get("m") or 0) for contest in regular)
        min_sort = min(int(contest.get("so") or 0) for contest in regular)
        candidates.append(
            {
                "draftGroupId": draft_group,
                "startEt": start,
                "contestCount": len(contests),
                "regularContestCount": len(regular),
                "maxPrizePool": max_prize,
                "maxEntries": max_entries,
                "minSortOrder": min_sort,
                "sampleContestName": sorted(regular, key=lambda item: int(item.get("so") or 0))[0].get("n", ""),
            }
        )

    if target_date is None and candidates:
        today_et = dt.datetime.now(eastern_zone()).date()
        upcoming_dates = sorted({item["startEt"].date() for item in candidates if item["startEt"].date() >= today_et})
        if upcoming_dates:
            candidates = [item for item in candidates if item["startEt"].date() == upcoming_dates[0]]

    if not candidates:
        date_text = target_date.isoformat() if target_date else "the next available date"
        raise RuntimeError(f"No DraftKings Classic regular MLB slate found for {date_text}.")

    # Tiebreaker: largest regular prize pool, most regular contests, earliest
    # start, then lowest draftGroupId. This favors the main slate while avoiding
    # Turbo/Night/qualifier-only slates.
    candidates.sort(
        key=lambda item: (
            -item["maxPrizePool"],
            -item["regularContestCount"],
            item["startEt"],
            int(item["draftGroupId"]),
        )
    )
    chosen = candidates[0]
    chosen["selectionReason"] = (
        "Selected largest-prize regular Classic MLB draft group after excluding "
        "Turbo/Night/qualifier/satellite/showdown/snake/single-stat slates."
    )
    chosen["candidateCount"] = len(candidates)
    return chosen


def csv_url(draft_group_id: str, contest_type_id: str) -> str:
    query = urllib.parse.urlencode({"contestTypeId": contest_type_id, "draftGroupId": draft_group_id})
    return f"{CSV_URL}?{query}"


def load_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing DK player map: {path}")
    with path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    missing = [field for field in MAP_REQUIRED_FIELDS if field not in (rows[0].keys() if rows else [])]
    if missing:
        raise ValueError(f"DK player map missing required fields: {', '.join(missing)}")
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        dk_id = row.get("dkPlayerId", "").strip()
        if not dk_id:
            continue
        if dk_id in mapping:
            raise ValueError(f"Duplicate dkPlayerId in map: {dk_id}")
        mapping[dk_id] = row
    return mapping


def parse_game_info(game_info: str, team: str) -> dict[str, str]:
    match = re.match(r"(?P<away>[A-Z]+)@(?P<home>[A-Z]+)\s+(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>.+)$", game_info or "")
    if not match:
        return {"gameDateTimeEt": "", "opponent": "", "homeAway": ""}
    away = match.group("away")
    home = match.group("home")
    game_dt = f"{match.group('date')} {match.group('time')}"
    if team == away:
        return {"gameDateTimeEt": game_dt, "opponent": home, "homeAway": "away"}
    if team == home:
        return {"gameDateTimeEt": game_dt, "opponent": away, "homeAway": "home"}
    return {"gameDateTimeEt": game_dt, "opponent": "", "homeAway": ""}


def join_row(
    row: dict[str, str],
    mapping: dict[str, dict[str, str]],
    slate_date: str,
    draft_group_id: str,
    contest_type_id: str,
    selection_reason: str,
    source_url: str,
    captured_at: dt.datetime,
) -> tuple[dict[str, str], dict[str, str] | None]:
    dk_id = row.get("ID", "").strip()
    dk_name = row.get("Name", "").strip()
    mapped = mapping.get(dk_id)
    review: dict[str, str] | None = None

    if mapped is None:
        join_status = "needs_review_unmapped_dk_id"
        join_method = "dk_player_map"
        join_note = "No reviewed DK player map entry; do not auto-guess."
        mlbam_id = ""
        mlb_name = ""
        review_reason = "unmapped_dk_id"
    elif normalize_name(mapped.get("dkName", "")) != normalize_name(dk_name):
        join_status = "needs_review_name_changed"
        join_method = "dk_player_map"
        join_note = f"Mapped DK ID name changed from {mapped.get('dkName', '')} to {dk_name}."
        mlbam_id = ""
        mlb_name = ""
        review_reason = "dk_id_name_changed"
    else:
        join_status = "mapped"
        join_method = "dk_player_map"
        join_note = mapped.get("reviewNote", "")
        mlbam_id = mapped.get("mlbamId", "")
        mlb_name = mapped.get("mlbName", "")
        review_reason = ""

    if review_reason:
        review = {
            "slateDate": slate_date,
            "draftGroupId": draft_group_id,
            "contestTypeId": contest_type_id,
            "dkPlayerId": dk_id,
            "dkName": dk_name,
            "position": row.get("Position", ""),
            "rosterPosition": row.get("Roster Position", ""),
            "teamAbbrev": row.get("TeamAbbrev", ""),
            "salary": row.get("Salary", ""),
            "gameInfo": row.get("Game Info", ""),
            "reviewReason": review_reason,
            "mapDkName": mapped.get("dkName", "") if mapped else "",
            "mapMlbamId": mapped.get("mlbamId", "") if mapped else "",
            "mapMlbName": mapped.get("mlbName", "") if mapped else "",
        }

    game = parse_game_info(row.get("Game Info", ""), row.get("TeamAbbrev", ""))
    output = {
        "captureDate": captured_at.astimezone(eastern_zone()).date().isoformat(),
        "capturedAtUtc": captured_at.astimezone(dt.timezone.utc).isoformat(),
        "slateDate": slate_date,
        "source": "DraftKings official lineup CSV",
        "sourceUrl": source_url,
        "draftGroupId": draft_group_id,
        "contestTypeId": contest_type_id,
        "selectionReason": selection_reason,
        "position": row.get("Position", ""),
        "namePlusId": row.get("Name + ID", ""),
        "dkName": dk_name,
        "dkPlayerId": dk_id,
        "rosterPosition": row.get("Roster Position", ""),
        "salary": row.get("Salary", ""),
        "gameInfo": row.get("Game Info", ""),
        "gameDateTimeEt": game["gameDateTimeEt"],
        "teamAbbrev": row.get("TeamAbbrev", ""),
        "opponent": game["opponent"],
        "homeAway": game["homeAway"],
        "avgPointsPerGame": row.get("AvgPointsPerGame", ""),
        "mlbamId": mlbam_id,
        "mlbName": mlb_name,
        "joinStatus": join_status,
        "joinMethod": join_method,
        "joinNote": join_note,
    }
    return output, review


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def collect(args: argparse.Namespace) -> int:
    target_date = dt.date.fromisoformat(args.slate_date) if args.slate_date else None
    lobby = json.loads(fetch_text(LOBBY_URL))
    chosen = select_main_slate(lobby, target_date)
    slate_date = chosen["startEt"].date().isoformat()
    draft_group_id = str(chosen["draftGroupId"])
    contest_type_id = str(args.contest_type_id)
    source_url = csv_url(draft_group_id, contest_type_id)
    salary_text = fetch_text(source_url)
    salary_rows = list(csv.DictReader(salary_text.splitlines()))
    if not salary_rows:
        raise RuntimeError(f"Downloaded DK CSV for draftGroupId={draft_group_id}, but it had no rows.")

    mapping = load_map(Path(args.map_path))
    captured_at = dt.datetime.now(dt.timezone.utc)
    output_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    for row in salary_rows:
        output, review = join_row(
            row,
            mapping,
            slate_date,
            draft_group_id,
            contest_type_id,
            chosen["selectionReason"],
            source_url,
            captured_at,
        )
        output_rows.append(output)
        if review is not None:
            review_rows.append(review)

    output_dir = Path(args.output_dir)
    output_path = output_dir / f"dk-mlb-{slate_date}.csv"
    review_path = output_dir / f"dk-mlb-{slate_date}-review.csv"

    print(f"Selected draftGroupId={draft_group_id} contestTypeId={contest_type_id}")
    print(f"Slate date: {slate_date}")
    print(f"Sample contest: {chosen['sampleContestName']}")
    print(f"Candidate groups on date: {chosen['candidateCount']}")
    print(f"Rows downloaded: {len(output_rows)}")
    print(f"Review rows: {len(review_rows)}")

    if args.dry_run:
        print(f"Dry run: would write {output_path}")
        if review_rows:
            print(f"Dry run: would write {review_path}")
        return 0

    write_csv(output_path, OUTPUT_FIELDS, output_rows)
    if review_rows:
        write_csv(review_path, REVIEW_FIELDS, review_rows)
    print(f"Wrote {output_path}")
    if review_rows:
        print(f"Wrote {review_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slate-date", help="Slate date to collect, YYYY-MM-DD. Defaults to next available regular Classic slate.")
    parser.add_argument("--contest-type-id", default=DEFAULT_CONTEST_TYPE_ID, help="DraftKings CSV contestTypeId. Default: 9 for MLB Classic.")
    parser.add_argument("--map-path", default=str(DEFAULT_MAP_PATH), help="Reviewed DK player map CSV.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for immutable dated salary files.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and join, but do not write output files.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return collect(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
