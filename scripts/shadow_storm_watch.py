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
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd


DEFAULT_INPUT = Path("public/data/hr-distance-latest.json")
DEFAULT_STATCAST_CACHE = Path("data/raw/statcast-pitches.csv")
DEFAULT_PEOPLE_CACHE = Path("data/cache/longball-threat-backtest/player-people-cache.json")
DEFAULT_OUTPUT_DIR = Path("data/shadow/storm_watch")
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)

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


def classify_bucket(age: float | None, low_history: bool, bbe: int) -> tuple[str, str, str]:
    if age is None:
        return "Unbucketed", "Missing age", "Age missing; cannot assign Storm Watch bucket"
    if low_history and 24 <= age < 26:
        return "Prime Emergence", "High Trust", "Validated age 24-25 low-history bucket"
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
    ]
    return {field: sum(1 for row in players if row.get(field) is None) for field in fields}


def build_snapshot(payload: dict[str, Any], args: argparse.Namespace, snapshot_date: str) -> dict[str, Any]:
    season = int(payload.get("season") or 2026)
    snapshot_day = parse_date(snapshot_date)
    age_lookup = load_people_birth_dates(args.people_cache)
    pitch_by_batter = pitch_context(args.statcast_cache)
    prior, league_prior = prior_context(season)
    records = [
        base_player_record(row, age_lookup, pitch_by_batter, snapshot_day, prior, league_prior)
        for row in payload.get("players", [])
        if isinstance(row, dict)
    ]
    players = add_scores([record for record in records if record is not None])
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
                "primeEmergence": "24 <= age < 26, previous-season PA < 300, High Trust.",
                "earlyEmergence": "21 <= age < 23, previous-season PA < 300, Candidate.",
                "earlyEmergenceBbe250": "Early Emergence with BBE >= 250; stronger internal context only.",
                "otherAgeLe25LowHistory": "Other low-history age <=25 buckets; provisional/caution.",
                "lateArrivalReference": "26 <= age < 28 low-history; internal reference only.",
            },
            "contextPolicy": {
                "emergenceScore": "Secondary context only: B6-Air plus positive realized-HR lag, exposure novelty, and age runway.",
                "durability": "Contact/whiff/chase/K/BB are confidence context only, not score inputs.",
                "consensusTodo": "Future validation should compare surfaced names against public consensus/projection/prospect context to ask whether Storm Watch found useful names before the broader market did.",
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


def write_review_outputs(snapshot: dict[str, Any], review_dir: Path) -> tuple[Path, Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    stem = f"storm_watch_shadow_{snapshot['snapshotDate']}"
    json_path = review_dir / f"{stem}.json"
    csv_path = review_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame([compact_entry(row) for row in snapshot["players"]]).to_csv(csv_path, index=False)
    return csv_path, json_path


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


def print_summary(snapshot: dict[str, Any], paths: tuple[Path, Path, Path]) -> None:
    snapshot_path, csv_path, json_path = paths
    print(f"Storm Watch shadow snapshot: {snapshot['snapshotDate']}")
    print(f"Rows: {snapshot['coverage']['players']}")
    print("Bucket counts:")
    for bucket, count in sorted(snapshot["coverage"]["bucketCounts"].items()):
        print(f"- {bucket}: {count}")
    print("Missing field counts:")
    for field, count in snapshot["coverage"]["missingFieldCounts"].items():
        if count:
            print(f"- {field}: {count}")
    print_watchlist("Top 25 Prime Emergence", snapshot["watchlists"]["primeEmergence"])
    print_watchlist("Top 25 Early Emergence", snapshot["watchlists"]["earlyEmergence"])
    print_watchlist("Top 25 Early Emergence BBE >= 250", snapshot["watchlists"]["earlyEmergenceBbe250"])
    print_watchlist("Top 25 All Low-History <=25", snapshot["watchlists"]["allLowHistoryAgeLe25"])
    print_watchlist("26-27 Late-Arrival Reference", snapshot["watchlists"]["lateArrivalReference26To27"])
    print(f"\nSnapshot path: {snapshot_path}")
    print(f"Review CSV: {csv_path}")
    print(f"Review JSON: {json_path}")


def main() -> None:
    args = parse_args()
    payload = load_json(args.input)
    snapshot_date = parse_snapshot_date(payload, args.date)
    snapshot = build_snapshot(payload, args, snapshot_date)
    snapshot_path = write_snapshot(snapshot, args.output_dir, args.replace_existing)
    csv_path, json_path = write_review_outputs(snapshot, args.review_dir)
    print_summary(snapshot, (snapshot_path, csv_path, json_path))


if __name__ == "__main__":
    main()
