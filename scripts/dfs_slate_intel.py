#!/usr/bin/env python3
"""Generate a lightweight DFS slate intelligence report."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INDEX_PATH = Path("data/shadow/dfs-slate-index.csv")
DEFAULT_OUTPUT_DIR = Path("data/shadow/dfs-intel")
DEFAULT_SALARY_DIR = Path("data/shadow/dfs-salaries")
DK_EXPECTED_COLUMNS = {
    "dkName",
    "salary",
    "rosterPosition",
    "position",
    "teamAbbrev",
    "gameInfo",
}
LONG_BALL_METRICS = [
    ("lbi", "LBI"),
    ("currentLbi", "LBI"),
    ("longballIndex", "Longball Index"),
    ("thumpIndex", "Thunder / Thump Index"),
    ("hrWindowThunderRate", "HR-window thunder rate"),
    ("barrelRate", "Barrel rate"),
    ("xhr", "Expected HR"),
]
SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DFS slate intelligence.")
    parser.add_argument("--slate-date", help="Captured slate date to report, YYYY-MM-DD.")
    parser.add_argument("--write", action="store_true", help="Write JSON and Markdown reports.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum rows in ranked boards.")
    parser.add_argument(
        "--index",
        default=os.environ.get("DFS_SLATE_INDEX_PATH", str(DEFAULT_INDEX_PATH)),
        help=f"DFS slate index path. Defaults to {DEFAULT_INDEX_PATH}.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("DFS_INTEL_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)),
        help=f"Report output directory. Defaults to {DEFAULT_OUTPUT_DIR}.",
    )
    return parser.parse_args()


def friendly_exit(message: str) -> int:
    print(message)
    return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_index(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv(path)


def selected_date_from_row(row: dict[str, str]) -> str:
    return row.get("selected_slate_date") or row.get("slate_date", "")


def resolve_salary_file(index_rows: list[dict[str, str]], slate_date: str | None) -> tuple[str, Path] | None:
    captured_rows = [row for row in index_rows if row.get("capture_status", "captured") == "captured"]

    if slate_date:
        for row in captured_rows:
            if selected_date_from_row(row) == slate_date or row.get("slate_date") == slate_date:
                salary_path = row.get("salary_csv_path") or str(DEFAULT_SALARY_DIR / f"dk-mlb-{slate_date}.csv")
                return slate_date, Path(salary_path)
        return slate_date, DEFAULT_SALARY_DIR / f"dk-mlb-{slate_date}.csv"

    if not captured_rows:
        return None

    latest = max(
        captured_rows,
        key=lambda row: (
            selected_date_from_row(row),
            row.get("captured_at_utc", ""),
            row.get("salary_csv_path", ""),
        ),
    )
    selected_date = selected_date_from_row(latest)
    return selected_date, Path(latest.get("salary_csv_path") or DEFAULT_SALARY_DIR / f"dk-mlb-{selected_date}.csv")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"['’`.-]", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = SUFFIX_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_positions(value: str) -> list[str]:
    parts = re.split(r"[/,]", value or "")
    return [part.strip() for part in parts if part.strip()]


def is_pitcher(row: dict[str, str]) -> bool:
    positions = set(split_positions(row.get("rosterPosition") or row.get("position") or ""))
    raw_position = (row.get("position") or "").upper()
    return "P" in positions or raw_position in {"P", "SP", "RP"}


def to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def median(values: list[int]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def metric_candidate_paths(slate_date: str) -> list[Path]:
    year = slate_date[:4]
    paths = [
        Path(f"public/data/longball-index-{year}.json"),
        Path("public/data/hr-distance-latest.json"),
        Path("public/data/longball-index-2026.json"),
    ]
    paths.extend(sorted(Path("public/data/snapshots").glob(f"lbi-{year}-*.json"), reverse=True))
    seen: set[Path] = set()
    unique = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def load_metric_source(slate_date: str, warnings: list[str]) -> dict[str, Any] | None:
    for path in metric_candidate_paths(slate_date):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warnings.append(f"Could not parse Long Ball metric source {path}: {exc}")
            continue

        players = data.get("players") if isinstance(data, dict) else None
        if not isinstance(players, list):
            continue

        metric_key = None
        metric_label = None
        for candidate_key, label in LONG_BALL_METRICS:
            if any(to_float(player.get(candidate_key)) is not None for player in players if isinstance(player, dict)):
                metric_key = candidate_key
                metric_label = label
                break

        if metric_key:
            return {
                "path": str(path),
                "metric_key": metric_key,
                "metric_label": metric_label,
                "players": [player for player in players if isinstance(player, dict)],
            }

    warnings.append("No usable Long Ball hitter metric source was found; generated salary-only report.")
    return None


def build_metric_indexes(metric_source: dict[str, Any] | None) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_name_team: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not metric_source:
        return by_name_team, by_name

    for player in metric_source["players"]:
        name = normalize_name(str(player.get("player") or player.get("name") or ""))
        team = str(player.get("team") or "").upper()
        if not name:
            continue
        by_name[name].append(player)
        if team:
            by_name_team[(name, team)].append(player)
    return by_name_team, by_name


def match_metric_player(
    dk_row: dict[str, str],
    by_name_team: dict[tuple[str, str], list[dict[str, Any]]],
    by_name: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str, str | None]:
    names = [dk_row.get("mlbName") or "", dk_row.get("dkName") or ""]
    team = (dk_row.get("teamAbbrev") or "").upper()
    normalized_names = []
    for name in names:
        normalized = normalize_name(name)
        if normalized and normalized not in normalized_names:
            normalized_names.append(normalized)

    for normalized in normalized_names:
        team_matches = by_name_team.get((normalized, team), [])
        if len(team_matches) == 1:
            return team_matches[0], "name_team", None
        if len(team_matches) > 1:
            return None, "ambiguous", f"{dk_row.get('dkName', '')} ({team}) matched multiple Long Ball rows by name/team"

    for normalized in normalized_names:
        name_matches = by_name.get(normalized, [])
        if len(name_matches) == 1:
            return name_matches[0], "name_only", None
        if len(name_matches) > 1:
            return None, "ambiguous", f"{dk_row.get('dkName', '')} ({team}) matched multiple Long Ball rows by name"

    return None, "unmatched", None


def salary_value(row: dict[str, str]) -> int:
    return to_int(row.get("salary")) or 0


def row_name(row: dict[str, str]) -> str:
    return row.get("dkName") or row.get("name") or row.get("mlbName") or ""


def compact_player(row: dict[str, str]) -> dict[str, Any]:
    return {
        "player": row_name(row),
        "team": row.get("teamAbbrev", ""),
        "positions": row.get("rosterPosition") or row.get("position") or "",
        "salary": salary_value(row),
        "game_info": row.get("gameInfo", ""),
    }


def salary_structure(rows: list[dict[str, str]], limit: int) -> dict[str, Any]:
    by_position: dict[str, list[dict[str, str]]] = defaultdict(list)
    cheap_by_position: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        positions = split_positions(row.get("rosterPosition") or row.get("position") or "UNK") or ["UNK"]
        for position in positions:
            by_position[position].append(row)
            cheap_cutoff = 7000 if position == "P" or is_pitcher(row) else 3000
            if salary_value(row) and salary_value(row) <= cheap_cutoff:
                cheap_by_position[position].append(row)

    return {
        "top_salaries_overall": [
            compact_player(row) for row in sorted(rows, key=salary_value, reverse=True)[:limit]
        ],
        "top_salaries_by_position": {
            position: [compact_player(row) for row in sorted(position_rows, key=salary_value, reverse=True)[: min(5, limit)]]
            for position, position_rows in sorted(by_position.items())
        },
        "salary_pool_notes": {
            position: [compact_player(row) for row in sorted(position_rows, key=salary_value)[: min(5, limit)]]
            for position, position_rows in sorted(cheap_by_position.items())
        },
    }


def build_overlay(
    hitters: list[dict[str, str]],
    metric_source: dict[str, Any] | None,
    limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, str]], list[str]]:
    by_name_team, by_name = build_metric_indexes(metric_source)
    metric_key = metric_source["metric_key"] if metric_source else None
    metric_label = metric_source["metric_label"] if metric_source else None
    matched = []
    unmatched = []
    ambiguous = []

    for row in hitters:
        metric_row, match_quality, ambiguity = match_metric_player(row, by_name_team, by_name)
        if ambiguity:
            ambiguous.append(ambiguity)

        score = to_float(metric_row.get(metric_key)) if metric_row and metric_key else None
        if metric_row and score is not None:
            salary = salary_value(row)
            matched.append(
                {
                    "player": row_name(row),
                    "team": row.get("teamAbbrev", ""),
                    "positions": row.get("rosterPosition") or row.get("position") or "",
                    "salary": salary,
                    "long_ball_score": round(score, 3),
                    "metric_name": metric_label,
                    "value_score": round(score / (salary / 1000), 3) if salary else None,
                    "match_quality": match_quality,
                    "metric_player": metric_row.get("player", ""),
                }
            )
        else:
            unmatched.append(
                {
                    "player": row_name(row),
                    "team": row.get("teamAbbrev", ""),
                    "positions": row.get("rosterPosition") or row.get("position") or "",
                }
            )

    top_bats = sorted(matched, key=lambda item: item["long_ball_score"], reverse=True)[:limit]
    values = sorted(
        [item for item in matched if item.get("value_score") is not None],
        key=lambda item: item["value_score"],
        reverse=True,
    )[:limit]
    overlay = {
        "metric_name": metric_label,
        "matched_hitter_count": len(matched),
        "unmatched_hitter_count": len(unmatched),
        "match_rate": round(len(matched) / len(hitters), 4) if hitters else 0.0,
        "top_long_ball_bats": top_bats,
        "top_salary_adjusted_values": values,
    }
    return overlay, matched, {"top_bats": top_bats, "values": values}, unmatched, ambiguous


def build_stack_watch(hitters: list[dict[str, str]], matched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched_by_key = {(item["player"], item["team"], item["salary"]): item for item in matched}
    teams: dict[str, list[dict[str, str]]] = defaultdict(list)
    for hitter in hitters:
        teams[hitter.get("teamAbbrev", "")].append(hitter)

    stack_rows = []
    for team, team_hitters in teams.items():
        salaries = [salary_value(row) for row in team_hitters if salary_value(row)]
        team_matches = []
        for row in team_hitters:
            key = (row_name(row), team, salary_value(row))
            if key in matched_by_key:
                team_matches.append(matched_by_key[key])
        scores = [item["long_ball_score"] for item in team_matches]
        stack_rows.append(
            {
                "team": team,
                "hitter_count": len(team_hitters),
                "average_salary": round(statistics.mean(salaries), 1) if salaries else None,
                "max_salary": max(salaries) if salaries else None,
                "matched_long_ball_hitters": len(team_matches),
                "average_long_ball_score": round(statistics.mean(scores), 2) if scores else None,
                "top_3_long_ball_bats": [
                    {
                        "player": item["player"],
                        "salary": item["salary"],
                        "long_ball_score": item["long_ball_score"],
                    }
                    for item in sorted(team_matches, key=lambda item: item["long_ball_score"], reverse=True)[:3]
                ],
            }
        )

    return sorted(
        stack_rows,
        key=lambda row: (
            row["average_long_ball_score"] is not None,
            row["average_long_ball_score"] or 0,
            row["hitter_count"],
            row["max_salary"] or 0,
        ),
        reverse=True,
    )


def pitcher_board(rows: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
    pitchers = [row for row in rows if is_pitcher(row)]
    return [
        {
            "player": row_name(row),
            "team": row.get("teamAbbrev", ""),
            "salary": salary_value(row),
            "game_info": row.get("gameInfo", ""),
            "avg_dk_points": to_float(row.get("avgPointsPerGame")),
        }
        for row in sorted(pitchers, key=salary_value, reverse=True)[:limit]
    ]


def build_report(slate_date: str, salary_csv_path: Path, rows: list[dict[str, str]], limit: int) -> dict[str, Any]:
    warnings = []
    fieldnames = set(rows[0].keys()) if rows else set()
    missing_columns = sorted(DK_EXPECTED_COLUMNS - fieldnames)
    if missing_columns:
        warnings.append(f"DK salary CSV missing expected columns: {', '.join(missing_columns)}")

    metric_source = load_metric_source(slate_date, warnings)
    hitters = [row for row in rows if not is_pitcher(row)]
    salaries = [salary_value(row) for row in rows if salary_value(row)]
    teams = sorted({row.get("teamAbbrev", "") for row in rows if row.get("teamAbbrev")})
    games = sorted({row.get("gameInfo", "") for row in rows if row.get("gameInfo")})
    position_counts = Counter()
    for row in rows:
        for position in split_positions(row.get("rosterPosition") or row.get("position") or "UNK") or ["UNK"]:
            position_counts[position] += 1

    overlay, matched, power_boards, unmatched, ambiguous = build_overlay(hitters, metric_source, limit)
    stack_rows = build_stack_watch(hitters, matched)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "slate_date": slate_date,
        "salary_csv_path": str(salary_csv_path),
        "metric_source": metric_source["path"] if metric_source else "",
        "metric_name": metric_source["metric_label"] if metric_source else "",
        "summary": {
            "player_rows": len(rows),
            "teams": len(teams),
            "games": len(games),
            "positions": dict(sorted(position_counts.items())),
            "salary_min": min(salaries) if salaries else 0,
            "salary_median": median(salaries) or 0,
            "salary_max": max(salaries) if salaries else 0,
            "matched_hitters": overlay["matched_hitter_count"],
            "unmatched_hitters": overlay["unmatched_hitter_count"],
            "match_rate": overlay["match_rate"],
        },
        "slate_overview": {
            "teams_represented": teams,
            "games_represented": games,
        },
        "salary_structure": salary_structure(rows, limit),
        "long_ball_power_overlay": overlay,
        "stack_watch_lite": stack_rows,
        "power_value_board": power_boards["values"],
        "pitcher_salary_board": pitcher_board(rows, limit),
        "data_quality": {
            "warnings": warnings,
            "missing_columns": missing_columns,
            "unmatched_hitters": unmatched,
            "ambiguous_matches": ambiguous,
            "metric_source_used": metric_source["path"] if metric_source else "",
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    }
    return report


def money(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"${int(value):,}"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(out) + "\n"


def render_markdown(report: dict[str, Any], limit: int) -> str:
    summary = report["summary"]
    salary = report["salary_structure"]
    overlay = report["long_ball_power_overlay"]
    quality = report["data_quality"]
    lines = [
        f"# DFS Slate Intelligence: {report['slate_date']}",
        "",
        "This is a slate intelligence report, not a projections model, ownership model, or lineup optimizer.",
        "",
        "## Slate Overview",
        "",
        f"- Salary file: `{report['salary_csv_path']}`",
        f"- Player rows: {summary['player_rows']}",
        f"- Teams represented: {summary['teams']}",
        f"- Games represented: {summary['games']}",
        f"- Position counts: {summary['positions']}",
        f"- Salary min / median / max: {money(summary['salary_min'])} / {money(summary['salary_median'])} / {money(summary['salary_max'])}",
        f"- Metric source: `{report['metric_source'] or 'none'}`",
        "",
        "## Salary Structure",
        "",
        "### Top Salaries Overall",
        "",
        markdown_table(
            ["Player", "Team", "Pos", "Salary"],
            [[row["player"], row["team"], row["positions"], money(row["salary"])] for row in salary["top_salaries_overall"][:limit]],
        ),
        "### Salary Pool Notes",
        "",
        "These are low-salary pool notes only, not recommendations.",
        "",
    ]

    for position, rows in salary["salary_pool_notes"].items():
        lines.extend(
            [
                f"#### {position}",
                "",
                markdown_table(
                    ["Player", "Team", "Salary"],
                    [[row["player"], row["team"], money(row["salary"])] for row in rows[: min(5, limit)]],
                ),
            ]
        )

    lines.extend(
        [
            "## Long Ball Power Overlay",
            "",
            f"- Metric: {overlay['metric_name'] or 'none'}",
            f"- Matched hitters: {overlay['matched_hitter_count']}",
            f"- Unmatched hitters: {overlay['unmatched_hitter_count']}",
            f"- Match rate: {overlay['match_rate']:.1%}",
            "",
        ]
    )

    if overlay["top_long_ball_bats"]:
        lines.extend(
            [
                "### Top Long Ball Bats",
                "",
                markdown_table(
                    ["Player", "Team", "Pos", "Salary", "Score", "Match"],
                    [
                        [row["player"], row["team"], row["positions"], money(row["salary"]), row["long_ball_score"], row["match_quality"]]
                        for row in overlay["top_long_ball_bats"][:limit]
                    ],
                ),
            ]
        )
    else:
        lines.extend(["_No Long Ball metric matches available._", ""])

    lines.extend(
        [
            "## Stack Watch Lite",
            "",
            markdown_table(
                ["Team", "Hitters", "Avg Salary", "Max Salary", "Matched", "Avg LB Score", "Top Bats"],
                [
                    [
                        row["team"],
                        row["hitter_count"],
                        money(row["average_salary"]),
                        money(row["max_salary"]),
                        row["matched_long_ball_hitters"],
                        row["average_long_ball_score"] if row["average_long_ball_score"] is not None else "n/a",
                        ", ".join(bat["player"] for bat in row["top_3_long_ball_bats"]) or "n/a",
                    ]
                    for row in report["stack_watch_lite"][:limit]
                ],
            ),
            "## Power Value Board",
            "",
        ]
    )

    if report["power_value_board"]:
        lines.append(
            markdown_table(
                ["Player", "Team", "Pos", "Salary", "LB Score", "Value", "Match"],
                [
                    [row["player"], row["team"], row["positions"], money(row["salary"]), row["long_ball_score"], row["value_score"], row["match_quality"]]
                    for row in report["power_value_board"][:limit]
                ],
            )
        )
    else:
        lines.extend(["_Skipped because no Long Ball score was available._", ""])

    lines.extend(
        [
            "## Pitcher Salary Board",
            "",
            markdown_table(
                ["Player", "Team", "Salary", "Game", "Avg DK Pts"],
                [
                    [row["player"], row["team"], money(row["salary"]), row["game_info"], row["avg_dk_points"] if row["avg_dk_points"] is not None else "n/a"]
                    for row in report["pitcher_salary_board"][:limit]
                ],
            ),
            "## Data Quality",
            "",
            f"- Missing DK columns: {quality['missing_columns'] or []}",
            f"- Ambiguous matches: {len(quality['ambiguous_matches'])}",
            f"- Unmatched DK hitters: {len(quality['unmatched_hitters'])}",
            f"- Generated at UTC: {quality['generated_at_utc']}",
        ]
    )

    if quality["warnings"]:
        lines.extend(["", "Warnings:"])
        for warning in quality["warnings"]:
            lines.append(f"- {warning}")

    return "\n".join(lines).rstrip() + "\n"


def print_stdout_summary(report: dict[str, Any], limit: int) -> None:
    summary = report["summary"]
    overlay = report["long_ball_power_overlay"]
    print(f"DFS Slate Intelligence: {report['slate_date']}")
    print(f"Salary file: {report['salary_csv_path']}")
    print(
        "Rows/teams/games: "
        f"{summary['player_rows']} / {summary['teams']} / {summary['games']}"
    )
    print(
        "Salary min/median/max: "
        f"{money(summary['salary_min'])} / {money(summary['salary_median'])} / {money(summary['salary_max'])}"
    )
    print(f"Metric source: {report['metric_source'] or 'none'}")
    print(
        "Long Ball matches: "
        f"{overlay['matched_hitter_count']} matched, {overlay['unmatched_hitter_count']} unmatched "
        f"({overlay['match_rate']:.1%})"
    )

    if overlay["top_long_ball_bats"]:
        print("Top Long Ball bats:")
        for row in overlay["top_long_ball_bats"][: min(5, limit)]:
            print(f"- {row['player']} {row['team']} {money(row['salary'])}: {row['long_ball_score']} ({row['match_quality']})")
    elif report["data_quality"]["warnings"]:
        print(f"Warning: {report['data_quality']['warnings'][0]}")

    if report["power_value_board"]:
        print("Top power values:")
        for row in report["power_value_board"][: min(5, limit)]:
            print(f"- {row['player']} {row['team']} {money(row['salary'])}: value {row['value_score']}")


def write_reports(report: dict[str, Any], output_dir: Path, limit: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"dk-mlb-{report['slate_date']}-intel"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report, limit), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    index_path = Path(args.index)
    index_rows = read_index(index_path)
    resolved = resolve_salary_file(index_rows, args.slate_date)

    if resolved is None:
        return friendly_exit(
            f"No captured DFS slate index rows found at {index_path}. "
            "Run a capture first or pass --slate-date for an existing salary CSV."
        )

    slate_date, salary_csv_path = resolved
    if not salary_csv_path.exists():
        print(f"ERROR: salary CSV is missing or unreadable: {salary_csv_path}", file=sys.stderr)
        return 1

    rows = read_csv(salary_csv_path)
    if not rows:
        print(f"ERROR: salary CSV has no player rows: {salary_csv_path}", file=sys.stderr)
        return 1

    report = build_report(slate_date, salary_csv_path, rows, max(1, args.limit))
    print_stdout_summary(report, max(1, args.limit))

    if args.write:
        json_path, md_path = write_reports(report, Path(args.output_dir), max(1, args.limit))
        print(f"Wrote JSON report: {json_path}")
        print(f"Wrote Markdown report: {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
