#!/usr/bin/env python3
"""Write an internal Prospect Storm Board snapshot from MLB Pipeline stats.

This is shadow/research plumbing only. It does not change public data,
front-end output, production formulas, or Storm Watch scoring.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pybaseball import top_prospects


DEFAULT_OUTPUT_DIR = Path("data/shadow/prospects")
DEFAULT_REVIEW_DIR = Path("/tmp")
SOURCE_URL = "https://www.mlb.com/prospects/stats/top-prospects"
SOURCE_NAME = "MLB Pipeline prospect stats via pybaseball.top_prospects(playerType='batters')"
NORMAL_LEVEL_SCORES = {
    "ROK": 10,
    "A": 25,
    "A+": 40,
    "AA": 65,
    "AAA": 85,
    "MLB": 100,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an internal Prospect Storm Board snapshot.")
    parser.add_argument("--date", help="Snapshot date YYYY-MM-DD. Defaults to current UTC date.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--replace-existing", action="store_true", help="Replace an existing same-date snapshot.")
    return parser.parse_args()


def snapshot_date(override: str | None) -> str:
    if override:
        datetime.fromisoformat(override)
        return override
    return datetime.now(timezone.utc).date().isoformat()


def normalize_name(value: Any) -> str:
    text = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKD", text.replace("’", "'"))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = re.sub(r"\b(Jr|Sr|II|III|IV)\.?\b", "", ascii_text, flags=re.IGNORECASE)
    ascii_text = re.sub(r"[^A-Za-z0-9 ]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def maybe_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def percentile(values: pd.Series, ascending: bool = True) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.rank(method="average", pct=True, ascending=ascending) * 100


def level_score(level: Any) -> float | None:
    if level is None or pd.isna(level):
        return None
    text = str(level).strip().upper()
    if text.startswith("ALL"):
        return 62.5
    return NORMAL_LEVEL_SCORES.get(text)


def age_level_context(age: Any, level: Any) -> float | None:
    age_value = maybe_number(age)
    level_value = level_score(level)
    if age_value is None or level_value is None:
        return None
    # Younger at a higher level should be rewarded; older/lower-level production
    # should get less support. Keep this coarse because Pipeline's level field can
    # be an aggregate like ALL (2).
    age_score = max(0.0, min(100.0, (24.5 - age_value) / 6.5 * 100))
    return 0.60 * level_value + 0.40 * age_score


def category(row: pd.Series) -> str:
    pa = maybe_number(row.get("PA")) or 0.0
    power = maybe_number(row.get("powerSupport")) or 0.0
    approach = maybe_number(row.get("approachSupport")) or 0.0
    consensus = maybe_number(row.get("consensusSupport")) or 0.0
    k_rate = maybe_number(row.get("KRate")) or 0.0
    if pa < 50:
        return "Not Enough Data"
    if consensus >= 75 and power >= 70:
        return "Top Prospect Power"
    if consensus < 55 and power >= 72:
        return "Under-the-Radar Power"
    if power >= 68 and k_rate >= 0.28:
        return "Power Risk"
    if approach >= 75 and power < 62:
        return "Contact Foundation"
    return "Balanced / Follow"


def sample_note(row: pd.Series) -> str:
    pa = maybe_number(row.get("PA")) or 0.0
    level = str(row.get("level") or "")
    if pa < 50:
        return "not enough PA to judge"
    if level.upper().startswith("ALL"):
        return "level is a multi-level aggregate; age/level context is coarse"
    if maybe_number(row.get("ageLevelContext")) is None:
        return "missing age or level context"
    return "enough current prospect-stat sample"


def fetch_pipeline_batters() -> pd.DataFrame:
    rows = top_prospects(playerType="batters")
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("pybaseball.top_prospects did not return a DataFrame")
    return rows.copy()


def build_rows(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rename = {
        "Rk": "rank",
        "Player": "player",
        "Age": "age",
        "L": "level",
        "HR%": "HRPct",
        "BB%": "BBPct",
        "K%": "KPct",
    }
    frame = frame.rename(columns=rename).copy()
    for column in ["rank", "age", "PA", "HR", "HRPct", "BBPct", "KPct", "SLG", "OPS", "BB", "SO"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["normalizedName"] = frame["player"].map(normalize_name)
    frame["HRRate"] = frame.apply(lambda row: safe_divide(float(row.get("HR") or 0), float(row.get("PA") or 0)), axis=1)
    frame["BBRate"] = frame["BBPct"] / 100
    frame["KRate"] = frame["KPct"] / 100
    frame["BBK"] = frame.apply(lambda row: safe_divide(float(row.get("BB") or 0), float(row.get("SO") or 0)), axis=1)
    frame["scoreHRRate"] = percentile(frame["HRRate"])
    frame["scoreSLG"] = percentile(frame["SLG"])
    frame["scoreOPS"] = percentile(frame["OPS"])
    frame["powerSupport"] = 0.50 * frame["scoreHRRate"] + 0.25 * frame["scoreSLG"] + 0.25 * frame["scoreOPS"]
    frame["consensusSupport"] = percentile(frame["rank"], ascending=False)
    frame["scoreBBRate"] = percentile(frame["BBRate"])
    frame["scoreInverseKRate"] = percentile(-frame["KRate"])
    frame["scoreBBK"] = percentile(frame["BBK"])
    frame["approachSupport"] = 0.45 * frame["scoreBBRate"] + 0.45 * frame["scoreInverseKRate"] + 0.10 * frame["scoreBBK"]
    frame["ageLevelContext"] = frame.apply(lambda row: age_level_context(row.get("age"), row.get("level")), axis=1)
    if frame["ageLevelContext"].isna().all():
        frame["prospectStormSupport"] = (
            0.47 * frame["powerSupport"]
            + 0.29 * frame["consensusSupport"]
            + 0.24 * frame["approachSupport"]
        )
        level_note = "age/level context unavailable; weights reallocated across power, rank, and approach"
    else:
        frame["prospectStormSupport"] = (
            0.40 * frame["powerSupport"]
            + 0.25 * frame["consensusSupport"]
            + 0.20 * frame["approachSupport"]
            + 0.15 * frame["ageLevelContext"].fillna(frame["ageLevelContext"].median())
        )
        level_note = "age/level context included at 15%; ALL-level rows use a coarse neutral level score"
    frame["prospectCategory"] = frame.apply(category, axis=1)
    frame["sampleNote"] = frame.apply(sample_note, axis=1)

    output_fields = [
        "player",
        "normalizedName",
        "rank",
        "age",
        "level",
        "PA",
        "HR",
        "HRRate",
        "BBRate",
        "KRate",
        "SLG",
        "OPS",
        "powerSupport",
        "consensusSupport",
        "approachSupport",
        "ageLevelContext",
        "prospectStormSupport",
        "prospectCategory",
        "sampleNote",
    ]
    rows: list[dict[str, Any]] = []
    for record in frame.sort_values(["prospectStormSupport", "rank"], ascending=[False, True]).to_dict(orient="records"):
        row = {field: record.get(field) for field in output_fields}
        for key, value in list(row.items()):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                row[key] = None
        for key in ["HRRate", "BBRate", "KRate", "SLG", "OPS"]:
            if row.get(key) is not None:
                row[key] = round(float(row[key]), 5)
        for key in ["powerSupport", "consensusSupport", "approachSupport", "ageLevelContext", "prospectStormSupport"]:
            if row.get(key) is not None:
                row[key] = round(float(row[key]), 1)
        for key in ["rank", "age", "PA", "HR"]:
            if row.get(key) is not None:
                row[key] = int(row[key]) if key in {"rank", "PA", "HR"} else round(float(row[key]), 1)
        row["source"] = SOURCE_NAME
        row["sourceDate"] = None
        row["joinLimitations"] = "No MLBAM id, org/team, or position in pybaseball.top_prospects batting output; future bridge needs MLBAM/player id or strict name+age/org matching."
        rows.append(row)

    coverage = {}
    for field in ["rank", "age", "level", "PA", "HR", "HRRate", "BBRate", "KRate", "SLG", "OPS"]:
        coverage[field] = int(frame[field].notna().sum()) if field in frame.columns else 0

    metadata = {
        "rowCount": len(rows),
        "fieldsReturned": list(frame.columns),
        "coverage": coverage,
        "levelContextNote": level_note,
        "missingIdTeamPositionLimitations": "pybaseball output has no MLBAM id, team/org, or position fields.",
        "weights": {
            "prospectStormSupport": {
                "minorLeaguePowerSupport": 0.40,
                "prospectRankConsensus": 0.25,
                "approachSupport": 0.20,
                "ageLevelContext": 0.15,
            },
            "minorLeaguePowerSupport": {
                "HRRate": 0.50,
                "SLG": 0.25,
                "OPS": 0.25,
            },
            "approachSupport": {
                "BBRate": 0.45,
                "inverseKRate": 0.45,
                "BBK": 0.10,
            },
        },
    }
    return rows, metadata


def write_snapshot(snapshot: dict[str, Any], output_dir: Path, replace_existing: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"prospect_storm_board_{snapshot['snapshotDate']}.json"
    if path.exists() and not replace_existing:
        raise SystemExit(f"Refusing to overwrite existing snapshot: {path}")
    path.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_review(snapshot: dict[str, Any], review_dir: Path) -> tuple[Path, Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    stem = f"prospect_storm_board_{snapshot['snapshotDate']}"
    json_path = review_dir / f"{stem}.json"
    csv_path = review_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(snapshot["players"]).to_csv(csv_path, index=False)
    return csv_path, json_path


def print_rows(title: str, rows: list[dict[str, Any]], limit: int = 12) -> None:
    print(f"\n{title}")
    if not rows:
        print("- none")
        return
    for index, row in enumerate(rows[:limit], 1):
        print(
            f"{index:2}. {row['player']:<24} rk {row['rank']:<3} age {row['age']:<4} "
            f"{row['level']:<7} PA {row['PA']:<3} HR {row['HR']:<2} "
            f"HR/PA {row['HRRate']:<7} SLG {row['SLG']:<6} OPS {row['OPS']:<6} "
            f"support {row['prospectStormSupport']:<5} | {row['prospectCategory']}"
        )


def print_summary(snapshot: dict[str, Any], paths: tuple[Path, Path, Path]) -> None:
    snapshot_path, csv_path, json_path = paths
    rows = snapshot["players"]
    print(f"Prospect Storm Board snapshot: {snapshot['snapshotDate']}")
    print(f"Source: {snapshot['source']['name']}")
    print(f"Rows: {snapshot['source']['rowCount']}")
    print("Coverage:")
    for field, count in snapshot["source"]["coverage"].items():
        print(f"- {field}: {count}/{snapshot['source']['rowCount']}")
    print("Category counts:")
    for category, count in sorted(snapshot["categoryCounts"].items()):
        print(f"- {category}: {count}")
    print_rows("Top 25 Prospect Storm Support", rows, 25)
    for category in [
        "Top Prospect Power",
        "Under-the-Radar Power",
        "Power Risk",
        "Contact Foundation",
        "Not Enough Data",
    ]:
        category_rows = [row for row in rows if row["prospectCategory"] == category]
        print_rows(f"Top {category}", category_rows, 12)
    print(f"\nSnapshot path: {snapshot_path}")
    print(f"Review CSV: {csv_path}")
    print(f"Review JSON: {json_path}")


def main() -> None:
    args = parse_args()
    date_value = snapshot_date(args.date)
    raw = fetch_pipeline_batters()
    rows, metadata = build_rows(raw)
    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row["prospectCategory"]] = category_counts.get(row["prospectCategory"], 0) + 1
    snapshot = {
        "snapshotDate": date_value,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "internal-shadow",
        "description": "Prospect Storm Board is the pre-MLB support layer for Storm Watch. It is not a public leaderboard and does not change B6-Air.",
        "source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
            "sourceDate": None,
            **metadata,
        },
        "categories": {
            "Top Prospect Power": "Top rank/consensus plus strong current minor-league power support.",
            "Under-the-Radar Power": "Lower rank/consensus within this table plus strong current power support.",
            "Power Risk": "Strong power support with high strikeout risk.",
            "Contact Foundation": "Strong approach/contact support with less power.",
            "Balanced / Follow": "No extreme power/risk/contact read.",
            "Not Enough Data": "Too little PA for a current descriptive read.",
        },
        "categoryCounts": category_counts,
        "bridgePlan": {
            "purpose": "When a prospect graduates into Storm Watch, carry forward current Pipeline rank/stats/support context.",
            "futureFields": [
                "pipelineRank",
                "pipelineAge",
                "pipelineLevel",
                "pipelinePA",
                "pipelineHR",
                "pipelineHRRate",
                "pipelineSLG",
                "pipelineOPS",
                "pipelineBBRate",
                "pipelineKRate",
                "prospectStormSupport",
                "prospectCategory",
                "prospectSourceDate",
            ],
            "joinNeed": "Future bridge needs MLBAM/player ID or strict normalized name + age + org matching. Current Pipeline stats table does not include IDs, org/team, or position.",
        },
        "players": rows,
    }
    snapshot_path = write_snapshot(snapshot, args.output_dir, args.replace_existing)
    csv_path, json_path = write_review(snapshot, args.review_dir)
    print_summary(snapshot, (snapshot_path, csv_path, json_path))


if __name__ == "__main__":
    main()
