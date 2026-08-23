#!/usr/bin/env python3
"""Build the season-to-date defense-subsidy team-context read.

``defenseSubsidy`` is actual minus expected wOBA on tracked, non-home-run
terminal balls in play.  Negative values mean results were better than the
contact expectation.  The read deliberately combines defense and batted-ball
luck: the gloves and the bounces.

This module is not a pitcher-skill model, is never plus-scaled, and is not a
projection input.  Pitcher rows are a staff-context detail; team aggregates
always include every eligible staff BIP, including sub-qualifier pitchers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from data_integrity import scope_to_regular_season
from generate_pitch_cache import PITCH_CACHE_PATH, read_pitch_cache


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0"
INTERNAL_ID = "defenseSubsidy"
MODEL_PATH = ROOT / "data/models/defense-subsidy-v1.0-2021-2025.joblib"
MODEL_METADATA_PATH = ROOT / "data/models/defense-subsidy-v1.0-2021-2025.json"
HOT_DOG_LATEST_PATH = ROOT / "public/data/hot-dog-stand-latest.json"
DEFAULT_MIN_BIP = 100
LEAGUE_MEAN_TOLERANCE = 0.005
IDENTITY_TOLERANCE = 1e-12
TRAINING_SEASONS = (2021, 2022, 2023, 2024, 2025)
FEATURE_COLUMNS = (
    "launch_speed",
    "launch_angle",
    "bb_ground",
    "bb_line",
    "bb_fly",
    "bb_popup",
)

PITCH_KEY = ["game_pk", "at_bat_number", "pitch_number", "pitcher"]
PA_KEY = ["game_pk", "at_bat_number"]
TRAINING_USECOLS = {
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "events",
    "type",
    "description",
    "launch_speed",
    "launch_angle",
    "bb_type",
    "woba_value",
}
NUMERIC_TRAINING_COLUMNS = {
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "launch_speed",
    "launch_angle",
    "woba_value",
}

EXPECTED_DIAGNOSTIC_CUBS = {
    "team": "CHC",
    "asOfDate": "2026-08-20",
    "defenseSubsidy": -0.0334,
    "leagueRank": 1,
    "pitchers": {
        "Trent Thornton": -0.0675,
        "Javier Assad": -0.0675,
        "Hoby Milner": -0.0597,
        "David Peterson": -0.0459,
        "Ben Brown": -0.0446,
        "Matthew Boyd": -0.0432,
    },
}


@dataclass
class DefenseSubsidyModel:
    estimator: HistGradientBoostingRegressor
    event_weights: dict[str, float]
    training_seasons: tuple[int, ...]
    training_bip: int
    sklearn_version: str


@dataclass
class DerivationResult:
    season: int
    as_of_date: str
    min_bip: int
    all_pitchers: pd.DataFrame
    qualified_pitchers: pd.DataFrame
    teams: pd.DataFrame
    league_bip: int
    league_mean_subsidy: float
    cooked_missing: pd.DataFrame
    identity_checks: dict[str, Any]
    source_metadata: dict[str, Any]


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected date format YYYY-MM-DD") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--as-of", type=parse_iso_date)
    parser.add_argument("--pitch-cache", type=Path, default=ROOT / PITCH_CACHE_PATH)
    parser.add_argument("--hot-dog-json", type=Path, default=HOT_DOG_LATEST_PATH)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--min-bip", type=int)
    parser.add_argument("--distribution-only", action="store_true")
    parser.add_argument("--verify-diagnostic", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional private/public JSON output path.")
    parser.add_argument("--train-model", action="store_true")
    parser.add_argument(
        "--training-source-root",
        type=Path,
        default=ROOT,
        help="Checkout containing historical longball-threat-backtest pitch caches.",
    )
    parser.add_argument("--model-output", type=Path, default=MODEL_PATH)
    parser.add_argument("--model-metadata-output", type=Path, default=MODEL_METADATA_PATH)
    return parser.parse_args()


def pitcher_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def is_fair_terminal(frame: pd.DataFrame) -> pd.Series:
    pitch_type = frame.get("type", pd.Series("", index=frame.index)).astype("string").str.upper()
    description = frame.get("description", pd.Series("", index=frame.index)).astype("string")
    return pitch_type.eq("X") | description.str.startswith("hit_into_play", na=False)


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    bb_type = frame["bb_type"].astype("string").str.lower()
    return pd.DataFrame(
        {
            "launch_speed": pd.to_numeric(frame["launch_speed"], errors="coerce"),
            "launch_angle": pd.to_numeric(frame["launch_angle"], errors="coerce"),
            "bb_ground": bb_type.eq("ground_ball").fillna(False).astype(float),
            "bb_line": bb_type.eq("line_drive").fillna(False).astype(float),
            "bb_fly": bb_type.eq("fly_ball").fillna(False).astype(float),
            "bb_popup": bb_type.eq("popup").fillna(False).astype(float),
        },
        index=frame.index,
    )


def new_estimator() -> HistGradientBoostingRegressor:
    """Return the exact frozen Basic expectation form validated in Part 3."""
    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=160,
        max_leaf_nodes=31,
        min_samples_leaf=200,
        l2_regularization=10.0,
        random_state=17,
    )


def historical_source_paths(source_root: Path, season: int) -> list[Path]:
    return [
        source_root / f"data/cache/longball-threat-backtest/statcast-pitches-{season}-{half}.csv"
        for half in ("first", "second")
    ]


def load_historical_terminal_bbe(source_root: Path, season: int) -> pd.DataFrame:
    """Load one date-guarded terminal fair BBE per PA for model training."""
    frames: list[pd.DataFrame] = []
    for path in historical_source_paths(source_root, season):
        if not path.exists():
            raise FileNotFoundError(f"Missing historical defense-subsidy source: {path}")
        header = pd.read_csv(path, nrows=0).columns
        missing = TRAINING_USECOLS.difference(header)
        if missing:
            raise RuntimeError(f"Historical source {path} lacks: {', '.join(sorted(missing))}")
        frame = pd.read_csv(path, usecols=lambda column: column in TRAINING_USECOLS, low_memory=False)
        frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce")
        # Required on every input because the canonical production cache omits game_type.
        frame = scope_to_regular_season(frame, season)
        frames.append(frame)
    pitches = pd.concat(frames, ignore_index=True)
    for column in NUMERIC_TRAINING_COLUMNS:
        pitches[column] = pd.to_numeric(pitches[column], errors="coerce")
    pitches = pitches.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])
    pitches = pitches.drop_duplicates(PITCH_KEY, keep="last")
    event_text = pitches["events"].astype("string").str.strip()
    terminal = pitches[event_text.notna() & event_text.ne("")].drop_duplicates(PA_KEY, keep="last")
    terminal = terminal[is_fair_terminal(terminal)].copy()
    terminal["event_norm"] = terminal["events"].astype("string").str.lower().str.strip()
    terminal["pitcher_id"] = pd.to_numeric(terminal["pitcher"], errors="coerce").astype("Int64")
    # Preserve the validated diagnostic's deterministic per-pitcher row order;
    # histogram accumulation can move at the fourth decimal under a different
    # input order even with identical observations and a fixed random_state.
    terminal = terminal.sort_values(
        ["pitcher_id", "game_date", "game_pk", "at_bat_number", "pitch_number"]
    )
    terminal["season"] = season
    return terminal


def train_model(source_root: Path, seasons: Iterable[int]) -> DefenseSubsidyModel:
    season_frames = [load_historical_terminal_bbe(source_root, season) for season in seasons]
    history = pd.concat(season_frames, ignore_index=True)
    weighted = history.dropna(subset=["woba_value"])
    event_weights = {
        str(event): float(weight)
        for event, weight in weighted.groupby("event_norm", observed=True)["woba_value"].median().items()
    }
    training = history[~history["event_norm"].eq("home_run")].dropna(
        subset=["launch_speed", "launch_angle", "woba_value"]
    )
    estimator = new_estimator()
    estimator.fit(
        feature_frame(training),
        pd.to_numeric(training["woba_value"], errors="coerce").clip(0, 2),
    )
    return DefenseSubsidyModel(
        estimator=estimator,
        event_weights=event_weights,
        training_seasons=tuple(int(season) for season in seasons),
        training_bip=int(len(training)),
        sklearn_version=sklearn.__version__,
    )


def write_model(model_path: Path, metadata_path: Path, model: DefenseSubsidyModel) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path, compress=3)
    metadata = {
        "version": VERSION,
        "internalIdentifier": INTERNAL_ID,
        "eventUniverse": "tracked non-home-run terminal fair BIP",
        "expectation": "Historical-league HGB regression of actual wOBA from EV, LA, and batted-ball type",
        "trainingSeasons": list(model.training_seasons),
        "trainingBip": model.training_bip,
        "featureColumns": list(FEATURE_COLUMNS),
        "eventWeights": model.event_weights,
        "scikitLearnVersion": model.sklearn_version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "copyGuardrail": "The gloves and the bounces: defense and batted-ball luck together, not separated.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_model(path: Path) -> DefenseSubsidyModel:
    if not path.exists():
        raise FileNotFoundError(f"Missing committed defense-subsidy model: {path}")
    model = joblib.load(path)
    if not isinstance(model, DefenseSubsidyModel):
        raise TypeError(f"Unexpected defense-subsidy model payload in {path}")
    if tuple(model.estimator.feature_names_in_) != FEATURE_COLUMNS:
        raise RuntimeError("Defense-subsidy model feature contract changed")
    if model.sklearn_version != sklearn.__version__:
        raise RuntimeError(
            f"Defense-subsidy model requires scikit-learn {model.sklearn_version}; running {sklearn.__version__}"
        )
    return model


def prepare_current_bip(pitches: pd.DataFrame, season: int, as_of: date | None) -> pd.DataFrame:
    """Return the exact tracked, non-HR terminal fair BIP universe validated in Part 3."""
    scoped = scope_to_regular_season(pitches, season)
    scoped["game_date"] = pd.to_datetime(scoped["game_date"], errors="coerce")
    if as_of is not None:
        scoped = scoped[scoped["game_date"].dt.date.le(as_of)].copy()
    for column in ["game_pk", "at_bat_number", "pitch_number", "pitcher", "launch_speed", "launch_angle"]:
        scoped[column] = pd.to_numeric(scoped[column], errors="coerce")
    scoped = scoped.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])
    scoped = scoped.drop_duplicates(PITCH_KEY, keep="last")
    event_text = scoped["events"].astype("string").str.strip()
    terminal = scoped[event_text.notna() & event_text.ne("")].drop_duplicates(PA_KEY, keep="last")
    bbe = terminal[is_fair_terminal(terminal)].copy()
    bbe["event_norm"] = bbe["events"].astype("string").str.lower().str.strip()
    bbe = bbe[~bbe["event_norm"].eq("home_run")].copy()
    bbe = bbe.dropna(subset=["launch_speed", "launch_angle", "pitcher"])
    bbe["pitcher_id"] = pd.to_numeric(bbe["pitcher"], errors="coerce").astype("Int64")
    bbe["pitcher_name"] = bbe["player_name"].map(pitcher_display_name)
    side = bbe["inning_topbot"].astype("string").str.lower()
    bbe["team"] = pd.NA
    bbe.loc[side.eq("top"), "team"] = bbe.loc[side.eq("top"), "home_team"]
    bbe.loc[side.eq("bot"), "team"] = bbe.loc[side.eq("bot"), "away_team"]
    bbe = bbe.dropna(subset=["team", "pitcher_id"])
    return bbe.reset_index(drop=True)


def load_cooked_plus(path: Path, season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Hot Dog Stand payload for cookedPlus join: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("season", 0)) != season:
        raise RuntimeError(f"Hot Dog Stand payload season {payload.get('season')} does not match {season}")
    rows = []
    for pitcher in payload.get("pitchers", []):
        rows.append(
            {
                "pitcher_id": pitcher.get("pitcherId"),
                "cookedPlus": pitcher.get("cookedPlus", pitcher.get("gettingCookedIndex")),
            }
        )
    frame = pd.DataFrame(rows, columns=["pitcher_id", "cookedPlus"])
    frame["pitcher_id"] = pd.to_numeric(frame["pitcher_id"], errors="coerce").astype("Int64")
    frame["cookedPlus"] = pd.to_numeric(frame["cookedPlus"], errors="coerce")
    frame = frame.dropna(subset=["pitcher_id"]).drop_duplicates("pitcher_id", keep="last")
    metadata = {
        "path": str(path),
        "generatedAt": payload.get("generatedAt"),
        "season": payload.get("season"),
        "methodologyVersion": payload.get("methodologyVersion"),
    }
    return frame, metadata


def bip_distribution(bip: pd.DataFrame) -> dict[str, Any]:
    counts = bip.groupby("pitcher_id", observed=True).size()
    return {
        "pitchersWithAnyBip": int(len(counts)),
        "quantiles": {
            f"p{int(q * 100)}": float(counts.quantile(q))
            for q in (0.10, 0.25, 0.50, 0.75, 0.90)
        },
        "atLeast": {str(cut): int(counts.ge(cut).sum()) for cut in (25, 50, 75, 100, 125, 150, 200)},
    }


def print_bip_distribution(distribution: dict[str, Any]) -> None:
    print("2026 pitcher BIP-against distribution (pitchers with any tracked fieldable BIP)")
    print(f"Pitchers: {distribution['pitchersWithAnyBip']}")
    print("Quantiles: " + ", ".join(f"{key}={value:.0f}" for key, value in distribution["quantiles"].items()))
    print("Counts: " + ", ".join(f">={cut}: {count}" for cut, count in distribution["atLeast"].items()))


def score_bip(bip: pd.DataFrame, model: DefenseSubsidyModel) -> pd.DataFrame:
    scored = bip.copy()
    unknown_events = sorted(set(scored["event_norm"].dropna()) - set(model.event_weights))
    if unknown_events:
        raise RuntimeError(f"No actual-wOBA mapping for BIP events: {', '.join(unknown_events)}")
    scored["actual_woba"] = scored["event_norm"].map(model.event_weights)
    scored["expected_woba"] = np.clip(model.estimator.predict(feature_frame(scored)), 0, 2)
    scored[INTERNAL_ID] = scored["actual_woba"] - scored["expected_woba"]
    return scored


def _aggregate_pitchers(scored: pd.DataFrame) -> pd.DataFrame:
    return (
        scored.groupby(["team", "pitcher_id", "pitcher_name"], observed=True)
        .agg(
            bip=(INTERNAL_ID, "size"),
            actualWobaOnBip=("actual_woba", "mean"),
            expectedWobaOnBip=("expected_woba", "mean"),
            defenseSubsidy=(INTERNAL_ID, "mean"),
        )
        .reset_index()
    )


def _aggregate_teams(scored: pd.DataFrame) -> pd.DataFrame:
    teams = (
        scored.groupby("team", observed=True)
        .agg(
            staffBip=(INTERNAL_ID, "size"),
            actualWobaOnBip=("actual_woba", "mean"),
            expectedWobaOnBip=("expected_woba", "mean"),
            defenseSubsidy=(INTERNAL_ID, "mean"),
        )
        .reset_index()
        .sort_values(["defenseSubsidy", "team"])
    )
    teams["leagueRank"] = np.arange(1, len(teams) + 1)
    return teams


def run_identity_checks(
    scored: pd.DataFrame,
    all_pitchers: pd.DataFrame,
    teams: pd.DataFrame,
) -> dict[str, Any]:
    errors = []
    maximum_team_delta = 0.0
    for team_row in teams.itertuples(index=False):
        pitchers = all_pitchers[all_pitchers["team"].eq(team_row.team)]
        weighted = float(np.average(pitchers["defenseSubsidy"], weights=pitchers["bip"]))
        delta = abs(weighted - float(team_row.defenseSubsidy))
        maximum_team_delta = max(maximum_team_delta, delta)
        if delta > IDENTITY_TOLERANCE:
            errors.append(f"{team_row.team} weighted pitcher identity delta {delta:.3e}")
    league_mean = float(scored[INTERNAL_ID].mean())
    if abs(league_mean) > LEAGUE_MEAN_TOLERANCE:
        errors.append(
            f"League BIP-weighted mean {league_mean:+.6f} exceeds tolerance {LEAGUE_MEAN_TOLERANCE:.3f}"
        )
    if len(teams) != 30:
        errors.append(f"Expected 30 teams, found {len(teams)}")
    if int(teams["staffBip"].sum()) != len(scored):
        errors.append("Team BIP totals do not equal scored league BIP")
    checks = {
        "passed": not errors,
        "teamCount": int(len(teams)),
        "leagueBip": int(len(scored)),
        "leagueBipWeightedMeanDefenseSubsidy": league_mean,
        "leagueMeanTolerance": LEAGUE_MEAN_TOLERANCE,
        "maximumTeamWeightedIdentityDelta": maximum_team_delta,
        "teamIdentityTolerance": IDENTITY_TOLERANCE,
        "errors": errors,
    }
    if errors:
        raise RuntimeError("Defense-subsidy identity checks failed:\n- " + "\n- ".join(errors))
    return checks


def derive(
    pitches: pd.DataFrame,
    model: DefenseSubsidyModel,
    cooked_plus: pd.DataFrame,
    *,
    season: int,
    as_of: date | None,
    min_bip: int,
    source_metadata: dict[str, Any],
) -> DerivationResult:
    bip = prepare_current_bip(pitches, season, as_of)
    if bip.empty:
        raise RuntimeError("No eligible defense-subsidy BIP after regular-season scoping")
    scored = score_bip(bip, model)
    all_pitchers = _aggregate_pitchers(scored)
    qualified = all_pitchers[all_pitchers["bip"].ge(min_bip)].copy()
    qualified = qualified.merge(cooked_plus, on="pitcher_id", how="left")
    qualified = qualified.sort_values(["team", "defenseSubsidy", "pitcher_name"])
    teams = _aggregate_teams(scored)
    checks = run_identity_checks(scored, all_pitchers, teams)
    cooked_missing = qualified[qualified["cookedPlus"].isna()][
        ["team", "pitcher_id", "pitcher_name", "bip", "defenseSubsidy"]
    ].copy()
    effective_as_of = as_of or scored["game_date"].max().date()
    return DerivationResult(
        season=season,
        as_of_date=effective_as_of.isoformat(),
        min_bip=min_bip,
        all_pitchers=all_pitchers,
        qualified_pitchers=qualified,
        teams=teams,
        league_bip=int(len(scored)),
        league_mean_subsidy=float(scored[INTERNAL_ID].mean()),
        cooked_missing=cooked_missing,
        identity_checks=checks,
        source_metadata=source_metadata,
    )


def verify_diagnostic(result: DerivationResult) -> dict[str, Any]:
    expected = EXPECTED_DIAGNOSTIC_CUBS
    if result.season != 2026 or result.as_of_date != expected["asOfDate"] or result.min_bip != 100:
        raise RuntimeError("Diagnostic reproduction requires season 2026, --as-of 2026-08-20, and --min-bip 100")
    cubs = result.teams[result.teams["team"].eq(expected["team"])]
    if len(cubs) != 1:
        raise RuntimeError("Diagnostic reproduction could not resolve exactly one Cubs team row")
    cubs_row = cubs.iloc[0]
    checks = {
        "cubsDefenseSubsidy": float(cubs_row["defenseSubsidy"]),
        "cubsLeagueRank": int(cubs_row["leagueRank"]),
        "pitchers": {},
    }
    if round(float(cubs_row["defenseSubsidy"]), 4) != expected["defenseSubsidy"]:
        raise RuntimeError(
            f"Cubs subsidy mismatch: {float(cubs_row['defenseSubsidy']):+.6f} vs {expected['defenseSubsidy']:+.4f}"
        )
    if int(cubs_row["leagueRank"]) != expected["leagueRank"]:
        raise RuntimeError(f"Cubs rank mismatch: {int(cubs_row['leagueRank'])} vs 1")
    cubs_pitchers = result.qualified_pitchers[result.qualified_pitchers["team"].eq("CHC")].copy()
    ordered = cubs_pitchers.sort_values("defenseSubsidy")["pitcher_name"].head(6).tolist()
    expected_order = list(expected["pitchers"])
    if ordered != expected_order:
        raise RuntimeError(f"Cubs top subsidy names mismatch: {ordered} vs {expected_order}")
    for name, expected_value in expected["pitchers"].items():
        row = cubs_pitchers[cubs_pitchers["pitcher_name"].eq(name)]
        if len(row) != 1:
            raise RuntimeError(f"Missing diagnostic pitcher row: {name}")
        actual_value = float(row.iloc[0]["defenseSubsidy"])
        checks["pitchers"][name] = actual_value
        if round(actual_value, 4) != expected_value:
            raise RuntimeError(f"{name} mismatch: {actual_value:+.6f} vs {expected_value:+.4f}")
    checks["passed"] = True
    return checks


def result_payload(result: DerivationResult, diagnostic: dict[str, Any] | None = None) -> dict[str, Any]:
    team_rows = []
    for team in result.teams.itertuples(index=False):
        pitchers = result.qualified_pitchers[result.qualified_pitchers["team"].eq(team.team)]
        team_rows.append(
            {
                "team": str(team.team),
                "leagueRank": int(team.leagueRank),
                "staffBip": int(team.staffBip),
                "actualWobaOnBip": float(team.actualWobaOnBip),
                "expectedWobaOnBip": float(team.expectedWobaOnBip),
                "defenseSubsidy": float(team.defenseSubsidy),
                "pitchers": [
                    {
                        "pitcher": str(row.pitcher_name),
                        "mlbamId": int(row.pitcher_id),
                        "bip": int(row.bip),
                        "actualWobaOnBip": float(row.actualWobaOnBip),
                        "expectedWobaOnBip": float(row.expectedWobaOnBip),
                        "defenseSubsidy": float(row.defenseSubsidy),
                        "cookedPlus": None if pd.isna(row.cookedPlus) else float(row.cookedPlus),
                    }
                    for row in pitchers.itertuples(index=False)
                ],
            }
        )
    return {
        "version": VERSION,
        "internalIdentifier": INTERNAL_ID,
        "season": result.season,
        "asOfDate": result.as_of_date,
        "qualifier": {"minimumBip": result.min_bip},
        "league": {
            "bip": result.league_bip,
            "bipWeightedMeanDefenseSubsidy": result.league_mean_subsidy,
        },
        "teams": team_rows,
        "identityChecks": result.identity_checks,
        "source": result.source_metadata,
        "diagnosticReproduction": diagnostic,
    }


def print_result(result: DerivationResult, diagnostic: dict[str, Any] | None) -> None:
    print(f"Frozen pitcher-row qualifier: {result.min_bip} BIP")
    print(
        f"Identity checks PASS | teams {len(result.teams)} | league BIP {result.league_bip:,} | "
        f"league mean {result.league_mean_subsidy:+.6f} | max team identity delta "
        f"{result.identity_checks['maximumTeamWeightedIdentityDelta']:.3e}"
    )
    cubs = result.teams[result.teams["team"].eq("CHC")].iloc[0]
    print(
        f"Cubs | BIP {int(cubs['staffBip']):,} | actual {float(cubs['actualWobaOnBip']):.4f} | "
        f"expected {float(cubs['expectedWobaOnBip']):.4f} | subsidy "
        f"{float(cubs['defenseSubsidy']):+.6f} | rank {int(cubs['leagueRank'])}/30"
    )
    cubs_pitchers = result.qualified_pitchers[result.qualified_pitchers["team"].eq("CHC")]
    print("Qualified Cubs pitchers (most helped first)")
    for row in cubs_pitchers.sort_values("defenseSubsidy").itertuples(index=False):
        cooked = "—" if pd.isna(row.cookedPlus) else f"{float(row.cookedPlus):.1f}"
        print(
            f"  {row.pitcher_name:22s} BIP {int(row.bip):3d} | subsidy "
            f"{float(row.defenseSubsidy):+.6f} | cookedPlus {cooked}"
        )
    print(f"Qualified pitcher rows missing cookedPlus: {len(result.cooked_missing)}")
    for row in result.cooked_missing.itertuples(index=False):
        print(f"  {row.team} | {row.pitcher_name} ({int(row.pitcher_id)}) | BIP {int(row.bip)} | display —")
    if diagnostic is not None:
        print("Diagnostic reproduction PASS: Cubs -.0334, rank 1/30, and six 100+ BIP names match")


def main() -> None:
    args = parse_args()
    if args.train_model:
        model = train_model(args.training_source_root, TRAINING_SEASONS)
        write_model(args.model_output, args.model_metadata_output, model)
        print(
            f"Wrote defense-subsidy model v{VERSION}: {model.training_bip:,} BIP, "
            f"seasons {model.training_seasons}, sklearn {model.sklearn_version}"
        )
        return

    model = load_model(args.model)
    pitches = read_pitch_cache(args.pitch_cache)
    current_bip = prepare_current_bip(pitches, args.season, args.as_of)
    distribution = bip_distribution(current_bip)
    print_bip_distribution(distribution)
    if args.distribution_only or args.min_bip is None:
        print("STOP: freeze --min-bip from this distribution before deriving pitcher rows.")
        return
    cooked_plus, cooked_metadata = load_cooked_plus(args.hot_dog_json, args.season)
    source_metadata = {
        "pitchCache": str(args.pitch_cache),
        "pitchCacheMaxDate": current_bip["game_date"].max().date().isoformat(),
        "model": str(args.model),
        "modelVersion": VERSION,
        "modelTrainingSeasons": list(model.training_seasons),
        "modelTrainingBip": model.training_bip,
        "expectation": "Historical-league HGB actual-wOBA expectation from EV, LA, and batted-ball type",
        "hotDogStand": cooked_metadata,
    }
    result = derive(
        pitches,
        model,
        cooked_plus,
        season=args.season,
        as_of=args.as_of,
        min_bip=args.min_bip,
        source_metadata=source_metadata,
    )
    diagnostic = verify_diagnostic(result) if args.verify_diagnostic else None
    print_result(result, diagnostic)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result_payload(result, diagnostic), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
