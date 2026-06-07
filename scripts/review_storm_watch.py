#!/usr/bin/env python3
"""Generate a consolidated internal Storm Watch review artifact.

This is internal review plumbing only. It does not change production formulas,
public data, frontend output, leaderboards, or Storm Watch scoring.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STORM_DIR = Path("data/shadow/storm_watch")
DEFAULT_PROSPECT_DIR = Path("data/shadow/prospects")
DEFAULT_OUTPUT_DIR = Path("/tmp")
DEFAULT_NOTES_PATH = Path("public/docs/storm-watch-notes.md")
STORM_TMP_DIRS = (
    Path("/tmp/storm_watch_review_snapshot"),
    Path("/tmp/storm_watch_milb_snapshot"),
    Path("/tmp/storm_watch_adp_snapshot"),
    Path("/tmp/storm_watch_milb_base_snapshot"),
)

REVIEW_FIELDS = [
    "player",
    "playerId",
    "team",
    "age",
    "PA",
    "BBE",
    "HR",
    "previousSeasonPa",
    "priorStatus",
    "bucketLabel",
    "bucketConfidence",
    "b6Air",
    "stormFuelA2",
    "xhrPerBbe",
    "stabilizedXhrPerBbe",
    "thunderRate",
    "stabilizedThunderRate",
    "airEv90",
    "barrelPerPa",
    "thunderPerPa",
    "contact%",
    "whiff%",
    "zoneContact%",
    "chase%",
    "K%",
    "BB%",
    "durabilityTag",
    "contactRiskTag",
    "powerAccessTag",
    "powerAccessNote",
    "fantasyAdp",
    "fantasyAdpBucket",
    "fantasyAwarenessScore",
    "adpJoinStatus",
    "adpSourceDate",
    "milbDataStatus",
    "milbHighestLevel",
    "milbUpperMinorsPA",
    "milbUpperMinorsHR",
    "milbUpperMinorsHRPerPA",
    "milbUpperMinorsSLG",
    "milbUpperMinorsOPS",
    "milbPowerSupportScore",
    "milbPowerCategory",
    "milbNote",
    "prospectStormSupport",
    "prospectCategory",
    "pipelineRank",
    "pipelineAge",
    "pipelineLevel",
    "pipelinePA",
    "pipelineHR",
    "pipelineHRRate",
    "pipelineSLG",
    "pipelineOPS",
    "prospectSourceDate",
    "prospectJoinStatus",
    "mlbProductionObviousness",
    "consensusCategory",
    "stormWatchRead",
    "reviewNote",
]

STORM_REQUIRED_FIELDS = [
    "player",
    "playerId",
    "team",
    "age",
    "PA",
    "BBE",
    "HR",
    "previousSeasonPa",
    "priorStatus",
    "bucketLabel",
    "bucketConfidence",
    "b6Air",
    "stormFuelA2",
    "xhrPerBbe",
    "stabilizedXhrPerBbe",
    "thunderRate",
    "stabilizedThunderRate",
    "airEv90",
    "barrelPerPa",
    "thunderPerPa",
    "contact%",
    "whiff%",
    "zoneContact%",
    "chase%",
    "K%",
    "BB%",
    "durabilityTag",
    "contactRiskTag",
    "fantasyAdp",
    "fantasyAdpBucket",
    "fantasyAwarenessScore",
    "adpJoinStatus",
    "adpSourceDate",
    "milbDataStatus",
    "milbHighestLevel",
    "milbPowerSupportScore",
    "milbPowerCategory",
    "mlbProductionObviousness",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an internal Storm Watch review artifact.")
    parser.add_argument("--storm-snapshot", type=Path, help="Storm Watch shadow snapshot JSON.")
    parser.add_argument("--prospect-snapshot", type=Path, help="Prospect Storm Board snapshot JSON.")
    parser.add_argument("--date", help="Review date YYYY-MM-DD. Also prefers same-date snapshots when present.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for review CSV/JSON.")
    parser.add_argument("--limit", type=int, default=10, help="Number of rows printed for each review group.")
    parser.add_argument("--notes-path", type=Path, default=DEFAULT_NOTES_PATH, help="Internal notes file to audit.")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def review_date(override: str | None) -> str:
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
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def quantile(values: list[float], pct: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * pct
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    return clean[lower] * (upper - position) + clean[upper] * (position - lower)


def round_or_none(value: Any, digits: int = 1) -> float | None:
    parsed = maybe_number(value)
    return None if parsed is None else round(parsed, digits)


def snapshot_candidates(pattern: str, exact_path: Path | None, date_value: str | None, search_dirs: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    if exact_path:
        candidates.append(exact_path)
        return candidates
    if date_value:
        for directory in search_dirs:
            candidates.append(directory / pattern.format(date=date_value))
    for directory in search_dirs:
        candidates.extend(sorted(directory.glob(pattern.format(date="*")), reverse=True))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def resolve_snapshot(pattern: str, exact_path: Path | None, date_value: str | None, search_dirs: list[Path], label: str) -> Path:
    for candidate in snapshot_candidates(pattern, exact_path, date_value, search_dirs):
        if candidate.exists():
            return candidate
    searched = ", ".join(str(path) for path in search_dirs)
    raise FileNotFoundError(f"No {label} snapshot found for date={date_value or 'latest'} in {searched}")


def players_from_snapshot(payload: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("players"), list):
        return payload["players"]
    raise ValueError(f"{label} snapshot does not contain a players list")


def threshold_context(storm_rows: list[dict[str, Any]]) -> dict[str, float | None]:
    contacts = [value for row in storm_rows if (value := maybe_number(row.get("contactPct"))) is not None]
    whiffs = [value for row in storm_rows if (value := maybe_number(row.get("whiffPct"))) is not None]
    b6_values = [value for row in storm_rows if (value := maybe_number(row.get("b6Air"))) is not None]
    return {
        "contactMedian": quantile(contacts, 0.50),
        "contactTop20Cutoff": quantile(contacts, 0.80),
        "contactBottom30Cutoff": quantile(contacts, 0.30),
        "whiffMedian": quantile(whiffs, 0.50),
        "whiffTop20Cutoff": quantile(whiffs, 0.80),
        "whiffBottom20Cutoff": quantile(whiffs, 0.20),
        "b6Top20Cutoff": quantile(b6_values, 0.80),
        "b6HighCutoff": 110.0,
    }


def is_high_adp(bucket: Any, adp: Any) -> bool:
    bucket_text = str(bucket or "").lower()
    adp_value = maybe_number(adp)
    return bucket_text in {"top 100", "101-200"} or (adp_value is not None and adp_value <= 200)


def is_low_adp(bucket: Any, adp: Any) -> bool:
    bucket_text = str(bucket or "").lower()
    adp_value = maybe_number(adp)
    if bucket_text in {"300+", "undrafted / missing", "undrafted/missing", "missing", "ambiguous"}:
        return True
    if adp_value is None:
        return True
    return adp_value > 200


def is_mlb_obvious(row: dict[str, Any]) -> bool:
    obviousness = maybe_number(row.get("mlbProductionObviousness")) or 0.0
    hr = maybe_number(row.get("hr")) or 0.0
    hr_per_pa = maybe_number(row.get("currentHrPerPa")) or 0.0
    return obviousness >= 70 or hr >= 10 or hr_per_pa >= 0.045


def power_access(row: dict[str, Any], thresholds: dict[str, float | None]) -> tuple[str, str]:
    if row.get("powerAccessTag"):
        return str(row.get("powerAccessTag")), str(row.get("powerAccessNote") or "")

    b6_air = maybe_number(row.get("b6Air")) or 0.0
    contact = maybe_number(row.get("contactPct"))
    whiff = maybe_number(row.get("whiffPct"))
    risk = str(row.get("contactRiskTag") or "").lower()
    b6_top = thresholds.get("b6Top20Cutoff") or 130.0
    contact_median = thresholds.get("contactMedian") or 0.0
    contact_top = thresholds.get("contactTop20Cutoff") or 1.0
    contact_bottom = thresholds.get("contactBottom30Cutoff") or 0.0
    whiff_median = thresholds.get("whiffMedian") or 1.0
    whiff_top = thresholds.get("whiffTop20Cutoff") or 1.0
    whiff_bottom = thresholds.get("whiffBottom20Cutoff") or 0.0

    high_power = b6_air >= 110.0
    elite_power = b6_air >= max(130.0, b6_top)
    weak_contact = contact is not None and contact <= contact_bottom
    high_whiff = whiff is not None and whiff >= whiff_top
    playable_contact = contact is not None and contact >= contact_median
    playable_whiff = whiff is not None and whiff <= whiff_median
    contact_foundation = contact is not None and whiff is not None and contact >= contact_top and whiff <= whiff_bottom

    if elite_power and ("contact-whiff-risk" in risk or weak_contact or high_whiff):
        return "Boom-or-Bust", "Elite power with extreme contact/whiff risk."
    if high_power and ("contact-whiff-risk" in risk or "mild-contact-risk" in risk or weak_contact or high_whiff):
        return "Volatile Access", "Loud power, but contact/whiff risk keeps access volatile."
    if high_power and playable_contact and playable_whiff:
        return "Power Trust", "Loud power with playable contact support."
    if contact_foundation and b6_air < 110.0:
        return "Contact Foundation", "Excellent contact foundation; power read is modest or forming."
    return "Neutral Context", "No strong power-access archetype flag."


def consensus_category(row: dict[str, Any], prospect_only: bool = False) -> str:
    if prospect_only:
        return "Prospect Watch"

    b6_air = maybe_number(row.get("b6Air")) or 0.0
    high_storm = b6_air >= 110.0
    weaker_storm = b6_air < 100.0
    adp_bucket = row.get("fantasyAdpBucket")
    adp = row.get("fantasyAdp")
    milb_category = str(row.get("milbPowerCategory") or "")
    high_adp = is_high_adp(adp_bucket, adp)
    low_adp = is_low_adp(adp_bucket, adp)
    obvious = is_mlb_obvious(row)
    strong_milb = milb_category in {"Strong MiLB power support", "Solid MiLB power support"}
    weak_milb = milb_category in {"Weak MiLB power support", "Not enough MiLB data", "Source mismatch / manual review"}
    foreign = milb_category == "Foreign/pro context missing"

    if foreign and (high_storm or row.get("player") in {"Munetaka Murakami", "Kazuma Okamoto", "Shohei Ohtani", "Jung Hoo Lee"}):
        return "Foreign/Pro Context Needed"
    if high_adp and weaker_storm:
        return "Market Ahead Of Signal"
    if high_storm and (high_adp or obvious):
        return "Storm Confirms"
    if high_storm and low_adp and weak_milb and not obvious:
        return "Statcast Flash"
    if high_storm and low_adp and not obvious:
        return "Consensus Gap"
    if high_storm and strong_milb:
        return "Track Record Supports"
    return "Neutral Context"


def storm_watch_read(row: dict[str, Any], category: str, power_access_tag: str) -> str:
    if category == "Prospect Watch":
        return "Pre-MLB Prospect Storm Board row; monitor for MLB Storm Watch entry."
    if category == "Consensus Gap":
        return "High Storm signal with low/missing ADP and not MLB-obvious."
    if category == "Track Record Supports":
        return "High Storm signal has MiLB track-record support."
    if category == "Statcast Flash":
        return "High Storm signal with low market awareness but weak/missing MiLB support; treat as caution."
    if category == "Storm Confirms":
        return "Storm signal confirms an already visible market or MLB power read."
    if category == "Market Ahead Of Signal":
        return "Fantasy market/prospect attention is ahead of the current Storm power signal."
    if category == "Foreign/Pro Context Needed":
        return "MiLB source does not cover the relevant pre-MLB record; needs foreign/pro context."
    bucket = row.get("bucketLabel") or "Unbucketed"
    confidence = row.get("bucketConfidence") or "context"
    return f"{bucket} ({confidence}); {power_access_tag}."


def build_prospect_index(prospect_rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in prospect_rows:
        grouped.setdefault(normalize_name(row.get("player")), []).append(row)
    unique = {name: rows[0] for name, rows in grouped.items() if len(rows) == 1}
    return unique, grouped


def review_note(row: dict[str, Any]) -> str:
    pieces: list[str] = []
    tags = row.get("consensusContextTags")
    if isinstance(tags, list) and tags:
        pieces.append(", ".join(str(tag) for tag in tags))
    for key in ("milbSampleCaution", "bbeConfidenceNote"):
        if row.get(key):
            pieces.append(str(row[key]))
    return " | ".join(pieces)


def map_storm_row(row: dict[str, Any], prospect: dict[str, Any] | None, prospect_status: str, thresholds: dict[str, float | None]) -> dict[str, Any]:
    power_tag, power_note = power_access(row, thresholds)
    category = consensus_category(row)
    return {
        "player": row.get("player"),
        "playerId": row.get("playerId"),
        "team": row.get("team"),
        "age": row.get("age"),
        "PA": row.get("pa"),
        "BBE": row.get("bbe"),
        "HR": row.get("hr"),
        "previousSeasonPa": row.get("previousSeasonPa"),
        "priorStatus": row.get("priorStatus"),
        "bucketLabel": row.get("bucketLabel"),
        "bucketConfidence": row.get("bucketConfidence"),
        "b6Air": row.get("b6Air"),
        "stormFuelA2": row.get("stormFuelA2"),
        "xhrPerBbe": row.get("xhrPerBbe"),
        "stabilizedXhrPerBbe": row.get("stabilizedXhrPerBbe"),
        "thunderRate": row.get("thunderRate"),
        "stabilizedThunderRate": row.get("stabilizedThunderRate"),
        "airEv90": row.get("airEv90"),
        "barrelPerPa": row.get("barrelPerPa"),
        "thunderPerPa": row.get("thunderPerPa"),
        "contact%": row.get("contactPct"),
        "whiff%": row.get("whiffPct"),
        "zoneContact%": row.get("zoneContactPct"),
        "chase%": row.get("chasePct"),
        "K%": row.get("kPct"),
        "BB%": row.get("bbPct"),
        "durabilityTag": row.get("durabilityTag"),
        "contactRiskTag": row.get("contactRiskTag"),
        "powerAccessTag": power_tag,
        "powerAccessNote": power_note,
        "fantasyAdp": row.get("fantasyAdp"),
        "fantasyAdpBucket": row.get("fantasyAdpBucket"),
        "fantasyAwarenessScore": row.get("fantasyAwarenessScore"),
        "adpJoinStatus": row.get("adpJoinStatus"),
        "adpSourceDate": row.get("adpSourceDate"),
        "milbDataStatus": row.get("milbDataStatus"),
        "milbHighestLevel": row.get("milbHighestLevel"),
        "milbUpperMinorsPA": row.get("milbUpperMinorsPA"),
        "milbUpperMinorsHR": row.get("milbUpperMinorsHR"),
        "milbUpperMinorsHRPerPA": row.get("milbUpperMinorsHRPerPA"),
        "milbUpperMinorsSLG": row.get("milbUpperMinorsSLG"),
        "milbUpperMinorsOPS": row.get("milbUpperMinorsOPS"),
        "milbPowerSupportScore": row.get("milbPowerSupportScore"),
        "milbPowerCategory": row.get("milbPowerCategory"),
        "milbNote": row.get("milbNote"),
        "prospectStormSupport": prospect.get("prospectStormSupport") if prospect else None,
        "prospectCategory": prospect.get("prospectCategory") if prospect else None,
        "pipelineRank": prospect.get("rank") if prospect else None,
        "pipelineAge": prospect.get("age") if prospect else None,
        "pipelineLevel": prospect.get("level") if prospect else None,
        "pipelinePA": prospect.get("PA") if prospect else None,
        "pipelineHR": prospect.get("HR") if prospect else None,
        "pipelineHRRate": prospect.get("HRRate") if prospect else None,
        "pipelineSLG": prospect.get("SLG") if prospect else None,
        "pipelineOPS": prospect.get("OPS") if prospect else None,
        "prospectSourceDate": prospect.get("sourceDate") if prospect else None,
        "prospectJoinStatus": prospect_status,
        "mlbProductionObviousness": row.get("mlbProductionObviousness"),
        "consensusCategory": category,
        "stormWatchRead": storm_watch_read(row, category, power_tag),
        "reviewNote": review_note(row),
    }


def map_prospect_only(row: dict[str, Any]) -> dict[str, Any]:
    output = {field: None for field in REVIEW_FIELDS}
    output.update(
        {
            "player": row.get("player"),
            "age": row.get("age"),
            "prospectStormSupport": row.get("prospectStormSupport"),
            "prospectCategory": row.get("prospectCategory"),
            "pipelineRank": row.get("rank"),
            "pipelineAge": row.get("age"),
            "pipelineLevel": row.get("level"),
            "pipelinePA": row.get("PA"),
            "pipelineHR": row.get("HR"),
            "pipelineHRRate": row.get("HRRate"),
            "pipelineSLG": row.get("SLG"),
            "pipelineOPS": row.get("OPS"),
            "prospectSourceDate": row.get("sourceDate"),
            "prospectJoinStatus": "prospect-only",
            "consensusCategory": "Prospect Watch",
            "stormWatchRead": "Pre-MLB Prospect Storm Board row; monitor for MLB Storm Watch entry.",
            "reviewNote": row.get("sampleNote") or row.get("joinLimitations"),
        }
    )
    return output


def build_review(storm_rows: list[dict[str, Any]], prospect_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float | None]]:
    thresholds = threshold_context(storm_rows)
    prospect_unique, prospect_grouped = build_prospect_index(prospect_rows)
    storm_names = {normalize_name(row.get("player")) for row in storm_rows}
    review_rows: list[dict[str, Any]] = []

    for row in storm_rows:
        normalized = normalize_name(row.get("player"))
        prospect = prospect_unique.get(normalized)
        if prospect:
            status = "name-match"
        elif normalized in prospect_grouped:
            status = "ambiguous-name"
        else:
            status = "not-found"
        review_rows.append(map_storm_row(row, prospect, status, thresholds))

    for row in prospect_rows:
        if normalize_name(row.get("player")) in storm_names:
            continue
        review_rows.append(map_prospect_only(row))

    return review_rows, thresholds


def missing_counts(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, int]:
    return {
        field: sum(1 for row in rows if row.get(field) in (None, ""))
        for field in fields
    }


def write_outputs(review_rows: list[dict[str, Any]], metadata: dict[str, Any], output_dir: Path, date_value: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"storm_watch_review_{date_value}.csv"
    json_path = output_dir / f"storm_watch_review_{date_value}.json"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in review_rows:
            writer.writerow({field: row.get(field) for field in REVIEW_FIELDS})
    payload = {
        **metadata,
        "players": review_rows,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return csv_path, json_path


def sort_by_b6(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: maybe_number(row.get("b6Air")) or -999.0, reverse=True)


def sort_by_prospect_support(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: maybe_number(row.get("prospectStormSupport")) or -999.0, reverse=True)


def format_number(value: Any, digits: int = 1) -> str:
    parsed = maybe_number(value)
    return "" if parsed is None else f"{parsed:.{digits}f}"


def review_line(row: dict[str, Any]) -> str:
    return (
        f"{str(row.get('player') or ''):<24} "
        f"{str(row.get('team') or ''):<3} "
        f"age {format_number(row.get('age'), 2):>5} "
        f"B6 {format_number(row.get('b6Air')):>5} "
        f"ADP {str(row.get('fantasyAdpBucket') or ''):<18} "
        f"MiLB {str(row.get('milbPowerCategory') or ''):<36} "
        f"{row.get('consensusCategory') or ''}"
    )


def prospect_line(row: dict[str, Any]) -> str:
    return (
        f"{str(row.get('player') or ''):<24} "
        f"rank {str(row.get('pipelineRank') or ''):>3} "
        f"lvl {str(row.get('pipelineLevel') or ''):<7} "
        f"PSS {format_number(row.get('prospectStormSupport')):>5} "
        f"HR% {format_number(row.get('pipelineHRRate'), 3):>6} "
        f"{row.get('prospectCategory') or ''}"
    )


def print_group(title: str, rows: list[dict[str, Any]], limit: int, prospect: bool = False) -> None:
    print(f"\n{title}")
    if not rows:
        print("- none")
        return
    for row in rows[:limit]:
        print("- " + (prospect_line(row) if prospect else review_line(row)))


def print_review_groups(rows: list[dict[str, Any]], limit: int) -> None:
    low_history_age_le25 = [
        row
        for row in rows
        if (maybe_number(row.get("age")) is not None and maybe_number(row.get("age")) <= 25)
        and row.get("priorStatus") in {"no-prior", "low-history"}
    ]
    high_storm_low_adp_strong_milb = [
        row
        for row in rows
        if (maybe_number(row.get("b6Air")) or 0.0) >= 110
        and is_low_adp(row.get("fantasyAdpBucket"), row.get("fantasyAdp"))
        and row.get("milbPowerCategory") in {"Strong MiLB power support", "Solid MiLB power support"}
    ]
    high_storm_weak_milb = [
        row
        for row in rows
        if (maybe_number(row.get("b6Air")) or 0.0) >= 110
        and row.get("milbPowerCategory") in {"Weak MiLB power support", "Not enough MiLB data", "Foreign/pro context missing", "Source mismatch / manual review"}
    ]
    groups = [
        ("Top Prime Emergence", sort_by_b6([row for row in rows if row.get("bucketLabel") == "Prime Emergence"]), False),
        ("Top Early Emergence", sort_by_b6([row for row in rows if row.get("bucketLabel") == "Early Emergence"]), False),
        ("Top all low-history <=25", sort_by_b6(low_history_age_le25), False),
        ("Top Late-Arrival Reference", sort_by_b6([row for row in rows if row.get("bucketLabel") == "Late-Arrival Reference"]), False),
        ("High Storm + low ADP + strong MiLB support", sort_by_b6(high_storm_low_adp_strong_milb), False),
        ("High Storm + weak/no MiLB support", sort_by_b6(high_storm_weak_milb), False),
        ("Market ahead of signal", sorted([row for row in rows if row.get("consensusCategory") == "Market Ahead Of Signal"], key=lambda row: maybe_number(row.get("fantasyAdp")) or 9999), False),
        ("Prospect Storm Board top power names", sort_by_prospect_support([row for row in rows if row.get("prospectStormSupport") is not None]), True),
        ("Foreign/pro context-needed names", sort_by_b6([row for row in rows if row.get("consensusCategory") == "Foreign/Pro Context Needed"]), False),
    ]
    for title, group_rows, is_prospect in groups:
        print_group(title, group_rows, limit, prospect=is_prospect)


def audit_notes(notes_path: Path) -> list[str]:
    if not notes_path.exists():
        return [f"notes file missing: {notes_path}"]
    issues: list[str] = []
    lines = notes_path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        lowered = line.lower()
        context = " ".join(lines[max(0, line_number - 2) : min(len(lines), line_number + 1)]).lower()
        is_guardrail = (
            "do not" in context
            or "not " in context
            or "context only" in context
            or "never part" in context
            or "clear no" in context
        )
        if re.search(r"(15[-–]45|15 to 45).{0,80}hr[- ]window|hr[- ]window.{0,80}(15[-–]45|15 to 45)", lowered) and not is_guardrail:
            issues.append(f"{line_number}: possible Air EV90/HR-window conflict: {line.strip()}")
        if re.search(r"21[-–]22", lowered) and re.search(r"validated|high trust|high-confidence|high confidence", lowered) and not is_guardrail:
            issues.append(f"{line_number}: possible literal 21-22 overclaim: {line.strip()}")
        if re.search(r"adp|milb|fv|fangraphs", lowered) and re.search(r"part of b6|part of storm fuel|score input", lowered) and not is_guardrail:
            issues.append(f"{line_number}: possible context-layer scoring conflict: {line.strip()}")
        if "damage access" in lowered and "public" in lowered and not is_guardrail:
            issues.append(f"{line_number}: possible Damage Access public conflict: {line.strip()}")
    return issues


def main() -> None:
    args = parse_args()
    date_value = review_date(args.date)
    storm_path = resolve_snapshot(
        "snapshot_{date}.json",
        args.storm_snapshot,
        args.date,
        [DEFAULT_STORM_DIR, *STORM_TMP_DIRS],
        "Storm Watch",
    )
    prospect_path = resolve_snapshot(
        "prospect_storm_board_{date}.json",
        args.prospect_snapshot,
        args.date,
        [DEFAULT_PROSPECT_DIR, DEFAULT_OUTPUT_DIR],
        "Prospect Storm Board",
    )

    storm_payload = load_json(storm_path)
    prospect_payload = load_json(prospect_path)
    storm_rows = players_from_snapshot(storm_payload, "Storm Watch")
    prospect_rows = players_from_snapshot(prospect_payload, "Prospect Storm Board")
    review_rows, thresholds = build_review(storm_rows, prospect_rows)

    storm_review_rows = [row for row in review_rows if row.get("prospectJoinStatus") != "prospect-only"]
    metadata = {
        "reviewDate": date_value,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "internal-review",
        "generatedFrom": {
            "stormWatchSnapshot": str(storm_path),
            "prospectStormBoard": str(prospect_path),
        },
        "rowCounts": {
            "total": len(review_rows),
            "stormWatchRows": len(storm_rows),
            "prospectOnlyRows": len(review_rows) - len(storm_rows),
        },
        "bucketCounts": dict(Counter(row.get("bucketLabel") or "Prospect Watch" for row in review_rows)),
        "consensusCategoryCounts": dict(Counter(row.get("consensusCategory") or "Neutral Context" for row in review_rows)),
        "powerAccessTagCounts": dict(Counter(row.get("powerAccessTag") or "Prospect-only" for row in review_rows)),
        "thresholds": {key: round_or_none(value, 3) for key, value in thresholds.items()},
        "missingKeyFieldCounts": {
            "stormWatchRows": missing_counts(storm_review_rows, STORM_REQUIRED_FIELDS),
            "allRows": missing_counts(review_rows, REVIEW_FIELDS),
        },
    }
    csv_path, json_path = write_outputs(review_rows, metadata, args.output_dir, date_value)

    print(f"Storm Watch review date: {date_value}")
    print(f"Storm snapshot: {storm_path}")
    print(f"Prospect snapshot: {prospect_path}")
    print(f"Review CSV: {csv_path}")
    print(f"Review JSON: {json_path}")
    print(f"Rows: {metadata['rowCounts']}")
    print(f"Bucket counts: {metadata['bucketCounts']}")
    print(f"Consensus category counts: {metadata['consensusCategoryCounts']}")
    print(f"Power Access tag counts: {metadata['powerAccessTagCounts']}")

    key_missing = {
        key: value
        for key, value in metadata["missingKeyFieldCounts"]["stormWatchRows"].items()
        if value
    }
    print("\nMissing key fields among Storm Watch rows:")
    if key_missing:
        for key, value in key_missing.items():
            print(f"- {key}: {value}")
    else:
        print("- none")

    print_review_groups(review_rows, args.limit)

    print("\nNotes guardrail audit:")
    issues = audit_notes(args.notes_path)
    if issues:
        for issue in issues:
            print(f"- {issue}")
    else:
        print("- no stale Storm Watch guardrail conflicts found")


if __name__ == "__main__":
    main()
