#!/usr/bin/env python3
"""Write retained internal Storm Watch Prime Emergence snapshots.

Storm Watch Prime Emergence is an internal/on-deck shadow workflow, not a
public formula or frontend output. It watches the validated highest-confidence
cohort: age-24/25 hitters with no-prior or low-history MLB track records whose
B6 Storm Watch score is flashing.

B6-Air is kept as the score:
- 60% Storm Fuel A2
- 20% Barrel/PA
- 20% HR-Window Thunder/PA

Storm Fuel A2:
- 50% stabilized xHR/BBE
- 25% stabilized HR-Window Thunder Rate
- 25% Air EV90

Pulled-airborne/PA is recorded as a confirmation/tiebreaker, not the primary
score. Snapshots are dated and retained under data/shadow/ so live evidence can
accumulate without touching public data or production formulas.

Durability/contact fields are future confidence/context only. They should not
modify B6-Air unless new diagnostics overturn the June 2026 contact-survival
finding.
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
DEFAULT_STATCAST_CACHE = Path("data/raw/statcast-pitches.csv.gz")
DEFAULT_PEOPLE_CACHE = Path("data/cache/longball-threat-backtest/player-people-cache.json")
DEFAULT_OUTPUT_DIR = Path("data/shadow/storm_watch_prime_emergence")
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
FUTURE_POWER_CONTEXT_FIELDS = [
    "stormWatchB6Air",
    "stormFuelA2",
    "anyAirEv90",
    "rawXhrPerBbe",
    "hrWindowThunderRate",
    "barrelPerPa",
    "hrWindowThunderPerPa",
]
FUTURE_BUCKET_CONTEXT_FIELDS = [
    "age",
    "priorStatus",
    "previousSeasonPa",
    "bucketLabel",
    "bucketConfidence",
]
FUTURE_DURABILITY_CONTEXT_FIELDS = [
    "contactPct",
    "whiffPct",
    "zoneContactPct",
    "chasePct",
    "kPct",
    "bbPct",
    "durabilityTag",
    "contactRiskTag",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an internal Storm Watch Prime Emergence shadow snapshot.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Current production hitter JSON.")
    parser.add_argument("--statcast-cache", type=Path, default=DEFAULT_STATCAST_CACHE, help="Current Statcast pitch cache used to compute Air EV90.")
    parser.add_argument("--people-cache", type=Path, default=DEFAULT_PEOPLE_CACHE, help="Cached MLB people data with birth dates.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Retained shadow snapshot directory.")
    parser.add_argument("--date", help="Snapshot date YYYY-MM-DD. Defaults to input generatedAt date.")
    parser.add_argument("--limit", type=int, default=30, help="Watchlist size.")
    parser.add_argument("--replace-existing", action="store_true", help="Replace an existing same-date snapshot.")
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


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def ev90_lookup(statcast_cache: Path) -> dict[int, dict[str, float]]:
    if not statcast_cache.exists():
        return {}
    pitches = pd.read_csv(statcast_cache, usecols=["batter", "launch_speed", "launch_angle"])
    pitches["batter"] = pd.to_numeric(pitches["batter"], errors="coerce")
    pitches["launch_speed"] = pd.to_numeric(pitches["launch_speed"], errors="coerce")
    pitches["launch_angle"] = pd.to_numeric(pitches["launch_angle"], errors="coerce")
    bbe = pitches.dropna(subset=["batter", "launch_speed"])
    if bbe.empty:
        return {}
    all_ev90 = bbe.groupby("batter")["launch_speed"].quantile(0.90)
    air = bbe[bbe["launch_angle"].between(15, 45, inclusive="both")]
    air_ev90 = air.groupby("batter")["launch_speed"].quantile(0.90) if not air.empty else pd.Series(dtype="float64")
    air_bbe = air.groupby("batter").size() if not air.empty else pd.Series(dtype="float64")

    lookup: dict[int, dict[str, float]] = {}
    for batter, value in all_ev90.items():
        if pd.notna(value):
            lookup.setdefault(int(batter), {})["ev90"] = float(value)
    for batter, value in air_ev90.items():
        if pd.notna(value):
            lookup.setdefault(int(batter), {})["anyAirEv90"] = float(value)
    for batter, value in air_bbe.items():
        lookup.setdefault(int(batter), {})["airBbe"] = float(value)
    return lookup


def prior_context(season: int) -> tuple[dict[int, dict[str, float]], dict[str, float]]:
    output: dict[int, dict[str, float]] = {}
    all_previous_xhr = []
    all_previous_thunder = []
    for offset in [1, 2, 3]:
        for row in load_public_lbi_rows(Path(f"public/data/longball-index-{season - offset}.json")):
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
                    "previousXhrPerBbe": float("nan"),
                    "previousThunderRate": float("nan"),
                },
            )
            context["priorSeasonCount"] += 1
            context["priorPaTotal"] += pa
            if offset == 1:
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


def player_record(row: dict[str, Any], age_lookup: dict[int, str], ev90_by_batter: dict[int, dict[str, float]], snapshot_day: date, prior: dict[int, dict[str, float]], league_prior: dict[str, float]) -> dict[str, Any] | None:
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
            "previousXhrPerBbe": float("nan"),
            "previousThunderRate": float("nan"),
        },
    )
    previous_xhr = prior_row["previousXhrPerBbe"]
    previous_thunder = prior_row["previousThunderRate"]
    has_previous_xhr = not math.isnan(previous_xhr)
    has_previous_thunder = not math.isnan(previous_thunder)
    prior_seasons = int(prior_row["priorSeasonCount"])
    prior_pa = float(prior_row["priorPaTotal"])
    no_prior = prior_seasons == 0
    missing_previous_baseline = not (has_previous_xhr or has_previous_thunder)
    low_history = prior_seasons < 2 or prior_pa < 300

    current_xhr_per_bbe = number(row.get("xhrPerBbe"))
    current_thunder_rate = number(row.get("hrWindowThunderRate"))
    ev90_context = ev90_by_batter.get(batter_id, {})
    ev90 = ev90_context.get("ev90")
    any_air_ev90 = ev90_context.get("anyAirEv90")
    air_bbe = ev90_context.get("airBbe", 0.0)
    barrel_per_pa = number(row.get("barrelRate")) * bbe / pa
    thunder_per_pa = number(row.get("hrWindowThunderBbe")) / pa
    pulled_air_per_pa = number(row.get("pulledAirBbe")) / pa

    mx = 150 if has_previous_xhr else 317
    mt = 100 if has_previous_thunder else 317
    wx = bbe / (bbe + mx)
    wt = bbe / (bbe + mt)
    prior_xhr = previous_xhr if has_previous_xhr else league_prior["previousXhrPerBbe"]
    prior_thunder = previous_thunder if has_previous_thunder else league_prior["previousThunderRate"]

    age = age_at(age_lookup.get(batter_id), snapshot_day)
    return {
        "playerId": batter_id,
        "player": str(row.get("player") or ""),
        "team": str(row.get("team") or ""),
        "age": age,
        "pa": int(pa),
        "bbe": int(bbe),
        "hr": int(number(row.get("hr"))),
        "longballIndex": number(row.get("longballIndex")),
        "rawXhrPerBbe": current_xhr_per_bbe,
        "hrWindowThunderRate": current_thunder_rate,
        "hrWindowThunderBbe": int(number(row.get("hrWindowThunderBbe"))),
        "barrelRate": number(row.get("barrelRate")),
        "barrelPerPa": barrel_per_pa,
        "hrWindowThunderPerPa": thunder_per_pa,
        "pulledAirbornePerPa": pulled_air_per_pa,
        "ev90": ev90,
        "anyAirEv90": any_air_ev90,
        "airBbe": int(air_bbe),
        "stabilizedXhrPerBbe": wx * current_xhr_per_bbe + (1 - wx) * prior_xhr,
        "stabilizedHrWindowThunderRate": wt * current_thunder_rate + (1 - wt) * prior_thunder,
        "priorSeasonCount": prior_seasons,
        "priorPaTotal": round(prior_pa, 1),
        "noPrior": no_prior,
        "missingPreviousSeasonBaseline": missing_previous_baseline,
        "lowHistory": low_history,
        "priorStatus": "no-prior" if no_prior else ("low-history" if low_history else "established"),
        "primeEmergenceEligible": bool(age is not None and 24 <= age < 26 and (no_prior or low_history)),
    }


def add_scores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(records)
    if frame.empty:
        return []
    league_any_air_ev90 = frame["anyAirEv90"].dropna().mean()
    if pd.isna(league_any_air_ev90):
        league_any_air_ev90 = frame["ev90"].dropna().mean()
    frame["anyAirEv90ForScoring"] = frame["anyAirEv90"].fillna(league_any_air_ev90)
    missing_previous_baseline = frame["missingPreviousSeasonBaseline"].fillna(False)
    air_bbe = frame["airBbe"].fillna(0)
    ev_weight = air_bbe / (air_bbe + 62)
    frame.loc[missing_previous_baseline, "anyAirEv90ForScoring"] = (
        ev_weight.loc[missing_previous_baseline] * frame.loc[missing_previous_baseline, "anyAirEv90ForScoring"]
        + (1 - ev_weight.loc[missing_previous_baseline]) * league_any_air_ev90
    )

    score_inputs = {
        "scoreStabilizedXhrPerBbe": "stabilizedXhrPerBbe",
        "scoreStabilizedThunderRate": "stabilizedHrWindowThunderRate",
        "scoreAnyAirEv90": "anyAirEv90ForScoring",
        "scoreBarrelPerPa": "barrelPerPa",
        "scoreThunderPerPa": "hrWindowThunderPerPa",
        "scorePulledAirbornePerPa": "pulledAirbornePerPa",
    }
    for score_column, source_column in score_inputs.items():
        frame[score_column] = percentile_scores(frame[source_column])

    frame["stormFuelA1"] = weighted_score(
        frame,
        {
            "scoreStabilizedXhrPerBbe": 0.50,
            "scoreStabilizedThunderRate": 0.25,
            "scoreAnyAirEv90": 0.25,
        },
    )
    frame["stormWatchB6"] = weighted_score(
        frame,
        {
            "stormFuelA1": 0.60,
            "scoreBarrelPerPa": 0.20,
            "scoreThunderPerPa": 0.20,
        },
    )
    # Keep old field names for existing snapshots, but expose the frozen current
    # naming so future shadow output can say Storm Fuel A2 / B6-Air plainly.
    frame["stormFuelA2"] = frame["stormFuelA1"]
    frame["stormWatchB6Air"] = frame["stormWatchB6"]
    frame["pulledAirborneConfirmation"] = frame["scorePulledAirbornePerPa"]
    frame["b6PlusPulledAirborneConfirmation"] = weighted_score(
        frame,
        {
            "stormWatchB6": 0.90,
            "scorePulledAirbornePerPa": 0.10,
        },
    )
    frame["stormWatchRank"] = frame["stormWatchB6"].rank(method="first", ascending=False).astype(int)
    frame["primeEmergenceRank"] = frame.loc[frame["primeEmergenceEligible"], "stormWatchB6"].rank(method="first", ascending=False)
    frame["primeEmergenceRank"] = frame["primeEmergenceRank"].where(frame["primeEmergenceRank"].notna(), None)

    rounded = []
    for row in frame.to_dict(orient="records"):
        for key in [
            "age",
            "rawXhrPerBbe",
            "hrWindowThunderRate",
            "barrelRate",
            "barrelPerPa",
            "hrWindowThunderPerPa",
            "pulledAirbornePerPa",
            "ev90",
            "anyAirEv90",
            "stabilizedXhrPerBbe",
            "stabilizedHrWindowThunderRate",
            "stormFuelA1",
            "stormFuelA2",
            "stormWatchB6",
            "stormWatchB6Air",
            "pulledAirborneConfirmation",
            "b6PlusPulledAirborneConfirmation",
        ]:
            if key in row and row[key] is not None and not pd.isna(row[key]):
                row[key] = round(float(row[key]), 5 if "Rate" in key or "Per" in key or key.endswith("perPa") else 1)
            elif key in row:
                row[key] = None
        if row.get("primeEmergenceRank") is not None and not pd.isna(row.get("primeEmergenceRank")):
            row["primeEmergenceRank"] = int(row["primeEmergenceRank"])
        else:
            row["primeEmergenceRank"] = None
        rounded.append(row)
    return rounded


def classify_note(row: dict[str, Any]) -> str:
    notes = []
    if row["noPrior"]:
        notes.append("no-prior hitter")
    elif row["lowHistory"]:
        notes.append("low-history hitter")
    if row.get("bbe", 0) < 120:
        notes.append("sample caution")
    if row.get("stormWatchB6", 0) >= 150:
        notes.append("power flashing")
    return "; ".join(notes) if notes else "context only"


def watch_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "playerId": row["playerId"],
        "player": row["player"],
        "team": row["team"],
        "age": row["age"],
        "pa": row["pa"],
        "bbe": row["bbe"],
        "hr": row["hr"],
        "priorStatus": row["priorStatus"],
        "priorSeasonCount": row["priorSeasonCount"],
        "priorPaTotal": row["priorPaTotal"],
        "missingPreviousSeasonBaseline": row["missingPreviousSeasonBaseline"],
        "stormWatchRank": row["stormWatchRank"],
        "primeEmergenceRank": row["primeEmergenceRank"],
        "stormWatchB6": row["stormWatchB6"],
        "stormWatchB6Air": row["stormWatchB6Air"],
        "stormFuelA1": row["stormFuelA1"],
        "stormFuelA2": row["stormFuelA2"],
        "pulledAirborneConfirmation": row["pulledAirborneConfirmation"],
        "b6PlusPulledAirborneConfirmation": row["b6PlusPulledAirborneConfirmation"],
        "rawXhrPerBbe": row["rawXhrPerBbe"],
        "stabilizedXhrPerBbe": row["stabilizedXhrPerBbe"],
        "hrWindowThunderRate": row["hrWindowThunderRate"],
        "stabilizedHrWindowThunderRate": row["stabilizedHrWindowThunderRate"],
        "ev90": row["ev90"],
        "anyAirEv90": row["anyAirEv90"],
        "airBbe": row["airBbe"],
        "barrelPerPa": row["barrelPerPa"],
        "hrWindowThunderPerPa": row["hrWindowThunderPerPa"],
        "pulledAirbornePerPa": row["pulledAirbornePerPa"],
        "note": classify_note(row),
    }


def build_snapshot(payload: dict[str, Any], args: argparse.Namespace, snapshot_date: str) -> dict[str, Any]:
    season = int(payload.get("season") or 2026)
    snapshot_day = parse_date(snapshot_date)
    age_lookup = load_people_birth_dates(args.people_cache)
    ev90_by_batter = ev90_lookup(args.statcast_cache)
    prior, league_prior = prior_context(season)
    records = [
        player_record(row, age_lookup, ev90_by_batter, snapshot_day, prior, league_prior)
        for row in payload.get("players", [])
        if isinstance(row, dict)
    ]
    players = add_scores([record for record in records if record is not None])
    prime = [row for row in players if row["primeEmergenceEligible"]]
    prime_top = sorted(prime, key=lambda row: (-number(row.get("stormWatchB6")), str(row.get("player"))))[: args.limit]
    confirmation_top = sorted(prime, key=lambda row: (-number(row.get("b6PlusPulledAirborneConfirmation")), str(row.get("player"))))[: args.limit]
    all_b6_top = sorted(players, key=lambda row: (-number(row.get("stormWatchB6")), str(row.get("player"))))[: args.limit]

    return {
        "snapshotDate": snapshot_date,
        "generatedAt": payload.get("generatedAt"),
        "season": season,
        "sourcePath": str(args.input),
        "statcastCachePath": str(args.statcast_cache),
        "peopleCachePath": str(args.people_cache),
        "model": {
            "name": "Storm Watch Prime Emergence shadow",
            "status": "internal-shadow",
            "identity": "Storm Watch is an internal Young Power Radar for low-history hitters whose MLB power signal is forming before the track record exists.",
            "naming": {
                "stormWatch": "branded feature name",
                "youngPowerRadar": "plain-English descriptor",
                "primeEmergence": "validated 24-to-25 High Trust bucket",
                "earlyEmergence": "21-to-23 Candidate bucket",
                "durability": "confidence/context layer, not score",
            },
            "cohortRule": "24 <= checkpoint age < 26 AND (no prior season baseline OR <2 prior MLB seasons OR <300 prior PA over the prior three seasons).",
            "score": {
                "primary": "B6-Air Storm Watch",
                "definition": "60% Storm Fuel A2 + 20% Barrel/PA + 20% HR-Window Thunder/PA.",
                "stormFuelA2": "50% stabilized xHR/BBE + 25% stabilized HR-Window Thunder Rate + 25% Air EV90.",
                "stabilization": {
                    "realPrior": "xHR/BBE M=150, HR-Window Thunder Rate M=100, using prior-season public LBI values.",
                    "noPrior": "xHR/Thunder shrink toward league average at M=317; Air EV90 shrinks toward current qualified-pool average at M=62 using air-BBE denominator.",
                    "ev90Limitation": "Prior Air EV90 is not present in public season JSON, so real-prior players use current Air EV90; no-prior players get M=62 league shrinkage.",
                    "airEv90Definition": "Air EV90 is 90th-percentile exit velocity on lifted damage-zone contact, currently launch angle 15-45 degrees.",
                },
                "confirmation": "Pulled-airborne/PA is retained as a confirmation/tiebreaker, not the primary score.",
            },
            "durabilityContext": {
                "status": "future snapshot context only",
                "finding": "Contact/whiff risk explains some Early Emergence false positives, but durability overlays did not rescue weak-year volatility and should not modify B6-Air.",
                "futureFields": FUTURE_DURABILITY_CONTEXT_FIELDS,
            },
            "futureSnapshotTodo": {
                "powerFields": FUTURE_POWER_CONTEXT_FIELDS,
                "bucketFields": FUTURE_BUCKET_CONTEXT_FIELDS,
                "durabilityFields": FUTURE_DURABILITY_CONTEXT_FIELDS,
            },
        },
        "qualifiedBy": payload.get("qualifiedBy", {}),
        "coverage": {
            "players": len(players),
            "primeEmergencePlayers": len(prime),
            "agePresent": sum(1 for row in players if row.get("age") is not None),
            "ev90Present": sum(1 for row in players if row.get("ev90") is not None),
            "anyAirEv90Present": sum(1 for row in players if row.get("anyAirEv90") is not None),
        },
        "watchlists": {
            "primeEmergenceB6": [watch_entry(row) for row in prime_top],
            "primeEmergenceB6PlusPulledAirborneConfirmation": [watch_entry(row) for row in confirmation_top],
            "allPoolB6Reference": [watch_entry(row) for row in all_b6_top],
        },
        "players": players,
    }


def write_snapshot(snapshot: dict[str, Any], output_dir: Path, replace_existing: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"snapshot_{snapshot['snapshotDate']}.json"
    if path.exists() and not replace_existing:
        raise SystemExit(f"Refusing to overwrite existing snapshot: {path}")
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return path


def print_watchlist(snapshot: dict[str, Any]) -> None:
    print(f"Wrote Storm Watch Prime Emergence snapshot for {snapshot['snapshotDate']}")
    print(f"Players scored: {snapshot['coverage']['players']}")
    print(f"Prime Emergence cohort: {snapshot['coverage']['primeEmergencePlayers']}")
    print(f"Age coverage: {snapshot['coverage']['agePresent']}/{snapshot['coverage']['players']}")
    print(f"Air EV90 coverage: {snapshot['coverage']['anyAirEv90Present']}/{snapshot['coverage']['players']}")
    print("\nPrime Emergence B6-Air:")
    for row in snapshot["watchlists"]["primeEmergenceB6"]:
        age = "NA" if row["age"] is None else f"{row['age']:.1f}"
        print(
            f"{row['primeEmergenceRank']:2}. {row['player']:<24} {row['team']:<3} | "
            f"age {age} | {row['priorStatus']:<11} | B6-Air {row['stormWatchB6Air']:6.1f} | "
            f"PA {row['pa']:3} BBE {row['bbe']:3} HR {row['hr']:2} | "
            f"xHR/BBE {row['rawXhrPerBbe'] * 100:5.2f}% | Thunder/PA {row['hrWindowThunderPerPa'] * 100:5.2f}% | "
            f"AirEV90 {row['anyAirEv90'] if row['anyAirEv90'] is not None else 'NA'} | {row['note']}"
        )


def main() -> None:
    args = parse_args()
    payload = load_json(args.input)
    snapshot_date = parse_snapshot_date(payload, args.date)
    snapshot = build_snapshot(payload, args, snapshot_date)
    path = write_snapshot(snapshot, args.output_dir, args.replace_existing)
    print_watchlist(snapshot)
    print(f"\nSnapshot path: {path}")


if __name__ == "__main__":
    main()
