#!/usr/bin/env python3
"""Generate The Longball Scouting Report from existing weekly artifacts.

This is a rule-based content generator. It does not use LLM text and does not
make predictive "due" claims. The "Power Gap" section is descriptive: it flags
hitters whose longball-quality indicators are stronger than their current HR
results.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MOVERS_PATH = Path("public/data/weekly-movers-latest.json")
DEFAULT_LBI_PATH = Path("public/data/hr-distance-latest.json")
DEFAULT_HOT_DOG_PATH = Path("public/data/hot-dog-stand-latest.json")
DEFAULT_TALE_DIR = Path("public/data/tale-of-the-tape")
DEFAULT_OUTPUT_PATH = Path("public/data/longball-scouting-report-latest.json")
DEFAULT_REPORT_DIR = Path("content/reports")

SITE_METADATA = {
    "name": "The Long Ball",
    "url": "https://thelongball.app",
    "tagline": "Digging the data behind the distance.",
}

SCOUTING_FIELDS = {
    "stockUp": "Biggest LBI risers from the weekly movers report.",
    "stockDown": "Biggest LBI fallers from the weekly movers report.",
    "powerGap": "Current hitters whose stadium-neutral expected HR total is running ahead of actual HR, with Longball Index support.",
    "powerMirage": "Current hitters whose HR output or Cheapies context is running ahead of LBI quality.",
    "gettingCooked": "Pitchers currently allowing the loudest longball damage by Hot Dog Index/Cooked context.",
    "taleOfTheTapeRecap": "Daily Dong, Hot Dog Robbery, and Cheapest Dong highlights from recent Tale archives.",
}

POWER_GAP_EXPLAINER = (
    "Expected HR running ahead of actual HR among hitters with strong Longball "
    "Index support."
)
POWER_MIRAGE_EXPLAINER = (
    "HR totals getting help from short-porch context, Cheapies, or results "
    "running ahead of longball quality. Descriptive context only."
)
GETTING_COOKED_EXPLAINER = (
    "Pitchers whose Hot Dog damage is climbing by volume, rate, or premium "
    "contact allowed."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate The Longball Scouting Report.")
    parser.add_argument("--weekly-movers", type=Path, default=DEFAULT_MOVERS_PATH, help="Weekly movers JSON path.")
    parser.add_argument("--lbi", type=Path, default=DEFAULT_LBI_PATH, help="Current Longball Index JSON path.")
    parser.add_argument("--hot-dog", type=Path, default=DEFAULT_HOT_DOG_PATH, help="Current Hot Dog Index JSON path.")
    parser.add_argument("--tale-dir", type=Path, default=DEFAULT_TALE_DIR, help="Daily Tale of the Tape archive directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Scouting Report JSON output path.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Generated markdown report directory.")
    parser.add_argument("--limit", type=int, default=8, help="Number of rows per section.")
    parser.add_argument("--recap-days", type=int, default=7, help="Number of recent Tale archive days to include.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(round(number(value, default)))


def pct(value: Any, decimals: int = 1) -> str:
    return f"{number(value) * 100:.{decimals}f}%"


def parse_generated_date(payload: dict[str, Any]) -> datetime:
    value = str(payload.get("generatedAt") or "")
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def percentile_cutoff(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(round((len(ordered) - 1) * percentile), 0), len(ordered) - 1)
    return ordered[index]


def editorial_note(kind: str, row: dict[str, Any]) -> str:
    if kind == "stock_up":
        if number(row.get("lbiChange")) >= 15:
            return "Rising fast"
        if number(row.get("barrelRateChange")) >= 0.03:
            return "Barrels ticking up"
        return "Positive LBI movement"
    if kind == "stock_down":
        if number(row.get("lbiChange")) <= -15:
            return "Sliding"
        if number(row.get("xhrPerBbeChange")) <= -0.015:
            return "xHR/BBE cooling"
        return "LBI moved lower"
    if kind == "power_gap":
        hr = integer(row.get("hr"))
        lbi = number(row.get("longballIndex"))
        xhr_diff = number(row.get("xhrDiff"))
        if hr >= 20 and xhr_diff >= 2:
            return "Big total, bigger expected total"
        if lbi >= 170 and xhr_diff >= 2:
            return "Elite LBI supports the gap"
        if lbi >= 145:
            return "Quality supports the gap"
        if lbi >= 110 and xhr_diff >= 2:
            return "Expected HR ahead of results"
        return "Gap worth watching"
    if kind == "power_mirage":
        actual_doubters = integer(row.get("actualDoubterHr"))
        cheapie_rate = number(row.get("cheapieRate"))
        hr_over_xhr = number(row.get("hrOverXhr"))
        lbi = number(row.get("longballIndex"))
        hr = integer(row.get("hr"))
        if actual_doubters >= 3 or cheapie_rate >= 0.30:
            return "Cheapie-heavy HR total"
        if actual_doubters >= 2:
            return "Wall-scraper context"
        if hr_over_xhr >= 1.5:
            return "HR total ahead of xHR"
        if lbi < 100 and hr >= 6:
            return "Results ahead of LBI"
        if lbi < 110 and hr >= 8:
            return "Power output worth a context check"
        return "Short-porch profile"
    if kind == "getting_cooked":
        no_doubters = integer(row.get("noDoubtersAllowed"))
        hr_capable = integer(row.get("hrCapableBbeAllowed"))
        cooked = number(row.get("cookedPer100Bbe"))
        max_ev = number(row.get("maxExitVelocityAllowed"))
        hdi = number(row.get("hotDogIndex"))
        if hr_capable >= 15:
            return "HR-capable contact piling up"
        if max_ev >= 114:
            return "Loud contact allowed"
        if no_doubters >= 4:
            return "No-doubter damage"
        if cooked >= 240:
            return "Cooked rate elevated"
        if hdi >= 145:
            return "Hot Dog damage high"
        return "Current damage flag"
    return "Notable signal"


def scouting_mover(row: dict[str, Any], kind: str) -> dict[str, Any]:
    output = dict(row)
    output["editorialNote"] = editorial_note(kind, row)
    return output


def power_gap_candidates(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified = [player for player in players if integer(player.get("bbe")) > 0]
    rows = []
    for player in qualified:
        lbi = number(player.get("longballIndex"))
        hr = integer(player.get("hr"))
        xhr_diff = number(player.get("xhrDiff"))
        if xhr_diff >= 1.5 and lbi >= 110 and hr >= 5:
            power_gap_score = xhr_diff * (lbi / 100)
            rows.append(
                {
                    "player": player.get("player", ""),
                    "playerDisplay": f"{player.get('player', '')} · {player.get('team', '')}".strip(" ·"),
                    "team": player.get("team", ""),
                    "playerId": player.get("batter") or player.get("playerId"),
                    "longballIndex": round(lbi, 1),
                    "hr": hr,
                    "xhr": round(number(player.get("xhr")), 1),
                    "xhrDiff": round(xhr_diff, 1),
                    "powerGapScore": round(power_gap_score, 2),
                    "xhrPerBbe": round(number(player.get("xhrPerBbe")), 4),
                    "barrelRate": round(number(player.get("barrelRate")), 4),
                    "editorialNote": editorial_note("power_gap", player),
                }
            )
    return sorted(rows, key=lambda row: (-row["xhrDiff"], -row["longballIndex"], row["player"]))


def power_gap(players: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return power_gap_candidates(players)[:limit]


def compare_power_gap_sorts(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    by_diff = rows[:limit]
    by_score = sorted(rows, key=lambda row: (-row["powerGapScore"], -row["xhrDiff"], row["player"]))[:limit]
    diff_names = [row["player"] for row in by_diff]
    score_names = [row["player"] for row in by_score]
    overlap = len(set(diff_names).intersection(score_names))
    return {
        "sortUsed": "xhrDiff",
        "alternateSort": "powerGapScore",
        "limit": limit,
        "overlap": overlap,
        "changedPlayers": [name for name in score_names if name not in diff_names],
        "recommendation": "Keep xHR Diff sorting for clarity." if overlap >= max(limit - 2, 1) else "Power Gap Score meaningfully changes the list; review before switching.",
    }


def power_mirage(players: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    qualified = [player for player in players if integer(player.get("hr")) >= 5]
    lbi_values = [number(player.get("longballIndex")) for player in qualified]
    lbi_median = percentile_cutoff(lbi_values, 0.50)
    rows = []
    for player in qualified:
        lbi = number(player.get("longballIndex"))
        cheapie_rate = number(player.get("cheapieRate"))
        actual_doubters = integer(player.get("actualDoubterHr"))
        hr = integer(player.get("hr"))
        hr_over_xhr = hr - number(player.get("xhr"))
        if actual_doubters >= 2 or cheapie_rate >= 0.20 or hr_over_xhr >= 1.5 or (hr >= 8 and lbi <= lbi_median):
            mirage_score = (actual_doubters * 1.5) + max(hr_over_xhr, 0) + max(110 - lbi, 0) / 20
            row = {
                "player": player.get("player", ""),
                "playerDisplay": f"{player.get('player', '')} · {player.get('team', '')}".strip(" ·"),
                "team": player.get("team", ""),
                "playerId": player.get("batter") or player.get("playerId"),
                "longballIndex": round(lbi, 1),
                "hr": hr,
                "xhr": round(number(player.get("xhr")), 1),
                "hrOverXhr": round(hr_over_xhr, 1),
                "actualDoubterHr": actual_doubters,
                "cheapieRate": round(cheapie_rate, 4),
                "cheapieSource": player.get("cheapieSource"),
                "mirageScore": round(mirage_score, 2),
            }
            row["editorialNote"] = editorial_note("power_mirage", row)
            rows.append(row)
    return sorted(rows, key=lambda row: (-row["mirageScore"], -row["actualDoubterHr"], -row["hrOverXhr"], row["longballIndex"], row["player"]))[:limit]


def getting_cooked(pitchers: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows = []
    for pitcher in pitchers:
        rows.append(
            {
                "pitcher": pitcher.get("pitcher", ""),
                "pitcherDisplay": f"{pitcher.get('pitcher', '')} · {pitcher.get('team', '')}".strip(" ·"),
                "team": pitcher.get("team", ""),
                "pitcherId": pitcher.get("pitcherId"),
                "hotDogIndex": round(number(pitcher.get("hotDogIndex")), 1),
                "cookedPer100Bbe": round(number(pitcher.get("cookedPer100Bbe")), 1),
                "hrCapableBbeAllowed": integer(pitcher.get("hrCapableBbeAllowed")),
                "noDoubtersAllowed": integer(pitcher.get("noDoubtersAllowed")),
                "mostlyGoneAllowed": integer(pitcher.get("mostlyGoneAllowed")),
                "doubtersAllowed": integer(pitcher.get("doubtersAllowed")),
                "maxExitVelocityAllowed": round(number(pitcher.get("maxExitVelocityAllowed")), 1),
                "editorialNote": editorial_note("getting_cooked", pitcher),
            }
        )
    return sorted(rows, key=lambda row: (-row["hotDogIndex"], -row["cookedPer100Bbe"], row["pitcher"]))[:limit]


def event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    return {
        "eventKey": event.get("eventKey"),
        "gameDate": event.get("gameDate"),
        "batter": event.get("batter"),
        "batterTeam": event.get("batterTeam"),
        "pitcher": event.get("pitcher"),
        "pitcherTeam": event.get("pitcherTeam"),
        "distance": event.get("distance"),
        "exitVelocity": event.get("exitVelocity"),
        "hrCat": event.get("hrCat"),
        "parksCleared": event.get("parksCleared"),
        "eventOutcome": event.get("eventOutcome"),
        "score": event.get("score"),
    }


def tale_recap(tale_dir: Path, days: int, report_date: datetime) -> list[dict[str, Any]]:
    cutoff = report_date.date() - timedelta(days=days)
    archive_paths = []
    for path in sorted(tale_dir.glob("*.json"), reverse=True):
        try:
            game_date = datetime.fromisoformat(path.stem).date()
        except ValueError:
            continue
        if cutoff <= game_date <= report_date.date():
            archive_paths.append(path)
    recap = []
    for path in archive_paths:
        payload = load_json(path)
        recap.append(
            {
                "gameDate": payload.get("gameDate") or path.stem,
                "dailyDong": event_summary(payload.get("dailyDong")),
                "hotDogRobbery": event_summary(payload.get("hotDogRobbery")),
                "cheapestDong": event_summary(payload.get("cheapestDong")),
            }
        )
    return sorted(recap, key=lambda row: row["gameDate"], reverse=True)


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], empty_text: str = "_None this week._") -> str:
    if not rows:
        return f"{empty_text}\n"
    header = "| " + " | ".join(label for label, _ in columns) + " |\n"
    divider = "|" + "|".join("---" for _ in columns) + "|\n"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "")) for _, key in columns) + " |")
    return header + divider + "\n".join(body) + "\n"


def format_tale_line(label: str, event: dict[str, Any] | None) -> str:
    if not event:
        return f"- {label}: no event available"
    parks = event.get("parksCleared")
    parks_text = f" · {parks}/30 parks" if parks is not None else ""
    return (
        f"- {label}: {event.get('batter')} vs. {event.get('pitcher')} — "
        f"{event.get('distance')} ft, {event.get('exitVelocity')} mph, {event.get('hrCat')}{parks_text}"
    )


def write_markdown_report(report_dir: Path, report_date: datetime, report: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{report_date.date().isoformat()}-longball-scouting-report.md"
    tale_lines = []
    for day in report["taleOfTheTapeRecap"]:
        tale_lines.append(f"### {day['gameDate']}")
        tale_lines.append("")
        tale_lines.append(format_tale_line("Daily Dong", day.get("dailyDong")))
        tale_lines.append(format_tale_line("Hot Dog Robbery", day.get("hotDogRobbery")))
        tale_lines.append(format_tale_line("Cheapest Dong", day.get("cheapestDong")))
        tale_lines.append("")

    content = f"""---
title: The Longball Scouting Report
date: {report_date.date().isoformat()}
description: Weekly Longball Index risers, fallers, power signals, pitcher damage, and Tale of the Tape highlights.
---

# The Longball Scouting Report

Generated from weekly Longball Index snapshots and current Long Ball data.
This is rule-based descriptive copy.

## Stock Up

{markdown_table(report["stockUp"], [("Player", "player"), ("Team", "team"), ("LBI", "currentLbi"), ("Change", "lbiChange"), ("Note", "editorialNote")], "_No qualifying LBI risers for this snapshot window._")}
## Stock Down

{markdown_table(report["stockDown"], [("Player", "player"), ("Team", "team"), ("LBI", "currentLbi"), ("Change", "lbiChange"), ("Note", "editorialNote")], "_No qualifying LBI fallers for this snapshot window._")}
## Power Gap

{POWER_GAP_EXPLAINER}

{markdown_table(report["powerGap"], [("Player", "playerDisplay"), ("xHR Diff", "xhrDiff"), ("HR", "hr"), ("LBI", "longballIndex"), ("Note", "editorialNote")])}
## Power Mirage

{POWER_MIRAGE_EXPLAINER}

{markdown_table(report["powerMirage"], [("Player", "playerDisplay"), ("HR OVER xHR", "hrOverXhr"), ("Cheapies", "actualDoubterHr"), ("HR", "hr"), ("LBI", "longballIndex"), ("Note", "editorialNote")])}
## Getting Cooked

{GETTING_COOKED_EXPLAINER}

{markdown_table(report["gettingCooked"], [("Pitcher", "pitcherDisplay"), ("HDI", "hotDogIndex"), ("Cooked / 100", "cookedPer100Bbe"), ("HR-Capable", "hrCapableBbeAllowed"), ("Note", "editorialNote")])}
## Tale of the Tape Recap

{chr(10).join(tale_lines) or "_No Tale archive entries available._"}
"""
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    if not args.weekly_movers.exists():
        print("No weekly movers data found; create a weekly movers report and rerun.")
        return

    movers = load_json(args.weekly_movers)
    lbi = load_json(args.lbi)
    hot_dog = load_json(args.hot_dog) if args.hot_dog.exists() else {"pitchers": []}
    report_date = parse_generated_date(movers)
    players = lbi.get("players") if isinstance(lbi.get("players"), list) else []
    pitchers = hot_dog.get("pitchers") if isinstance(hot_dog.get("pitchers"), list) else []
    power_gap_rows = power_gap_candidates(players)
    power_gap_sort_comparison = compare_power_gap_sorts(power_gap_rows, args.limit)

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "site": SITE_METADATA,
        "dataset": "The Longball Scouting Report",
        "season": movers.get("season") or lbi.get("season"),
        "description": "Rule-based weekly Long Ball content report covering LBI movement, power signals, pitcher damage, and Tale of the Tape highlights.",
        "methodologyVersion": "Scouting Report v0.1",
        "sourceNotes": "Uses weekly movers snapshots, current Longball Index data, current Hot Dog Index data, and archived Tale of the Tape daily features. Power Gap is descriptive, not predictive.",
        "fields": SCOUTING_FIELDS,
        "powerGapExplainer": POWER_GAP_EXPLAINER,
        "powerMirageExplainer": POWER_MIRAGE_EXPLAINER,
        "gettingCookedExplainer": GETTING_COOKED_EXPLAINER,
        "powerGapSortComparison": power_gap_sort_comparison,
        "currentSnapshot": movers.get("currentSnapshot"),
        "previousSnapshot": movers.get("previousSnapshot"),
        "stockUp": [scouting_mover(row, "stock_up") for row in movers.get("biggestLbiRisers", [])[: args.limit]],
        "stockDown": [scouting_mover(row, "stock_down") for row in movers.get("biggestLbiFallers", [])[: args.limit]],
        "powerGap": power_gap_rows[: args.limit],
        "powerMirage": power_mirage(players, args.limit),
        "gettingCooked": getting_cooked(pitchers, args.limit),
        "taleOfTheTapeRecap": tale_recap(args.tale_dir, args.recap_days, report_date),
    }

    write_json(args.output, report)
    markdown_path = write_markdown_report(args.report_dir, report_date, report)
    print(f"Wrote Scouting Report JSON: {args.output}")
    print(f"Wrote markdown draft: {markdown_path}")
    print(
        "Power Gap sort comparison: "
        f"xHR Diff vs Power Gap Score overlap {power_gap_sort_comparison['overlap']}/{args.limit}. "
        f"{power_gap_sort_comparison['recommendation']}"
    )
    if power_gap_sort_comparison["changedPlayers"]:
        print("Power Gap Score would add: " + ", ".join(power_gap_sort_comparison["changedPlayers"]))


if __name__ == "__main__":
    main()
