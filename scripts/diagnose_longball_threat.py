#!/usr/bin/env python3
"""Prototype Longball Threat, a predictive park-neutral HR/PA diagnostic.

This script does not write frontend data. It joins the current Longball Index
JSON to plate-appearance context, computes diagnostic Longball Threat scores,
and prints sanity checks for review before any product integration.
"""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

os.environ.setdefault("PYBASEBALL_CACHE", str(Path("data/cache/pybaseball").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/cache/matplotlib").resolve()))


DEFAULT_LBI_JSON = Path("public/data/hr-distance-latest.json")
DEFAULT_PITCH_CACHE = Path("data/raw/statcast-pitches.csv")
NORMAL_SCORE_SCALE = 50 / NormalDist().inv_cdf(0.90)
THREAT_WEIGHTS_V02 = {
    "adjustedXhrPerPa": 0.75,
    "barrelsPerPa": 0.25,
}
THREAT_WEIGHTS_V01 = {
    "adjustedXhrPerPa": 0.55,
    "barrelsPerPa": 0.25,
    "hardHitAirBbePerPa": 0.10,
    "avgDistanceOnBarrels": 0.10,
}
SANITY_PLAYERS = [
    "Aaron Judge",
    "Kyle Schwarber",
    "Yordan Alvarez",
    "Yordan Álvarez",
    "James Wood",
    "Munetaka Murakami",
    "Ke'Bryan Hayes",
    "Nico Hoerner",
    "Isaac Paredes",
    "Bobby Witt Jr.",
]


def normalize_name(value: Any) -> str:
    text = str(value or "").replace("’", "'").strip()
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_text.lower().replace(".", "").split())


def display_name(value: Any) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def percentile_scores(values: pd.Series) -> dict[int, dict[str, float]]:
    valid = values.dropna()
    if valid.empty:
        return {}

    ranks = valid.rank(method="average", pct=True)
    scores: dict[int, dict[str, float]] = {}
    for index, percentile in ranks.items():
        clipped = min(max(float(percentile), 0.01), 0.99)
        score = 100 + NORMAL_SCORE_SCALE * NormalDist().inv_cdf(clipped)
        scores[int(index)] = {
            "percentile": round(float(percentile), 4),
            "score": round(float(score), 1),
        }
    return scores


def weighted_score(
    row: pd.Series,
    weights: dict[str, float],
    score_maps: dict[str, dict[int, dict[str, float]]],
) -> tuple[float | None, dict[str, Any]]:
    active_weights = {
        key: weight
        for key, weight in weights.items()
        if row.get(key) is not None and not pd.isna(row.get(key)) and row.name in score_maps.get(key, {})
    }
    if not active_weights:
        return None, {}

    total = sum(active_weights.values())
    components: dict[str, Any] = {}
    score = 0.0
    for key, weight in active_weights.items():
        effective_weight = weight / total
        component = score_maps[key][row.name]
        score += component["score"] * effective_weight
        components[key] = {
            "value": round(float(row[key]), 5),
            "percentile": component["percentile"],
            "score": component["score"],
            "effectiveWeight": round(effective_weight, 3),
        }

    return round(max(score, 0), 1), components


def load_lbi_players(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = payload.get("players", [])
    if not isinstance(players, list) or not players:
        raise RuntimeError(f"No players found in {path}")

    frame = pd.DataFrame(players)
    frame["batter"] = to_numeric(frame["batter"]).astype("Int64")
    frame["lbiRank"] = frame["longballIndex"].rank(method="first", ascending=False).astype(int)
    for column in ["bbe", "hr", "xhr", "longballIndex", "avgDistanceOnBarrels"]:
        frame[column] = to_numeric(frame[column])
    frame["nameKey"] = frame["player"].map(normalize_name)
    return frame


def load_pitch_cache_stats(path: Path) -> pd.DataFrame:
    pitches = pd.read_csv(path)
    for column in ["batter", "game_pk", "at_bat_number", "pitch_number", "launch_speed", "launch_angle", "launch_speed_angle"]:
        if column in pitches.columns:
            pitches[column] = to_numeric(pitches[column])

    pitches = pitches[pitches["batter"].notna()].copy()
    terminal = pitches[pitches["events"].notna() & pitches["events"].astype(str).str.strip().ne("")]
    pa = (
        terminal.drop_duplicates(["game_pk", "at_bat_number", "batter"])
        .groupby("batter", as_index=False)
        .size()
        .rename(columns={"size": "estimatedPa"})
    )

    bbe = pitches[pitches["launch_speed"].notna() & pitches["launch_angle"].notna()].copy()
    bbe["isBarrel"] = bbe["launch_speed_angle"].eq(6)
    bbe["isHardHitAir"] = bbe["launch_speed"].ge(95) & bbe["launch_angle"].between(15, 40, inclusive="both")
    bbe_stats = (
        bbe.groupby("batter", as_index=False)
        .agg(
            statcastBbe=("batter", "size"),
            barrels=("isBarrel", "sum"),
            hardHitAirBbe=("isHardHitAir", "sum"),
        )
    )

    return pa.merge(bbe_stats, on="batter", how="outer").fillna(0)


def fetch_pybaseball_pa(season: int) -> tuple[pd.DataFrame, str]:
    try:
        from pybaseball import batting_stats

        stats = batting_stats(season, qual=0)
    except Exception as error:  # pragma: no cover - diagnostic path
        return pd.DataFrame(), f"pybaseball batting_stats failed: {error}"

    if "Name" not in stats.columns or "PA" not in stats.columns:
        return pd.DataFrame(), "pybaseball batting_stats did not expose Name and PA columns"

    frame = stats[["Name", "PA"]].copy()
    frame["player"] = frame["Name"].map(display_name)
    frame["nameKey"] = frame["player"].map(normalize_name)
    frame["pa"] = to_numeric(frame["PA"])
    frame = frame.dropna(subset=["pa"])
    return frame[["nameKey", "pa"]], f"pybaseball batting_stats matched by normalized player name ({len(frame)} PA rows)"


def attach_plate_appearances(players: pd.DataFrame, cache_stats: pd.DataFrame, season: int, source: str) -> tuple[pd.DataFrame, str]:
    merged = players.merge(cache_stats, on="batter", how="left")
    merged["estimatedPa"] = to_numeric(merged["estimatedPa"])
    merged["paSource"] = "statcast-pitch-cache"
    note = "PA estimated from terminal plate appearances in the canonical Statcast pitch cache."

    if source in {"auto", "pybaseball"}:
        pa_frame, pa_note = fetch_pybaseball_pa(season)
        if not pa_frame.empty:
            merged = merged.merge(pa_frame, on="nameKey", how="left")
            matched = int(merged["pa"].notna().sum())
            if source == "pybaseball" or matched >= max(50, len(merged) * 0.75):
                merged["pa"] = merged["pa"].fillna(merged["estimatedPa"])
                merged.loc[merged["pa"].notna(), "paSource"] = "pybaseball-batting-stats"
                note = f"{pa_note}; matched {matched}/{len(merged)} current LBI players. Missing names fall back to pitch-cache estimated PA."
            else:
                merged["pa"] = merged["estimatedPa"]
                note = f"{pa_note}, but only matched {matched}/{len(merged)} current LBI players; using pitch-cache estimated PA."
        elif source == "pybaseball":
            raise RuntimeError(pa_note)
        else:
            merged["pa"] = merged["estimatedPa"]
            note = f"{pa_note}; using pitch-cache estimated PA."
    else:
        merged["pa"] = merged["estimatedPa"]

    return merged, note


def calculate_threat(frame: pd.DataFrame, min_pa: int, min_bbe: int) -> pd.DataFrame:
    for column in ["statcastBbe", "barrels", "hardHitAirBbe", "pa"]:
        frame[column] = to_numeric(frame[column]).fillna(0)

    frame["adjustedXhrPerPa"] = frame["xhr"] / frame["pa"].where(frame["pa"].gt(0))
    frame["barrelsPerPa"] = frame["barrels"] / frame["pa"].where(frame["pa"].gt(0))
    frame["hardHitAirBbePerPa"] = frame["hardHitAirBbe"] / frame["pa"].where(frame["pa"].gt(0))
    frame["actualHrPerPa"] = frame["hr"] / frame["pa"].where(frame["pa"].gt(0))
    frame["qualifiedForThreat"] = frame["pa"].ge(min_pa) & frame["bbe"].ge(min_bbe)

    qualified = frame[frame["qualifiedForThreat"]].copy()
    score_maps = {
        key: percentile_scores(qualified[key])
        for key in sorted(set(THREAT_WEIGHTS_V02) | set(THREAT_WEIGHTS_V01))
    }

    threat_scores_v02 = []
    components_v02 = []
    threat_scores_v01 = []
    components_v01 = []
    for _, row in qualified.iterrows():
        score_v02, component_v02 = weighted_score(row, THREAT_WEIGHTS_V02, score_maps)
        score_v01, component_v01 = weighted_score(row, THREAT_WEIGHTS_V01, score_maps)
        threat_scores_v02.append(score_v02)
        components_v02.append(component_v02)
        threat_scores_v01.append(score_v01)
        components_v01.append(component_v01)

    qualified["longballThreat"] = threat_scores_v02
    qualified["threatComponents"] = components_v02
    qualified["longballThreatV01"] = threat_scores_v01
    qualified["threatComponentsV01"] = components_v01

    league_xhr_per_barrel = qualified["xhr"].sum() / qualified["barrels"].sum() if qualified["barrels"].sum() else 0
    league_xhr_per_hard_air = qualified["xhr"].sum() / qualified["hardHitAirBbe"].sum() if qualified["hardHitAirBbe"].sum() else 0
    league_xhr_per_pa = qualified["xhr"].sum() / qualified["pa"].sum() if qualified["pa"].sum() else 0

    distance_score_ratio_v01 = qualified["threatComponentsV01"].map(
        lambda item: (item.get("avgDistanceOnBarrels", {}).get("score", 100) / 100) if isinstance(item, dict) else 1
    )
    projected_rate_v02 = (
        0.75 * qualified["adjustedXhrPerPa"].fillna(0)
        + 0.25 * qualified["barrelsPerPa"].fillna(0) * league_xhr_per_barrel
    )
    projected_rate_v01 = (
        0.55 * qualified["adjustedXhrPerPa"].fillna(0)
        + 0.25 * qualified["barrelsPerPa"].fillna(0) * league_xhr_per_barrel
        + 0.10 * qualified["hardHitAirBbePerPa"].fillna(0) * league_xhr_per_hard_air
        + 0.10 * league_xhr_per_pa * distance_score_ratio_v01
    )
    qualified["projectedHrPer600"] = (projected_rate_v02 * 600).round(1)
    qualified["projectedHrPer600V01"] = (projected_rate_v01 * 600).round(1)
    qualified = qualified.sort_values(["longballThreat", "projectedHrPer600"], ascending=[False, False])
    qualified["threatRank"] = range(1, len(qualified) + 1)
    qualified["threatRankV01"] = qualified["longballThreatV01"].rank(method="first", ascending=False).astype(int)
    qualified["rankDeltaThreatMinusLbi"] = qualified["threatRank"] - qualified["lbiRank"]
    return qualified


def fmt_pct(value: Any, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:.{decimals}f}%"


def print_table(rows: pd.DataFrame, title: str, limit: int = 30) -> None:
    print(f"\n=== {title} ===")
    for _, row in rows.head(limit).iterrows():
        print(
            f"{int(row['threatRank']):2}. {row['player']} ({row['team']}) "
            f"LBT v0.2 {row['longballThreat']:.1f} | HR/600 {row['projectedHrPer600']:.1f} | "
            f"v0.1 {row['longballThreatV01']:.1f} | "
            f"xHR/PA {fmt_pct(row['adjustedXhrPerPa'], 2)} | Brl/PA {fmt_pct(row['barrelsPerPa'], 2)} | "
            f"LBI {row['longballIndex']:.1f}"
        )


def print_sanity(rows: pd.DataFrame) -> None:
    print("\n=== Sanity Player Outputs ===")
    by_name = {normalize_name(row["player"]): row for _, row in rows.iterrows()}
    seen: set[str] = set()
    for name in SANITY_PLAYERS:
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        row = by_name.get(key)
        if row is None:
            print(f"{name}: not qualified or not present")
            continue
        print(
            f"{row['player']} ({row['team']}) | PA {int(row['pa'])} | BBE {int(row['bbe'])} | HR {int(row['hr'])} | "
            f"LBT v0.2 {row['longballThreat']:.1f} | HR/600 {row['projectedHrPer600']:.1f} | "
            f"v0.1 {row['longballThreatV01']:.1f} | LBI {row['longballIndex']:.1f}"
        )
        print(
            f"  xHR/PA {fmt_pct(row['adjustedXhrPerPa'], 2)} | Brl/PA {fmt_pct(row['barrelsPerPa'], 2)} | "
            f"HH Air/PA {fmt_pct(row['hardHitAirBbePerPa'], 2)} | Avg Brl Dist {row['avgDistanceOnBarrels']}"
        )


def print_gaps(rows: pd.DataFrame) -> None:
    print("\n=== Much Higher in Threat than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi").head(15).iterrows():
        print(
            f"{row['player']} ({row['team']}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta {int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT {row['longballThreat']:.1f}, LBI {row['longballIndex']:.1f}"
        )

    print("\n=== Much Lower in Threat than LBI ===")
    for _, row in rows.sort_values("rankDeltaThreatMinusLbi", ascending=False).head(15).iterrows():
        print(
            f"{row['player']} ({row['team']}) | Threat rank {int(row['threatRank'])}, "
            f"LBI rank {int(row['lbiRank'])}, delta +{int(row['rankDeltaThreatMinusLbi'])} | "
            f"LBT {row['longballThreat']:.1f}, LBI {row['longballIndex']:.1f}"
        )


def print_correlations(rows: pd.DataFrame) -> None:
    columns = ["longballThreat", "longballThreatV01", "longballIndex", "adjustedXhrPerPa", "barrelsPerPa", "actualHrPerPa"]
    corr = rows[columns].corr(numeric_only=True)["actualHrPerPa"].drop("actualHrPerPa")
    print("\n=== Same-season correlation with actual HR/PA (diagnostic only) ===")
    for name, value in corr.sort_values(ascending=False).items():
        print(f"{name}: {value:.3f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prototype Longball Threat v0.2.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--lbi-json", type=Path, default=DEFAULT_LBI_JSON)
    parser.add_argument("--pitch-cache", type=Path, default=DEFAULT_PITCH_CACHE)
    parser.add_argument("--pa-source", choices=["auto", "pybaseball", "pitch-cache"], default="auto")
    parser.add_argument("--min-pa", type=int, default=75)
    parser.add_argument("--min-bbe", type=int, default=40)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    players = load_lbi_players(args.lbi_json)
    cache_stats = load_pitch_cache_stats(args.pitch_cache)
    merged, pa_note = attach_plate_appearances(players, cache_stats, args.season, args.pa_source)
    rows = calculate_threat(merged, args.min_pa, args.min_bbe)

    print("=== Longball Threat v0.2 Diagnostic ===")
    print("Goal: park-neutral future home-run likelihood per plate appearance.")
    print("Formula: 75% Adjusted xHR/PA, 25% Barrels/PA.")
    print("Comparison: v0.1 = 55% Adjusted xHR/PA, 25% Barrels/PA, 10% Hard-hit air BBE/PA, 10% Avg Distance on Barrels.")
    print("Backtest note: 2021-2025 first-half to second-half testing favored this two-factor v0.2 by pooled correlation.")
    print("Scale: 100 = league average qualified hitter; 90th percentile component score ~= 150; scores uncapped.")
    print(f"PA source: {pa_note}")
    print(f"Eligibility: PA >= {args.min_pa}, BBE >= {args.min_bbe}")
    print(f"Qualified players: {len(rows)} of {len(players)} current LBI players")
    print(
        "Distribution: "
        f"median={rows['longballThreat'].median():.1f}, mean={rows['longballThreat'].mean():.1f}, "
        f"max={rows['longballThreat'].max():.1f}, min={rows['longballThreat'].min():.1f}"
    )

    print_table(rows, "Top 30 Longball Threat v0.2", 30)
    print_sanity(rows)
    print_gaps(rows)
    print_correlations(rows)

    print("\n=== Readout ===")
    print("Projected HR/600 is a rough blended diagnostic, not a published projection yet.")
    print("Recommended next validation: backtest first-half Longball Threat against second-half HR/PA for 2021-2025.")


if __name__ == "__main__":
    main()
