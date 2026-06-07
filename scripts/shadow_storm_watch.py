#!/usr/bin/env python3
"""Write retained internal Storm Watch Young Power Radar snapshots.

This is internal shadow workflow plumbing only. It does not change production
formulas, public data, frontend output, or leaderboard behavior.

Storm Watch is the branded feature name. Young Power Radar is the plain-English
descriptor. B6-Air is the frozen score:

- 60% Storm Fuel A2
- 20% Barrel/PA
- 20% HR-Window Thunder/PA

Storm Fuel A2:

- 50% stabilized xHR/BBE
- 25% stabilized HR-Window Thunder Rate
- 25% Air EV90

Durability/contact fields are confidence context only, never score inputs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


DEFAULT_INPUT = Path("public/data/hr-distance-latest.json")
DEFAULT_STATCAST_CACHE = Path("data/raw/statcast-pitches.csv")
DEFAULT_PEOPLE_CACHE = Path("data/cache/longball-threat-backtest/player-people-cache.json")
DEFAULT_OUTPUT_DIR = Path("data/shadow/storm_watch")
DEFAULT_ADP_URL = "https://www.fantasypros.com/mlb/adp/hitters.php"
DEFAULT_MILB_STATS_API = "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
MILB_SPORT_LEVELS = {
    11: "AAA",
    12: "AA",
    13: "High-A",
    14: "Low-A",
}
MILB_LEVEL_RANK = {
    "Low-A": 1,
    "High-A": 2,
    "AA": 3,
    "AAA": 4,
}
FOREIGN_PRO_CONTEXT_NAMES = (
    "Munetaka Murakami",
    "Kazuma Okamoto",
    "Shohei Ohtani",
    "Jung Hoo Lee",
)

POWER_FIELDS = [
    "b6Air",
    "stormFuelA2",
    "airEv90",
    "xhrPerBbe",
    "stabilizedXhrPerBbe",
    "thunderRate",
    "stabilizedThunderRate",
    "barrelPerPa",
    "thunderPerPa",
]
SNAPSHOT_CONTEXT_FIELDS = [
    "emergenceScore",
    "emergenceGap",
    "positiveLag",
    "exposureNovelty",
    "ageRunway",
    "contactPct",
    "whiffPct",
    "zoneContactPct",
    "chasePct",
    "kPct",
    "bbPct",
    "durabilityTag",
    "contactRiskTag",
    "bbeConfidenceNote",
    "fantasyAdp",
    "fantasyAdpBucket",
    "fantasyAwarenessScore",
    "adpSource",
    "adpSourceDate",
    "adpJoinStatus",
    "adpNameMatched",
    "milbDataStatus",
    "milbHighestLevel",
    "milbUpperMinorsPA",
    "milbUpperMinorsHR",
    "milbUpperMinorsHRPerPA",
    "milbUpperMinorsSLG",
    "milbUpperMinorsOPS",
    "milbUpperMinorsBBRate",
    "milbUpperMinorsKRate",
    "milbAllLevelsPA",
    "milbAllLevelsHR",
    "milbAllLevelsHRPerPA",
    "milbAllLevelsSLG",
    "milbAllLevelsOPS",
    "milbAllLevelsBBRate",
    "milbAllLevelsKRate",
    "milbPowerSupportScore",
    "milbApproachSupport",
    "milbPowerCategory",
    "milbSampleCaution",
    "milbSource",
    "milbSourceSeasonRange",
    "milbJoinStatus",
    "milbNote",
    "mlbProductionObviousness",
    "consensusContextCategory",
    "consensusContextTags",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an internal Storm Watch shadow snapshot.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Current production hitter JSON.")
    parser.add_argument("--statcast-cache", type=Path, default=DEFAULT_STATCAST_CACHE, help="Current pitch cache used for Air EV90 and discipline context.")
    parser.add_argument("--people-cache", type=Path, default=DEFAULT_PEOPLE_CACHE, help="Cached MLB people data with birth dates.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Retained shadow snapshot directory.")
    parser.add_argument("--date", help="Snapshot date YYYY-MM-DD. Defaults to input generatedAt date.")
    parser.add_argument("--limit", type=int, default=25, help="Watchlist size to print/store per bucket.")
    parser.add_argument("--replace-existing", action="store_true", help="Replace an existing same-date snapshot.")
    parser.add_argument("--review-dir", type=Path, default=Path("/tmp"), help="Write CSV/JSON review copies here.")
    parser.add_argument("--adp-url", default=DEFAULT_ADP_URL, help="Fantasy ADP table URL. Context only; fetch failures are nonfatal.")
    parser.add_argument("--skip-adp", action="store_true", help="Skip live Fantasy ADP context.")
    parser.add_argument("--milb-api-url", default=DEFAULT_MILB_STATS_API, help="MLB Stats API people/stats endpoint template. Context only; fetch failures are nonfatal.")
    parser.add_argument("--skip-milb", action="store_true", help="Skip live MiLB power-support context.")
    parser.add_argument("--milb-timeout", type=float, default=12.0, help="Per-request timeout for MiLB context fetches.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_snapshot_date(payload: dict[str, Any], override: str | None) -> str:
    if override:
        datetime.fromisoformat(override)
        return override
    generated_at = str(payload.get("generatedAt") or "")
    if generated_at:
        try:
            return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def parse_date(value: str) -> date:
    return datetime.fromisoformat(value[:10]).date()


def birthday_in_year(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        raise


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def maybe_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_name(value: Any) -> str:
    text = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKD", text.replace("’", "'"))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = re.sub(r"\b(Jr|Sr|II|III|IV)\.?\b", "", ascii_text, flags=re.IGNORECASE)
    ascii_text = re.sub(r"[^A-Za-z0-9 ]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def clean_adp_player(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+IL\d+\b", "", text)
    text = re.sub(r"\s+DTD\b", "", text)
    text = re.sub(r"\s+\(Batter\)", "", text)
    if " (" in text:
        text = text.split(" (", 1)[0]
    return text.strip()


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def percentile_scores(values: pd.Series) -> pd.Series:
    ranks = pd.to_numeric(values, errors="coerce").rank(method="average", pct=True)

    def score(percentile: Any) -> float | None:
        if pd.isna(percentile):
            return None
        clipped = min(max(float(percentile), 0.01), 0.99)
        return 100 + NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped)

    return ranks.map(score)


def weighted_score(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    output: list[float] = []
    for index, _ in frame.iterrows():
        weighted = 0.0
        total = 0.0
        for column, weight in weights.items():
            value = frame.at[index, column] if column in frame.columns else None
            if pd.isna(value):
                continue
            weighted += float(value) * weight
            total += weight
        output.append(weighted / total if total else float("nan"))
    return pd.Series(output, index=frame.index, dtype="float64")


def load_public_lbi_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = load_json(path)
    rows = payload.get("players") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def load_people_birth_dates(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    payload = load_json(path)
    lookup: dict[int, str] = {}
    for person in payload.get("people", []):
        player_id = person.get("id")
        birth_date = person.get("birthDate")
        if player_id and birth_date:
            lookup[int(player_id)] = str(birth_date)
    return lookup


def age_at(birth_date: str | None, checkpoint: date) -> float | None:
    if not birth_date:
        return None
    born = parse_date(birth_date)
    years = checkpoint.year - born.year
    birthday = birthday_in_year(checkpoint.year, born.month, born.day)
    if checkpoint < birthday:
        years -= 1
        last_birthday = birthday_in_year(checkpoint.year - 1, born.month, born.day)
    else:
        last_birthday = birthday
    next_birthday = birthday_in_year(last_birthday.year + 1, born.month, born.day)
    return years + (checkpoint - last_birthday).days / max((next_birthday - last_birthday).days, 1)


def prior_context(season: int) -> tuple[dict[int, dict[str, float]], dict[str, float]]:
    output: dict[int, dict[str, float]] = {}
    all_previous_xhr = []
    all_previous_thunder = []
    for offset in [1, 2, 3]:
        rows = load_public_lbi_rows(Path(f"public/data/longball-index-{season - offset}.json"))
        for row in rows:
            batter = row.get("batter") or row.get("playerId")
            if batter is None:
                continue
            batter_id = int(batter)
            pa = number(row.get("pa"))
            if pa <= 0:
                continue
            context = output.setdefault(
                batter_id,
                {
                    "priorSeasonCount": 0,
                    "priorPaTotal": 0.0,
                    "previousSeasonPa": 0.0,
                    "previousXhrPerBbe": float("nan"),
                    "previousThunderRate": float("nan"),
                },
            )
            context["priorSeasonCount"] += 1
            context["priorPaTotal"] += pa
            if offset == 1:
                context["previousSeasonPa"] = pa
                context["previousXhrPerBbe"] = number(row.get("xhrPerBbe"), float("nan"))
                context["previousThunderRate"] = number(row.get("hrWindowThunderRate"), float("nan"))
                if not math.isnan(context["previousXhrPerBbe"]):
                    all_previous_xhr.append(context["previousXhrPerBbe"])
                if not math.isnan(context["previousThunderRate"]):
                    all_previous_thunder.append(context["previousThunderRate"])
    league = {
        "previousXhrPerBbe": statistics.mean(all_previous_xhr) if all_previous_xhr else 0.0,
        "previousThunderRate": statistics.mean(all_previous_thunder) if all_previous_thunder else 0.0,
    }
    return output, league


def pitch_context(statcast_cache: Path) -> dict[int, dict[str, float]]:
    if not statcast_cache.exists():
        return {}
    columns = [
        "batter",
        "game_pk",
        "at_bat_number",
        "events",
        "type",
        "description",
        "zone",
        "launch_speed",
        "launch_angle",
    ]
    pitches = pd.read_csv(statcast_cache, usecols=lambda column: column in columns)
    if pitches.empty or "batter" not in pitches.columns:
        return {}
    for column in ["batter", "game_pk", "at_bat_number", "zone", "launch_speed", "launch_angle"]:
        if column in pitches.columns:
            pitches[column] = pd.to_numeric(pitches[column], errors="coerce")
    pitches = pitches.dropna(subset=["batter"])
    pitches["batter"] = pitches["batter"].astype(int)
    description = pitches.get("description", pd.Series("", index=pitches.index)).fillna("").astype(str)
    events = pitches.get("events", pd.Series("", index=pitches.index)).fillna("").astype(str)
    zone = pitches.get("zone", pd.Series(float("nan"), index=pitches.index))

    swing_descriptions = {
        "swinging_strike",
        "swinging_strike_blocked",
        "foul",
        "foul_tip",
        "foul_bunt",
        "missed_bunt",
        "bunt_foul_tip",
        "hit_into_play",
        "hit_into_play_no_out",
        "hit_into_play_score",
    }
    whiff_descriptions = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}
    contact_descriptions = {
        "foul",
        "foul_tip",
        "foul_bunt",
        "bunt_foul_tip",
        "hit_into_play",
        "hit_into_play_no_out",
        "hit_into_play_score",
    }
    pitches["_swing"] = description.isin(swing_descriptions)
    pitches["_whiff"] = description.isin(whiff_descriptions)
    pitches["_contact"] = description.isin(contact_descriptions)
    pitches["_in_zone"] = zone.between(1, 9, inclusive="both")
    pitches["_out_zone"] = zone.notna() & ~pitches["_in_zone"]

    bbe = pitches.dropna(subset=["launch_speed"])
    all_ev90 = bbe.groupby("batter")["launch_speed"].quantile(0.90) if not bbe.empty else pd.Series(dtype="float64")
    air = bbe[bbe["launch_angle"].between(15, 45, inclusive="both")]
    air_ev90 = air.groupby("batter")["launch_speed"].quantile(0.90) if not air.empty else pd.Series(dtype="float64")
    air_bbe = air.groupby("batter").size() if not air.empty else pd.Series(dtype="float64")

    terminal = pitches[events.ne("")]
    strikeout_events = {"strikeout", "strikeout_double_play"}
    walk_events = {"walk", "intent_walk"}
    if not terminal.empty:
        terminal = terminal.copy()
        terminal["_strikeout_pa"] = terminal["events"].isin(strikeout_events)
        terminal["_walk_pa"] = terminal["events"].isin(walk_events)
        pa_by_batter = terminal.groupby("batter").size()
        k_by_batter = terminal.groupby("batter")["_strikeout_pa"].sum()
        bb_by_batter = terminal.groupby("batter")["_walk_pa"].sum()
    else:
        pa_by_batter = pd.Series(dtype="float64")
        k_by_batter = pd.Series(dtype="float64")
        bb_by_batter = pd.Series(dtype="float64")

    grouped = pitches.groupby("batter").agg(
        pitches=("batter", "size"),
        swings=("_swing", "sum"),
        whiffs=("_whiff", "sum"),
        contacts=("_contact", "sum"),
        zone_pitches=("_in_zone", "sum"),
        zone_swings=("_swing", lambda values: 0),
    )
    zone_swings = pitches[pitches["_in_zone"] & pitches["_swing"]].groupby("batter").size()
    zone_contacts = pitches[pitches["_in_zone"] & pitches["_contact"]].groupby("batter").size()
    out_zone_pitches = pitches[pitches["_out_zone"]].groupby("batter").size()
    chase_swings = pitches[pitches["_out_zone"] & pitches["_swing"]].groupby("batter").size()

    output: dict[int, dict[str, float]] = {}
    batter_ids = set(grouped.index)
    batter_ids.update(int(index) for index in all_ev90.index)
    batter_ids.update(int(index) for index in air_ev90.index)
    batter_ids.update(int(index) for index in pa_by_batter.index)
    for batter in batter_ids:
        row = grouped.loc[batter] if batter in grouped.index else None
        swings = float(row["swings"]) if row is not None else 0.0
        whiffs = float(row["whiffs"]) if row is not None else 0.0
        contacts = float(row["contacts"]) if row is not None else 0.0
        pitches_seen = float(row["pitches"]) if row is not None else 0.0
        zone_swing_count = float(zone_swings.get(batter, 0.0))
        zone_contact_count = float(zone_contacts.get(batter, 0.0))
        out_zone_count = float(out_zone_pitches.get(batter, 0.0))
        chase_count = float(chase_swings.get(batter, 0.0))
        pa = float(pa_by_batter.get(batter, 0.0))
        strikeouts = float(k_by_batter.get(batter, 0.0))
        walks = float(bb_by_batter.get(batter, 0.0))
        output[int(batter)] = {
            "disciplinePa": pa,
            "ev90": maybe_number(all_ev90.get(batter)),
            "airEv90": maybe_number(air_ev90.get(batter)),
            "airBbe": float(air_bbe.get(batter, 0.0)),
            "contactPct": safe_divide(contacts, swings),
            "whiffPct": safe_divide(whiffs, swings),
            "zoneContactPct": safe_divide(zone_contact_count, zone_swing_count),
            "chasePct": safe_divide(chase_count, out_zone_count),
            "swingingStrikePct": safe_divide(whiffs, pitches_seen),
            "kPct": safe_divide(strikeouts, pa),
            "bbPct": safe_divide(walks, pa),
        }
    return output


def fantasy_adp_bucket(adp: float | None, status: str) -> tuple[str, int | None]:
    if status == "ambiguous":
        return "ambiguous", None
    if adp is None:
        return "undrafted / missing", 0
    if adp <= 100:
        return "top 100", 100
    if adp <= 200:
        return "101-200", 75
    if adp <= 300:
        return "201-300", 50
    return "300+", 25


def load_adp_context(url: str, skip: bool = False) -> dict[str, Any]:
    status: dict[str, Any] = {
        "source": url,
        "status": "skipped" if skip else "not-loaded",
        "fields": [],
        "sourceDates": [],
        "rows": 0,
        "ambiguousNames": {},
    }
    if skip:
        return {"status": status, "byName": {}}
    try:
        tables = pd.read_html(url)
    except Exception as error:  # noqa: BLE001 - context fetch should never block snapshots.
        status["status"] = "failed"
        status["error"] = f"{type(error).__name__}: {error}"
        return {"status": status, "byName": {}}
    if not tables:
        status["status"] = "failed"
        status["error"] = "No ADP tables found"
        return {"status": status, "byName": {}}

    adp = tables[0]
    source_dates = tables[1] if len(tables) > 1 else pd.DataFrame()
    status["status"] = "loaded"
    status["fields"] = list(adp.columns)
    status["rows"] = int(len(adp))
    if not source_dates.empty:
        status["sourceDates"] = [
            {
                "expert": None if pd.isna(row.get("Expert")) else str(row.get("Expert")),
                "site": None if pd.isna(row.get("Site")) else str(row.get("Site")),
                "date": None if pd.isna(row.get("Date")) else str(row.get("Date")),
            }
            for row in source_dates.to_dict(orient="records")
        ]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for _, table_row in adp.iterrows():
        record = table_row.to_dict()
        matched_name = clean_adp_player(record.get("Player (Team)") or record.get("Player"))
        key = normalize_name(matched_name)
        if not key:
            continue
        record["_matchedName"] = matched_name
        grouped.setdefault(key, []).append(record)

    by_name: dict[str, dict[str, Any]] = {}
    ambiguous = {key: value for key, value in grouped.items() if len(value) > 1}
    status["ambiguousNames"] = {
        key: [str(record.get("_matchedName")) for record in value]
        for key, value in ambiguous.items()
    }
    for key, records in grouped.items():
        if len(records) == 1:
            by_name[key] = records[0]
    return {"status": status, "byName": by_name}


def adp_source_date(adp_status: dict[str, Any]) -> str | None:
    dates = []
    for row in adp_status.get("sourceDates") or []:
        site = row.get("site") or row.get("Site")
        date_value = row.get("date") or row.get("Date")
        if site and date_value and not pd.isna(date_value):
            dates.append(f"{site}: {date_value}")
    return "; ".join(dates) if dates else None


def add_adp_context(records: list[dict[str, Any]], adp_context: dict[str, Any]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = adp_context.get("byName", {})
    status = adp_context.get("status", {})
    ambiguous = set(status.get("ambiguousNames", {}).keys())
    source = status.get("source") if status.get("status") == "loaded" else None
    source_date = adp_source_date(status)

    for row in records:
        key = normalize_name(row.get("player"))
        if key in ambiguous:
            row["fantasyAdp"] = None
            row["fantasyAdpBucket"] = "ambiguous"
            row["fantasyAwarenessScore"] = None
            row["adpSource"] = source
            row["adpSourceDate"] = source_date
            row["adpJoinStatus"] = "ambiguous"
            row["adpNameMatched"] = row.get("player")
            continue
        match = by_name.get(key)
        if not match:
            row["fantasyAdp"] = None
            row["fantasyAdpBucket"] = "undrafted / missing"
            row["fantasyAwarenessScore"] = 0 if status.get("status") == "loaded" else None
            row["adpSource"] = source
            row["adpSourceDate"] = source_date
            row["adpJoinStatus"] = "unmatched" if status.get("status") == "loaded" else status.get("status", "not-loaded")
            row["adpNameMatched"] = None
            continue
        adp_value = maybe_number(match.get("AVG"))
        if adp_value is None:
            adp_value = maybe_number(match.get("Overall"))
        bucket, score = fantasy_adp_bucket(adp_value, "matched")
        row["fantasyAdp"] = round(adp_value, 1) if adp_value is not None else None
        row["fantasyAdpBucket"] = bucket
        row["fantasyAwarenessScore"] = score
        row["adpSource"] = source
        row["adpSourceDate"] = source_date
        row["adpJoinStatus"] = "name"
        row["adpNameMatched"] = match.get("_matchedName")
    return records


def fetch_milb_splits_for_player(
    player_id: int,
    api_url: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    splits: list[dict[str, Any]] = []
    errors: list[str] = []
    for sport_id, level in MILB_SPORT_LEVELS.items():
        params = urlencode({"stats": "yearByYear", "group": "hitting", "sportId": sport_id})
        url = f"{api_url.format(player_id=player_id)}?{params}"
        try:
            with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed MLB Stats API URL.
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - MiLB context must never block snapshots.
            errors.append(f"{level}: {type(error).__name__}: {error}")
            continue
        for stat_group in payload.get("stats", []):
            for split in stat_group.get("splits", []):
                stat = split.get("stat") or {}
                pa = maybe_number(stat.get("plateAppearances"))
                if pa is None:
                    at_bats = maybe_number(stat.get("atBats")) or 0.0
                    walks = maybe_number(stat.get("baseOnBalls")) or 0.0
                    hbp = maybe_number(stat.get("hitByPitch")) or 0.0
                    sac_flies = maybe_number(stat.get("sacFlies")) or 0.0
                    sac_bunts = maybe_number(stat.get("sacBunts")) or 0.0
                    pa = at_bats + walks + hbp + sac_flies + sac_bunts
                if pa <= 0:
                    continue
                splits.append(
                    {
                        "season": str(split.get("season") or ""),
                        "level": level,
                        "sportId": sport_id,
                        "pa": pa,
                        "hr": maybe_number(stat.get("homeRuns")) or 0.0,
                        "slg": maybe_number(stat.get("slg")),
                        "ops": maybe_number(stat.get("ops")),
                        "bb": maybe_number(stat.get("baseOnBalls")) or 0.0,
                        "strikeouts": maybe_number(stat.get("strikeOuts")) or 0.0,
                    }
                )
    return splits, errors


def aggregate_milb_splits(splits: list[dict[str, Any]]) -> dict[str, Any]:
    if not splits:
        return {
            "pa": None,
            "hr": None,
            "hrPerPa": None,
            "slg": None,
            "ops": None,
            "bbRate": None,
            "kRate": None,
        }
    pa = sum(number(split.get("pa")) for split in splits)
    hr = sum(number(split.get("hr")) for split in splits)
    bb = sum(number(split.get("bb")) for split in splits)
    strikeouts = sum(number(split.get("strikeouts")) for split in splits)

    def weighted_average(field: str) -> float | None:
        weighted = 0.0
        total = 0.0
        for split in splits:
            value = maybe_number(split.get(field))
            split_pa = number(split.get("pa"))
            if value is None or split_pa <= 0:
                continue
            weighted += value * split_pa
            total += split_pa
        return safe_divide(weighted, total)

    return {
        "pa": pa,
        "hr": hr,
        "hrPerPa": safe_divide(hr, pa),
        "slg": weighted_average("slg"),
        "ops": weighted_average("ops"),
        "bbRate": safe_divide(bb, pa),
        "kRate": safe_divide(strikeouts, pa),
    }


def milb_sample_caution(upper_pa: float, all_pa: float, join_status: str) -> str:
    if join_status == "foreign-pro-context-needed":
        return "foreign/pro track record needed"
    if join_status in {"skipped", "fetch-failed"}:
        return "source missing / manual review"
    if all_pa <= 0:
        return "not enough PA to judge"
    if upper_pa >= 150:
        return "enough upper-minors sample"
    if upper_pa >= 50:
        return "limited upper-minors PA"
    if upper_pa > 0 and all_pa >= 100:
        return "MiLB support leans on all-level data; limited upper-minors PA"
    if all_pa >= 100:
        return "all-level data only; no AA/AAA sample"
    return "not enough PA to judge"


def initialize_empty_milb_context(row: dict[str, Any], status: str, note: str) -> None:
    row["milbDataStatus"] = status
    row["milbHighestLevel"] = None
    row["milbUpperMinorsPA"] = None
    row["milbUpperMinorsHR"] = None
    row["milbUpperMinorsHRPerPA"] = None
    row["milbUpperMinorsSLG"] = None
    row["milbUpperMinorsOPS"] = None
    row["milbUpperMinorsBBRate"] = None
    row["milbUpperMinorsKRate"] = None
    row["milbAllLevelsPA"] = None
    row["milbAllLevelsHR"] = None
    row["milbAllLevelsHRPerPA"] = None
    row["milbAllLevelsSLG"] = None
    row["milbAllLevelsOPS"] = None
    row["milbAllLevelsBBRate"] = None
    row["milbAllLevelsKRate"] = None
    row["milbPowerSupportScore"] = None
    row["milbApproachSupport"] = None
    row["milbPowerCategory"] = "Foreign/pro context missing" if status == "foreign-pro-context-needed" else "Not enough MiLB data"
    row["milbSampleCaution"] = milb_sample_caution(0.0, 0.0, status)
    row["milbSource"] = None
    row["milbSourceSeasonRange"] = None
    row["milbJoinStatus"] = status
    row["milbNote"] = note


def add_raw_milb_context(records: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    status: dict[str, Any] = {
        "source": args.milb_api_url,
        "status": "skipped" if args.skip_milb else "loaded",
        "params": {
            "stats": "yearByYear",
            "group": "hitting",
            "sportIds": MILB_SPORT_LEVELS,
        },
        "rowsAttempted": len(records),
        "errors": {},
    }
    foreign_names = {normalize_name(name) for name in FOREIGN_PRO_CONTEXT_NAMES}
    if args.skip_milb:
        for row in records:
            initialize_empty_milb_context(row, "skipped", "MiLB context skipped by CLI flag")
        return status

    for row in records:
        player_id = row.get("playerId")
        name_key = normalize_name(row.get("player"))
        if name_key in foreign_names:
            initialize_empty_milb_context(
                row,
                "foreign-pro-context-needed",
                "MiLB source does not cover this player's primary non-MLB professional track record.",
            )
            continue
        if player_id is None:
            initialize_empty_milb_context(row, "source-mismatch-manual-review", "Missing MLBAM id for MiLB lookup")
            continue

        splits, errors = fetch_milb_splits_for_player(int(player_id), args.milb_api_url, args.milb_timeout)
        if errors:
            status["errors"][str(player_id)] = errors
        if not splits:
            initialize_empty_milb_context(row, "not-enough-milb-data", "No MiLB splits returned by MLB Stats API")
            if errors:
                row["milbJoinStatus"] = "fetch-failed"
                row["milbNote"] = "; ".join(errors[:2])
                row["milbDataStatus"] = "fetch-failed"
            continue

        upper_splits = [split for split in splits if split["level"] in {"AA", "AAA"}]
        upper = aggregate_milb_splits(upper_splits)
        all_levels = aggregate_milb_splits(splits)
        levels = sorted({split["level"] for split in splits}, key=lambda level: MILB_LEVEL_RANK.get(level, 0), reverse=True)
        seasons = sorted({split["season"] for split in splits if split.get("season")})
        upper_pa = number(upper.get("pa"))
        all_pa = number(all_levels.get("pa"))
        join_status = "matched-aa-aaa" if upper_pa > 0 else "matched-all-levels"
        row["milbDataStatus"] = "matched"
        row["milbHighestLevel"] = levels[0] if levels else None
        row["milbUpperMinorsPA"] = int(upper_pa) if upper_pa > 0 else 0
        row["milbUpperMinorsHR"] = int(number(upper.get("hr"))) if upper_pa > 0 else 0
        row["milbUpperMinorsHRPerPA"] = upper.get("hrPerPa")
        row["milbUpperMinorsSLG"] = upper.get("slg")
        row["milbUpperMinorsOPS"] = upper.get("ops")
        row["milbUpperMinorsBBRate"] = upper.get("bbRate")
        row["milbUpperMinorsKRate"] = upper.get("kRate")
        row["milbAllLevelsPA"] = int(all_pa) if all_pa > 0 else 0
        row["milbAllLevelsHR"] = int(number(all_levels.get("hr"))) if all_pa > 0 else 0
        row["milbAllLevelsHRPerPA"] = all_levels.get("hrPerPa")
        row["milbAllLevelsSLG"] = all_levels.get("slg")
        row["milbAllLevelsOPS"] = all_levels.get("ops")
        row["milbAllLevelsBBRate"] = all_levels.get("bbRate")
        row["milbAllLevelsKRate"] = all_levels.get("kRate")
        row["milbSource"] = args.milb_api_url
        row["milbSourceSeasonRange"] = f"{seasons[0]}-{seasons[-1]}" if seasons else None
        row["milbJoinStatus"] = join_status
        row["milbSampleCaution"] = milb_sample_caution(upper_pa, all_pa, join_status)
        row["milbNote"] = row["milbSampleCaution"]
    return status


def add_milb_scores_and_categories(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(records)
    if frame.empty:
        return []
    upper_pa = pd.to_numeric(frame.get("milbUpperMinorsPA"), errors="coerce").fillna(0)
    all_pa = pd.to_numeric(frame.get("milbAllLevelsPA"), errors="coerce").fillna(0)
    use_upper = upper_pa >= 50
    use_all = ~use_upper & (all_pa >= 100)
    frame["milbScorePA"] = 0.0
    frame["milbScoreHRPerPA"] = float("nan")
    frame["milbScoreSLG"] = float("nan")
    frame["milbScoreOPS"] = float("nan")
    frame["milbScoreBBRate"] = float("nan")
    frame["milbScoreKRate"] = float("nan")

    frame.loc[use_upper, "milbScorePA"] = upper_pa.loc[use_upper]
    frame.loc[use_upper, "milbScoreHRPerPA"] = pd.to_numeric(frame.loc[use_upper, "milbUpperMinorsHRPerPA"], errors="coerce")
    frame.loc[use_upper, "milbScoreSLG"] = pd.to_numeric(frame.loc[use_upper, "milbUpperMinorsSLG"], errors="coerce")
    frame.loc[use_upper, "milbScoreOPS"] = pd.to_numeric(frame.loc[use_upper, "milbUpperMinorsOPS"], errors="coerce")
    frame.loc[use_upper, "milbScoreBBRate"] = pd.to_numeric(frame.loc[use_upper, "milbUpperMinorsBBRate"], errors="coerce")
    frame.loc[use_upper, "milbScoreKRate"] = pd.to_numeric(frame.loc[use_upper, "milbUpperMinorsKRate"], errors="coerce")

    frame.loc[use_all, "milbScorePA"] = all_pa.loc[use_all]
    frame.loc[use_all, "milbScoreHRPerPA"] = pd.to_numeric(frame.loc[use_all, "milbAllLevelsHRPerPA"], errors="coerce")
    frame.loc[use_all, "milbScoreSLG"] = pd.to_numeric(frame.loc[use_all, "milbAllLevelsSLG"], errors="coerce")
    frame.loc[use_all, "milbScoreOPS"] = pd.to_numeric(frame.loc[use_all, "milbAllLevelsOPS"], errors="coerce")
    frame.loc[use_all, "milbScoreBBRate"] = pd.to_numeric(frame.loc[use_all, "milbAllLevelsBBRate"], errors="coerce")
    frame.loc[use_all, "milbScoreKRate"] = pd.to_numeric(frame.loc[use_all, "milbAllLevelsKRate"], errors="coerce")

    frame["scoreMilbHRPerPA"] = percentile_scores(frame["milbScoreHRPerPA"])
    frame["scoreMilbSLG"] = percentile_scores(frame["milbScoreSLG"])
    frame["scoreMilbOPS"] = percentile_scores(frame["milbScoreOPS"])
    frame["scoreMilbBBRate"] = percentile_scores(frame["milbScoreBBRate"])
    frame["scoreMilbInverseKRate"] = percentile_scores(-pd.to_numeric(frame["milbScoreKRate"], errors="coerce"))
    frame["scoreMilbSlugOps"] = weighted_score(frame, {"scoreMilbSLG": 0.50, "scoreMilbOPS": 0.50})
    frame["milbPowerSupportScore"] = weighted_score(
        frame,
        {
            "scoreMilbHRPerPA": 0.50,
            "scoreMilbSlugOps": 0.25,
            "scoreMilbInverseKRate": 0.15,
            "scoreMilbBBRate": 0.10,
        },
    )
    frame["milbApproachSupport"] = weighted_score(
        frame,
        {
            "scoreMilbInverseKRate": 0.60,
            "scoreMilbBBRate": 0.40,
        },
    )

    categories: list[str] = []
    notes: list[str] = []
    for _, row in frame.iterrows():
        join_status = str(row.get("milbJoinStatus") or "")
        if join_status == "foreign-pro-context-needed":
            categories.append("Foreign/pro context missing")
            notes.append(str(row.get("milbNote") or "Non-MLB professional context needed"))
            continue
        if join_status in {"skipped", "fetch-failed", "source-mismatch-manual-review"}:
            categories.append("Source mismatch / manual review")
            notes.append(str(row.get("milbNote") or "MiLB source missing or unavailable"))
            continue
        score = maybe_number(row.get("milbPowerSupportScore"))
        approach = maybe_number(row.get("milbApproachSupport"))
        sample_pa = number(row.get("milbScorePA"))
        hr_per_pa = maybe_number(row.get("milbScoreHRPerPA"))
        if score is None or sample_pa < 50:
            categories.append("Not enough MiLB data")
        elif score >= 120 and (hr_per_pa is None or hr_per_pa >= 0.035):
            categories.append("Strong MiLB power support")
        elif score >= 105:
            categories.append("Solid MiLB power support")
        elif approach is not None and approach >= 115:
            categories.append("Contact/approach support, modest power")
        else:
            categories.append("Weak MiLB power support")
        notes.append(str(row.get("milbSampleCaution") or ""))
    frame["milbPowerCategory"] = categories
    frame["milbNote"] = notes
    rounded: list[dict[str, Any]] = []
    rate_fields = {
        "milbUpperMinorsHRPerPA",
        "milbUpperMinorsSLG",
        "milbUpperMinorsOPS",
        "milbUpperMinorsBBRate",
        "milbUpperMinorsKRate",
        "milbAllLevelsHRPerPA",
        "milbAllLevelsSLG",
        "milbAllLevelsOPS",
        "milbAllLevelsBBRate",
        "milbAllLevelsKRate",
        "milbScoreHRPerPA",
        "milbScoreSLG",
        "milbScoreOPS",
        "milbScoreBBRate",
        "milbScoreKRate",
    }
    score_fields = {
        "milbPowerSupportScore",
        "milbApproachSupport",
        "scoreMilbHRPerPA",
        "scoreMilbSLG",
        "scoreMilbOPS",
        "scoreMilbBBRate",
        "scoreMilbInverseKRate",
        "scoreMilbSlugOps",
    }
    for record in frame.to_dict(orient="records"):
        for key, value in list(record.items()):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                record[key] = None
        for key in rate_fields:
            if record.get(key) is not None:
                record[key] = round(float(record[key]), 5)
        for key in score_fields:
            if record.get(key) is not None:
                record[key] = round(float(record[key]), 1)
        for key in ["milbScorePA"]:
            if record.get(key) is not None:
                record[key] = int(record[key])
        rounded.append(record)
    return rounded


def add_consensus_context_categories(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in records:
        b6_air = number(row.get("b6Air"), -999)
        hr = number(row.get("hr"))
        current_hr_per_pa = number(row.get("currentHrPerPa"))
        fantasy_bucket = str(row.get("fantasyAdpBucket") or "")
        milb_category = str(row.get("milbPowerCategory") or "")
        high_storm = b6_air >= 110
        weak_storm = b6_air < 105
        high_adp = fantasy_bucket in {"top 100", "101-200"}
        low_adp = fantasy_bucket in {"300+", "undrafted / missing", "ambiguous"}
        mlb_obviousness = 100 if (hr >= 10 or current_hr_per_pa >= 0.055) else (65 if (hr >= 6 or current_hr_per_pa >= 0.04) else 0)
        strong_milb = milb_category in {"Strong MiLB power support", "Solid MiLB power support"}
        weak_or_missing_milb = milb_category in {
            "Weak MiLB power support",
            "Not enough MiLB data",
            "Source mismatch / manual review",
        }
        tags: list[str] = []
        if milb_category == "Foreign/pro context missing":
            tags.append("Foreign/Pro Context Needed")
        if high_storm and strong_milb:
            tags.append("Track Record Supports")
        if high_storm and (high_adp or mlb_obviousness >= 65):
            tags.append("Storm Confirms")
        if high_storm and low_adp and mlb_obviousness < 65 and strong_milb:
            tags.append("Consensus Gap")
        if high_storm and low_adp and weak_or_missing_milb:
            tags.append("Statcast Flash")
        if high_adp and weak_storm:
            tags.append("Market Ahead Of Signal")
        if not tags:
            tags.append("Other context")
        priority = [
            "Foreign/Pro Context Needed",
            "Consensus Gap",
            "Storm Confirms",
            "Track Record Supports",
            "Statcast Flash",
            "Market Ahead Of Signal",
            "Other context",
        ]
        row["mlbProductionObviousness"] = mlb_obviousness
        row["consensusContextTags"] = tags
        row["consensusContextCategory"] = next((label for label in priority if label in tags), tags[0])
    return records


def add_milb_context(records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = add_raw_milb_context(records, args)
    records = add_milb_scores_and_categories(records)
    records = add_consensus_context_categories(records)
    status["status"] = "skipped" if args.skip_milb else "loaded"
    return records, status


def classify_bucket(age: float | None, low_history: bool, bbe: int) -> tuple[str, str, str]:
    if age is None:
        return "Unbucketed", "Missing age", "Age missing; cannot assign Storm Watch bucket"
    if low_history and 24 <= age < 26:
        return "Prime Emergence", "High Trust", "Validated 24-to-25 low-history bucket"
    if low_history and 21 <= age < 23:
        if bbe >= 250:
            return "Early Emergence", "Candidate", "Early BBE >= 250 stronger internal context"
        return "Early Emergence", "Candidate", "Early signal; sample below BBE >= 250 context line"
    if low_history and age < 26:
        return "Other <=25 Low-History", "Caution", "Low-history <=25, but this age bucket is not validated"
    if low_history and 26 <= age < 28:
        return "Late-Arrival Reference", "Internal reference only", "26-27 low-history; not public young-power promise"
    return "Out of Scope", "Out of scope", "Established or outside Storm Watch age scope"


def contact_risk_tag(row: dict[str, Any]) -> tuple[str, str]:
    contact = row.get("contactPct")
    whiff = row.get("whiffPct")
    if contact is None or whiff is None:
        return "unknown-contact-risk", "durability-unknown"
    if contact <= 0.73 or whiff >= 0.27:
        return "contact-whiff-risk", "durability-caution"
    if contact <= 0.75 or whiff >= 0.25:
        return "mild-contact-risk", "durability-watch"
    return "no-contact-risk", "durability-context-clean"


def missing_reasons(row: dict[str, Any]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for field in [
        "age",
        "airEv90",
        "contactPct",
        "whiffPct",
        "zoneContactPct",
        "chasePct",
        "kPct",
        "bbPct",
    ]:
        if row.get(field) is None:
            if field == "age":
                reasons[field] = "player missing from people cache"
            elif field == "airEv90":
                reasons[field] = "no lifted 15-45 degree batted balls in pitch cache"
            else:
                reasons[field] = "no current pitch-cache denominator for discipline metric"
    return reasons


def base_player_record(
    row: dict[str, Any],
    age_lookup: dict[int, str],
    pitch_by_batter: dict[int, dict[str, float]],
    snapshot_day: date,
    prior: dict[int, dict[str, float]],
    league_prior: dict[str, float],
) -> dict[str, Any] | None:
    batter = row.get("batter") or row.get("playerId")
    if batter is None:
        return None
    batter_id = int(batter)
    pa = number(row.get("pa"))
    bbe = number(row.get("bbe"))
    if pa <= 0 or bbe <= 0:
        return None

    prior_row = prior.get(
        batter_id,
        {
            "priorSeasonCount": 0,
            "priorPaTotal": 0.0,
            "previousSeasonPa": 0.0,
            "previousXhrPerBbe": float("nan"),
            "previousThunderRate": float("nan"),
        },
    )
    previous_season_pa = float(prior_row["previousSeasonPa"])
    previous_xhr = prior_row["previousXhrPerBbe"]
    previous_thunder = prior_row["previousThunderRate"]
    has_previous_xhr = not math.isnan(previous_xhr)
    has_previous_thunder = not math.isnan(previous_thunder)
    prior_seasons = int(prior_row["priorSeasonCount"])
    prior_pa_total = float(prior_row["priorPaTotal"])
    no_prior = prior_seasons == 0 or previous_season_pa <= 0
    low_history = previous_season_pa < 300
    missing_previous_baseline = not (has_previous_xhr or has_previous_thunder)

    current_xhr_per_bbe = number(row.get("xhrPerBbe"))
    current_thunder_rate = number(row.get("hrWindowThunderRate"))
    pitch_context_row = pitch_by_batter.get(batter_id, {})
    ev90 = pitch_context_row.get("ev90")
    air_ev90 = pitch_context_row.get("airEv90")
    air_bbe = number(pitch_context_row.get("airBbe"))
    barrel_per_pa = number(row.get("barrelRate")) * bbe / pa
    thunder_per_pa = number(row.get("hrWindowThunderBbe")) / pa
    pulled_air_per_pa = number(row.get("pulledAirBbe")) / pa
    hr_per_pa = number(row.get("hr")) / pa

    mx = 150 if has_previous_xhr else 317
    mt = 100 if has_previous_thunder else 317
    wx = bbe / (bbe + mx)
    wt = bbe / (bbe + mt)
    prior_xhr = previous_xhr if has_previous_xhr else league_prior["previousXhrPerBbe"]
    prior_thunder = previous_thunder if has_previous_thunder else league_prior["previousThunderRate"]

    age = age_at(age_lookup.get(batter_id), snapshot_day)
    bucket_label, bucket_confidence, bbe_note = classify_bucket(age, low_history, int(bbe))

    output = {
        "playerId": batter_id,
        "player": str(row.get("player") or ""),
        "team": str(row.get("team") or ""),
        "age": age,
        "pa": int(pa),
        "bbe": int(bbe),
        "hr": int(number(row.get("hr"))),
        "previousSeasonPa": int(previous_season_pa),
        "priorSeasonCount": prior_seasons,
        "priorPaTotal": round(prior_pa_total, 1),
        "noPrior": no_prior,
        "lowHistory": low_history,
        "missingPreviousSeasonBaseline": missing_previous_baseline,
        "priorStatus": "no-prior" if no_prior else ("low-history" if low_history else "established"),
        "bucketLabel": bucket_label,
        "bucketConfidence": bucket_confidence,
        "bbeConfidenceNote": bbe_note,
        "xhrPerBbe": current_xhr_per_bbe,
        "thunderRate": current_thunder_rate,
        "hrWindowThunderBbe": int(number(row.get("hrWindowThunderBbe"))),
        "barrelRate": number(row.get("barrelRate")),
        "barrelPerPa": barrel_per_pa,
        "thunderPerPa": thunder_per_pa,
        "pulledAirbornePerPa": pulled_air_per_pa,
        "currentHrPerPa": hr_per_pa,
        "ev90": ev90,
        "airEv90": air_ev90,
        "airBbe": int(air_bbe),
        "stabilizedXhrPerBbe": wx * current_xhr_per_bbe + (1 - wx) * prior_xhr,
        "stabilizedThunderRate": wt * current_thunder_rate + (1 - wt) * prior_thunder,
        "disciplinePa": pitch_context_row.get("disciplinePa"),
        "contactPct": pitch_context_row.get("contactPct"),
        "whiffPct": pitch_context_row.get("whiffPct"),
        "zoneContactPct": pitch_context_row.get("zoneContactPct"),
        "chasePct": pitch_context_row.get("chasePct"),
        "swingingStrikePct": pitch_context_row.get("swingingStrikePct"),
        "kPct": pitch_context_row.get("kPct"),
        "bbPct": pitch_context_row.get("bbPct"),
    }
    output["contactRiskTag"], output["durabilityTag"] = contact_risk_tag(output)
    output["missingReasons"] = missing_reasons(output)
    return output


def add_scores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(records)
    if frame.empty:
        return []

    league_air_ev90 = frame["airEv90"].dropna().mean()
    if pd.isna(league_air_ev90):
        league_air_ev90 = frame["ev90"].dropna().mean()
    frame["airEv90ForScoring"] = frame["airEv90"].fillna(league_air_ev90)
    missing_previous_baseline = frame["missingPreviousSeasonBaseline"].fillna(False)
    air_bbe = frame["airBbe"].fillna(0)
    ev_weight = air_bbe / (air_bbe + 62)
    frame.loc[missing_previous_baseline, "airEv90ForScoring"] = (
        ev_weight.loc[missing_previous_baseline] * frame.loc[missing_previous_baseline, "airEv90ForScoring"]
        + (1 - ev_weight.loc[missing_previous_baseline]) * league_air_ev90
    )

    score_inputs = {
        "scoreStabilizedXhrPerBbe": "stabilizedXhrPerBbe",
        "scoreStabilizedThunderRate": "stabilizedThunderRate",
        "scoreAirEv90": "airEv90ForScoring",
        "scoreBarrelPerPa": "barrelPerPa",
        "scoreThunderPerPa": "thunderPerPa",
        "scoreCurrentHrPerPa": "currentHrPerPa",
        "scorePositiveLag": "positiveLag",
    }
    for score_column, source_column in list(score_inputs.items())[:-1]:
        frame[score_column] = percentile_scores(frame[source_column])

    frame["stormFuelA2"] = weighted_score(
        frame,
        {
            "scoreStabilizedXhrPerBbe": 0.50,
            "scoreStabilizedThunderRate": 0.25,
            "scoreAirEv90": 0.25,
        },
    )
    frame["b6Air"] = weighted_score(
        frame,
        {
            "stormFuelA2": 0.60,
            "scoreBarrelPerPa": 0.20,
            "scoreThunderPerPa": 0.20,
        },
    )
    frame["emergenceGap"] = frame["b6Air"] - frame["scoreCurrentHrPerPa"]
    frame["positiveLag"] = frame["emergenceGap"].clip(lower=0)
    frame["scorePositiveLag"] = percentile_scores(frame["positiveLag"])
    frame["exposureNovelty"] = (1 - (frame["previousSeasonPa"].clip(lower=0, upper=300) / 300)) * 100
    numeric_age = pd.to_numeric(frame["age"], errors="coerce")
    frame["ageRunway"] = ((26 - numeric_age) / 5).clip(lower=0, upper=1) * 100
    frame["emergenceScore"] = weighted_score(
        frame,
        {
            "b6Air": 0.70,
            "scorePositiveLag": 0.10,
            "exposureNovelty": 0.10,
            "ageRunway": 0.10,
        },
    )
    frame["stormWatchRank"] = frame["b6Air"].rank(method="first", ascending=False).astype(int)
    frame["bucketRank"] = frame.groupby("bucketLabel")["b6Air"].rank(method="first", ascending=False)

    rounded = []
    for row in frame.to_dict(orient="records"):
        for key, value in list(row.items()):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                row[key] = None
        for key in [
            "age",
            "xhrPerBbe",
            "thunderRate",
            "barrelRate",
            "barrelPerPa",
            "thunderPerPa",
            "pulledAirbornePerPa",
            "currentHrPerPa",
            "ev90",
            "airEv90",
            "stabilizedXhrPerBbe",
            "stabilizedThunderRate",
            "contactPct",
            "whiffPct",
            "zoneContactPct",
            "chasePct",
            "swingingStrikePct",
            "kPct",
            "bbPct",
            "stormFuelA2",
            "b6Air",
            "emergenceGap",
            "positiveLag",
            "exposureNovelty",
            "ageRunway",
            "emergenceScore",
        ]:
            if key in row and row[key] is not None:
                if key == "age":
                    decimals = 2
                elif key.endswith("Pct") or key.endswith("Rate") or key.endswith("PerPa") or key in {"xhrPerBbe", "thunderRate", "barrelRate", "barrelPerPa", "thunderPerPa", "currentHrPerPa", "stabilizedXhrPerBbe", "stabilizedThunderRate", "contactPct", "whiffPct", "zoneContactPct", "chasePct", "swingingStrikePct", "kPct", "bbPct"}:
                    decimals = 5
                else:
                    decimals = 1
                row[key] = round(float(row[key]), decimals)
        if row.get("bucketRank") is not None:
            row["bucketRank"] = int(row["bucketRank"])
        rounded.append(row)
    return rounded


def sort_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (-number(row.get("b6Air"), -999), str(row.get("player"))))[:limit]


def compact_entry(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "playerId",
        "player",
        "team",
        "age",
        "pa",
        "bbe",
        "hr",
        "previousSeasonPa",
        "priorStatus",
        "bucketLabel",
        "bucketConfidence",
        "bbeConfidenceNote",
        "stormWatchRank",
        "bucketRank",
        "b6Air",
        "stormFuelA2",
        "emergenceScore",
        "emergenceGap",
        "positiveLag",
        "exposureNovelty",
        "ageRunway",
        "xhrPerBbe",
        "stabilizedXhrPerBbe",
        "thunderRate",
        "stabilizedThunderRate",
        "airEv90",
        "barrelPerPa",
        "thunderPerPa",
        "contactPct",
        "whiffPct",
        "zoneContactPct",
        "chasePct",
        "kPct",
        "bbPct",
        "durabilityTag",
        "contactRiskTag",
        "fantasyAdp",
        "fantasyAdpBucket",
        "fantasyAwarenessScore",
        "adpSource",
        "adpSourceDate",
        "adpJoinStatus",
        "adpNameMatched",
        "milbDataStatus",
        "milbHighestLevel",
        "milbUpperMinorsPA",
        "milbUpperMinorsHR",
        "milbUpperMinorsHRPerPA",
        "milbUpperMinorsSLG",
        "milbUpperMinorsOPS",
        "milbUpperMinorsBBRate",
        "milbUpperMinorsKRate",
        "milbAllLevelsPA",
        "milbAllLevelsHR",
        "milbAllLevelsHRPerPA",
        "milbAllLevelsSLG",
        "milbAllLevelsOPS",
        "milbAllLevelsBBRate",
        "milbAllLevelsKRate",
        "milbPowerSupportScore",
        "milbApproachSupport",
        "milbPowerCategory",
        "milbSampleCaution",
        "milbSource",
        "milbSourceSeasonRange",
        "milbJoinStatus",
        "milbNote",
        "mlbProductionObviousness",
        "consensusContextCategory",
        "consensusContextTags",
        "missingReasons",
    ]
    return {key: row.get(key) for key in keys}


def missing_field_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    fields = [
        "age",
        "previousSeasonPa",
        "b6Air",
        "stormFuelA2",
        "xhrPerBbe",
        "stabilizedXhrPerBbe",
        "thunderRate",
        "stabilizedThunderRate",
        "airEv90",
        "barrelPerPa",
        "thunderPerPa",
        "emergenceScore",
        "emergenceGap",
        "positiveLag",
        "exposureNovelty",
        "ageRunway",
        "contactPct",
        "whiffPct",
        "zoneContactPct",
        "chasePct",
        "kPct",
        "bbPct",
        "durabilityTag",
        "contactRiskTag",
        "bbeConfidenceNote",
        "fantasyAdp",
        "fantasyAdpBucket",
        "fantasyAwarenessScore",
        "adpSource",
        "adpSourceDate",
        "adpJoinStatus",
        "adpNameMatched",
        "milbDataStatus",
        "milbHighestLevel",
        "milbUpperMinorsPA",
        "milbUpperMinorsHR",
        "milbUpperMinorsHRPerPA",
        "milbUpperMinorsSLG",
        "milbUpperMinorsOPS",
        "milbUpperMinorsBBRate",
        "milbUpperMinorsKRate",
        "milbAllLevelsPA",
        "milbAllLevelsHR",
        "milbAllLevelsHRPerPA",
        "milbAllLevelsSLG",
        "milbAllLevelsOPS",
        "milbAllLevelsBBRate",
        "milbAllLevelsKRate",
        "milbPowerSupportScore",
        "milbApproachSupport",
        "milbPowerCategory",
        "milbSampleCaution",
        "milbSource",
        "milbSourceSeasonRange",
        "milbJoinStatus",
        "milbNote",
        "mlbProductionObviousness",
        "consensusContextCategory",
        "consensusContextTags",
    ]
    return {field: sum(1 for row in players if row.get(field) is None) for field in fields}


def adp_join_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in players:
        status = str(row.get("adpJoinStatus") or "missing")
        counts[status] = counts.get(status, 0) + 1
    return counts


def field_counts(players: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in players:
        value = row.get(field)
        if isinstance(value, list):
            keys = value or ["missing"]
        else:
            keys = [str(value or "missing")]
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return counts


def build_snapshot(payload: dict[str, Any], args: argparse.Namespace, snapshot_date: str) -> dict[str, Any]:
    season = int(payload.get("season") or 2026)
    snapshot_day = parse_date(snapshot_date)
    age_lookup = load_people_birth_dates(args.people_cache)
    pitch_by_batter = pitch_context(args.statcast_cache)
    prior, league_prior = prior_context(season)
    adp_context = load_adp_context(args.adp_url, args.skip_adp)
    records = [
        base_player_record(row, age_lookup, pitch_by_batter, snapshot_day, prior, league_prior)
        for row in payload.get("players", [])
        if isinstance(row, dict)
    ]
    players = add_adp_context(add_scores([record for record in records if record is not None]), adp_context)
    players, milb_status = add_milb_context(players, args)
    low_history_25 = [row for row in players if row.get("lowHistory") and row.get("age") is not None and row["age"] < 26]
    early = [row for row in players if row.get("bucketLabel") == "Early Emergence"]
    early_bbe_250 = [row for row in early if row.get("bbe", 0) >= 250]
    prime = [row for row in players if row.get("bucketLabel") == "Prime Emergence"]
    late = [row for row in players if row.get("bucketLabel") == "Late-Arrival Reference"]
    watchlists = {
        "primeEmergence": [compact_entry(row) for row in sort_rows(prime, args.limit)],
        "earlyEmergence": [compact_entry(row) for row in sort_rows(early, args.limit)],
        "earlyEmergenceBbe250": [compact_entry(row) for row in sort_rows(early_bbe_250, args.limit)],
        "allLowHistoryAgeLe25": [compact_entry(row) for row in sort_rows(low_history_25, args.limit)],
        "lateArrivalReference26To27": [compact_entry(row) for row in sort_rows(late, args.limit)],
    }
    bucket_counts = {}
    for row in players:
        bucket_counts[row["bucketLabel"]] = bucket_counts.get(row["bucketLabel"], 0) + 1
    return {
        "snapshotDate": snapshot_date,
        "generatedAt": payload.get("generatedAt"),
        "season": season,
        "sourcePath": str(args.input),
        "statcastCachePath": str(args.statcast_cache),
        "peopleCachePath": str(args.people_cache),
        "model": {
            "name": "Storm Watch shadow",
            "status": "internal-shadow",
            "identity": "Storm Watch is an internal Young Power Radar for low-history hitters whose MLB power signal is forming before the track record exists.",
            "score": {
                "primary": "B6-Air",
                "definition": "60% Storm Fuel A2 + 20% Barrel/PA + 20% HR-Window Thunder/PA.",
                "stormFuelA2": "50% stabilized xHR/BBE + 25% stabilized HR-Window Thunder Rate + 25% Air EV90.",
                "airEv90": "90th-percentile EV on lifted damage-zone contact, launch angle 15-45 degrees.",
                "stabilization": {
                    "realPrior": "xHR/BBE M=150, HR-Window Thunder Rate M=100.",
                    "noPrior": "xHR/Thunder shrink toward league average at M=317; Air EV90 shrinks toward current pool average at M=62 using air-BBE denominator.",
                },
            },
            "buckets": {
                "primeEmergence": "24-to-25 low-history (24 <= age < 26), previous-season PA < 300, High Trust.",
                "earlyEmergence": "21 <= age < 23, previous-season PA < 300, Candidate.",
                "earlyEmergenceBbe250": "Early Emergence with BBE >= 250; stronger internal context only.",
                "otherAgeLe25LowHistory": "Other low-history age <=25 buckets; provisional/caution.",
                "lateArrivalReference": "26 <= age < 28 low-history; internal reference only.",
            },
            "contextPolicy": {
                "emergenceScore": "Secondary context only: B6-Air plus positive realized-HR lag, exposure novelty, and age runway.",
                "durability": "Contact/whiff/chase/K/BB are confidence context only, not score inputs.",
                "fantasyAdp": "Fantasy ADP is current market-awareness context only, never a B6-Air input.",
                "milbPowerSupport": "MLB Stats API MiLB power support is pre-MLB track-record context only, never a B6-Air input.",
                "consensusTodo": "Future validation should compare surfaced names against public consensus/projection/prospect context to ask whether Storm Watch found useful names before the broader market did.",
            },
        },
        "consensusContext": {
            "fantasyAdp": {
                "source": adp_context.get("status", {}).get("source"),
                "sourceDates": adp_context.get("status", {}).get("sourceDates", []),
                "status": adp_context.get("status", {}).get("status"),
                "fields": adp_context.get("status", {}).get("fields", []),
                "rows": adp_context.get("status", {}).get("rows", 0),
                "ambiguousNames": adp_context.get("status", {}).get("ambiguousNames", {}),
                "joinCounts": adp_join_counts(players),
                "buckets": {
                    "top 100": "fantasyAdp <= 100",
                    "101-200": "100 < fantasyAdp <= 200",
                    "201-300": "200 < fantasyAdp <= 300",
                    "300+": "fantasyAdp > 300",
                    "undrafted / missing": "No FantasyPros ADP row matched by normalized name.",
                    "ambiguous": "Multiple ADP rows share the same normalized name; no value selected.",
                },
            },
            "milbPowerSupport": {
                "source": milb_status.get("source"),
                "status": milb_status.get("status"),
                "params": milb_status.get("params", {}),
                "rowsAttempted": milb_status.get("rowsAttempted", 0),
                "joinCounts": field_counts(players, "milbJoinStatus"),
                "categoryCounts": field_counts(players, "milbPowerCategory"),
                "contextCategoryCounts": field_counts(players, "consensusContextCategory"),
                "tagCounts": field_counts(players, "consensusContextTags"),
                "sampleCautionCounts": field_counts(players, "milbSampleCaution"),
                "errors": milb_status.get("errors", {}),
                "levelPriority": "AA + AAA are preferred; all-level aggregate is fallback/context when upper-minors PA is limited.",
                "foreignProPolicy": "NPB/KBO/foreign professional players are marked as needing separate context rather than weak MiLB support.",
            },
        },
        "coverage": {
            "players": len(players),
            "bucketCounts": bucket_counts,
            "missingFieldCounts": missing_field_counts(players),
        },
        "watchlists": watchlists,
        "players": players,
    }


def write_snapshot(snapshot: dict[str, Any], output_dir: Path, replace_existing: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"snapshot_{snapshot['snapshotDate']}.json"
    if path.exists() and not replace_existing:
        raise SystemExit(f"Refusing to overwrite existing snapshot: {path}")
    path.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_review_outputs(snapshot: dict[str, Any], review_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    stem = f"storm_watch_shadow_{snapshot['snapshotDate']}"
    json_path = review_dir / f"{stem}.json"
    csv_path = review_dir / f"{stem}.csv"
    adp_stem = f"storm_watch_adp_context_{snapshot['season']}"
    adp_json_path = review_dir / f"{adp_stem}.json"
    adp_csv_path = review_dir / f"{adp_stem}.csv"
    milb_stem = f"storm_watch_milb_context_{snapshot['season']}"
    milb_json_path = review_dir / f"{milb_stem}.json"
    milb_csv_path = review_dir / f"{milb_stem}.csv"
    compact_rows = [compact_entry(row) for row in snapshot["players"]]
    json_path.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(compact_rows).to_csv(csv_path, index=False)
    context_review = {
        "snapshotDate": snapshot["snapshotDate"],
        "season": snapshot["season"],
        "sourcePath": snapshot["sourcePath"],
        "consensusContext": snapshot.get("consensusContext", {}),
        "coverage": snapshot.get("coverage", {}),
        "rows": compact_rows,
    }
    adp_json_path.write_text(json.dumps(context_review, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(compact_rows).to_csv(adp_csv_path, index=False)
    milb_json_path.write_text(json.dumps(context_review, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(compact_rows).to_csv(milb_csv_path, index=False)
    return csv_path, json_path, adp_csv_path, adp_json_path, milb_csv_path, milb_json_path


def print_watchlist(name: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{name}")
    if not rows:
        print("- none")
        return
    for index, row in enumerate(rows, 1):
        age = "NA" if row["age"] is None else f"{row['age']:.2f}"
        print(
            f"{index:2}. {row['player']:<24} {row['team']:<3} | age {age} | "
            f"{row['priorStatus']:<11} | PA {row['pa']:3} BBE {row['bbe']:3} HR {row['hr']:2} | "
            f"B6-Air {row['b6Air']:6.1f} | AirEV90 {row['airEv90'] if row['airEv90'] is not None else 'NA'} | "
            f"{row['bucketConfidence']} | {row['contactRiskTag']}"
        )


def print_summary(snapshot: dict[str, Any], paths: tuple[Path, Path, Path, Path, Path, Path, Path]) -> None:
    snapshot_path, csv_path, json_path, adp_csv_path, adp_json_path, milb_csv_path, milb_json_path = paths
    print(f"Storm Watch shadow snapshot: {snapshot['snapshotDate']}")
    print(f"Rows: {snapshot['coverage']['players']}")
    print("Bucket counts:")
    for bucket, count in sorted(snapshot["coverage"]["bucketCounts"].items()):
        print(f"- {bucket}: {count}")
    print("Missing field counts:")
    for field, count in snapshot["coverage"]["missingFieldCounts"].items():
        if count:
            print(f"- {field}: {count}")
    fantasy_context = snapshot.get("consensusContext", {}).get("fantasyAdp", {})
    if fantasy_context:
        print("Fantasy ADP context:")
        print(f"- status: {fantasy_context.get('status')}")
        print(f"- source: {fantasy_context.get('source')}")
        for status, count in sorted(fantasy_context.get("joinCounts", {}).items()):
            print(f"- {status}: {count}")
    milb_context = snapshot.get("consensusContext", {}).get("milbPowerSupport", {})
    if milb_context:
        print("MiLB power-support context:")
        print(f"- status: {milb_context.get('status')}")
        print(f"- source: {milb_context.get('source')}")
        for status, count in sorted(milb_context.get("joinCounts", {}).items()):
            print(f"- {status}: {count}")
        print("MiLB power categories:")
        for category, count in sorted(milb_context.get("categoryCounts", {}).items()):
            print(f"- {category}: {count}")
        print("Consensus context categories:")
        for category, count in sorted(milb_context.get("contextCategoryCounts", {}).items()):
            print(f"- {category}: {count}")
    print_watchlist("Top 25 Prime Emergence", snapshot["watchlists"]["primeEmergence"])
    print_watchlist("Top 25 Early Emergence", snapshot["watchlists"]["earlyEmergence"])
    print_watchlist("Top 25 Early Emergence BBE >= 250", snapshot["watchlists"]["earlyEmergenceBbe250"])
    print_watchlist("Top 25 All Low-History <=25", snapshot["watchlists"]["allLowHistoryAgeLe25"])
    print_watchlist("26-27 Late-Arrival Reference", snapshot["watchlists"]["lateArrivalReference26To27"])
    print(f"\nSnapshot path: {snapshot_path}")
    print(f"Review CSV: {csv_path}")
    print(f"Review JSON: {json_path}")
    print(f"ADP context CSV: {adp_csv_path}")
    print(f"ADP context JSON: {adp_json_path}")
    print(f"MiLB context CSV: {milb_csv_path}")
    print(f"MiLB context JSON: {milb_json_path}")


def main() -> None:
    args = parse_args()
    payload = load_json(args.input)
    snapshot_date = parse_snapshot_date(payload, args.date)
    snapshot = build_snapshot(payload, args, snapshot_date)
    snapshot_path = write_snapshot(snapshot, args.output_dir, args.replace_existing)
    csv_path, json_path, adp_csv_path, adp_json_path, milb_csv_path, milb_json_path = write_review_outputs(snapshot, args.review_dir)
    print_summary(snapshot, (snapshot_path, csv_path, json_path, adp_csv_path, adp_json_path, milb_csv_path, milb_json_path))


if __name__ == "__main__":
    main()
