#!/usr/bin/env python3
"""Write retained internal LBI v2 T6040 shadow snapshots.

T6040 is an internal-only LBI v2 thesis candidate:
60% Adjusted xHR/BBE score and 40% HR-Window Thunder score.

This script does not change production LBI, public JSON, frontend output, or
Scouting Report logic. It reads the current production LBI JSON and writes a
dated retained snapshot under data/shadow/lbi_t6040/ so later evaluations can
test whether players elevated by T6040 out-produce players faded by T6040.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("public/data/hr-distance-latest.json")
DEFAULT_OUTPUT_DIR = Path("data/shadow/lbi_t6040")
T6040_WEIGHTS = {
    "adjustedXhrPerBbe": 0.60,
    "hrWindowThunderRate": 0.40,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an internal T6040 LBI v2 shadow snapshot.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Current production LBI JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Retained shadow snapshot directory.")
    parser.add_argument("--date", help="Snapshot date YYYY-MM-DD. Defaults to input generatedAt date.")
    parser.add_argument("--limit", type=int, default=15, help="Divergence-list size.")
    parser.add_argument("--replace-existing", action="store_true", help="Replace an existing same-date snapshot. Use only for internal schema refreshes.")
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


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def component_score(player: dict[str, Any], key: str) -> float:
    components = player.get("lbiComponents") if isinstance(player.get("lbiComponents"), dict) else {}
    component = components.get(key) if isinstance(components.get(key), dict) else {}
    return number(component.get("score"))


def thunder_share(thunder_rate: float, xhr_per_bbe: float) -> float | None:
    if xhr_per_bbe <= 0:
        return None
    return thunder_rate / xhr_per_bbe


def rank_rows(rows: list[dict[str, Any]], key: str, rank_key: str) -> None:
    sorted_rows = sorted(rows, key=lambda row: (-number(row.get(key)), str(row.get("player") or "")))
    for index, row in enumerate(sorted_rows, start=1):
        row[rank_key] = index


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def classify_signal(row: dict[str, Any], thresholds: dict[str, float]) -> None:
    xhr = number(row.get("rawXhrPerBbe"))
    thunder_rate = number(row.get("hrWindowThunderRate"))
    if xhr >= thresholds["rawXhrPerBbeMedian"] and thunder_rate >= thresholds["hrWindowThunderRateMedian"]:
        row["t6040SignalBucket"] = "real_signal"
        row["t6040SignalLabel"] = "Real signal"
        row["t6040SignalReason"] = "xHR/BBE and Thunder rate are both above the qualified-pool median."
    else:
        row["t6040SignalBucket"] = "visible_noise"
        row["t6040SignalLabel"] = "Visible noise"
        row["t6040SignalReason"] = "One or both core rates sit below the qualified-pool median; treat the elevation as visible context, not primary thesis evidence."


def shadow_player(player: dict[str, Any]) -> dict[str, Any]:
    xhr_score = component_score(player, "adjustedXhrPerBbe")
    thunder_score = component_score(player, "hrWindowThunderRate")
    xhr_per_bbe = number(player.get("xhrPerBbe"))
    thunder_rate = number(player.get("hrWindowThunderRate"))
    t6040 = (
        T6040_WEIGHTS["adjustedXhrPerBbe"] * xhr_score
        + T6040_WEIGHTS["hrWindowThunderRate"] * thunder_score
    )
    return {
        "playerId": integer(player.get("batter") or player.get("playerId")),
        "player": str(player.get("player") or ""),
        "team": str(player.get("team") or ""),
        "bbe": integer(player.get("bbe")),
        "pa": integer(player.get("pa")),
        "hr": integer(player.get("hr")),
        "lbiV13": round(number(player.get("longballIndex")), 1),
        "t6040": round(t6040, 1),
        "rawXhrPerBbe": round(xhr_per_bbe, 5),
        "hrWindowThunderRate": round(thunder_rate, 5),
        "thunderShare": None if thunder_share(thunder_rate, xhr_per_bbe) is None else round(thunder_share(thunder_rate, xhr_per_bbe), 3),
        "adjustedXhrPerBbeScore": round(xhr_score, 1),
        "hrWindowThunderScore": round(thunder_score, 1),
    }


def divergence_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "playerId": row["playerId"],
        "player": row["player"],
        "team": row["team"],
        "rankDelta": row["rankDelta"],
        "rankV13": row["rankV13"],
        "rankT6040": row["rankT6040"],
        "lbiV13": row["lbiV13"],
        "t6040": row["t6040"],
        "rawXhrPerBbe": row["rawXhrPerBbe"],
        "hrWindowThunderRate": row["hrWindowThunderRate"],
        "thunderShare": row["thunderShare"],
        "t6040SignalBucket": row["t6040SignalBucket"],
        "t6040SignalLabel": row["t6040SignalLabel"],
        "t6040SignalReason": row["t6040SignalReason"],
        "bbe": row["bbe"],
        "pa": row["pa"],
        "hr": row["hr"],
    }


def build_snapshot(payload: dict[str, Any], snapshot_date: str, limit: int, input_path: Path) -> dict[str, Any]:
    players = [shadow_player(player) for player in payload.get("players", []) if isinstance(player, dict)]
    players = [player for player in players if player["playerId"] and player["bbe"] > 0]
    signal_thresholds = {
        "rawXhrPerBbeMedian": round(median([row["rawXhrPerBbe"] for row in players]), 5),
        "hrWindowThunderRateMedian": round(median([row["hrWindowThunderRate"] for row in players]), 5),
    }
    for row in players:
        classify_signal(row, signal_thresholds)
    rank_rows(players, "lbiV13", "rankV13")
    rank_rows(players, "t6040", "rankT6040")
    for row in players:
        row["rankDelta"] = row["rankV13"] - row["rankT6040"]

    players = sorted(players, key=lambda row: row["rankV13"])
    elevated = sorted(players, key=lambda row: (-row["rankDelta"], row["rankT6040"], row["player"]))[:limit]
    faded = sorted(players, key=lambda row: (row["rankDelta"], row["rankV13"], row["player"]))[:limit]
    top_v13 = sorted(players, key=lambda row: row["rankV13"])[:30]
    top_t6040 = sorted(players, key=lambda row: row["rankT6040"])[:30]
    qualified_by = payload.get("qualifiedBy") if isinstance(payload.get("qualifiedBy"), dict) else {}

    return {
        "snapshotDate": snapshot_date,
        "generatedAt": payload.get("generatedAt"),
        "season": payload.get("season") or (payload.get("source") or {}).get("season"),
        "sourcePath": str(input_path),
        "model": {
            "name": "LBI v2 T6040 shadow",
            "status": "internal-shadow",
            "description": "60% Adjusted xHR/BBE score + 40% HR-Window Thunder score.",
            "weights": T6040_WEIGHTS,
            "productionLbi": "v1.3 remains public production LBI",
            "signalClassification": {
                "real_signal": "raw xHR/BBE >= qualified-pool median AND HR-Window Thunder Rate >= qualified-pool median",
                "visible_noise": "one or both core rates below median; keep visible but evaluate separately",
                "rationale": "The shadow test should judge T6040's elite-contact claim, while keeping low-denominator ratio spikes transparent instead of filtering them off the board.",
                "thresholds": signal_thresholds,
            },
        },
        "qualifiedBy": {
            "minimumBbe": qualified_by.get("minimumBbe"),
            "estimatedTeamGames": qualified_by.get("estimatedTeamGames"),
        },
        "divergenceLists": {
            "elevatedByT6040": [divergence_entry(row) for row in elevated],
            "fadedByT6040": [divergence_entry(row) for row in faded],
        },
        "top30": {
            "v13": [divergence_entry(row) for row in top_v13],
            "t6040": [divergence_entry(row) for row in top_t6040],
        },
        "players": players,
    }


def write_snapshot(snapshot: dict[str, Any], output_dir: Path, replace_existing: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"snapshot_{snapshot['snapshotDate']}.json"
    if path.exists() and not replace_existing:
        raise SystemExit(f"Refusing to overwrite existing snapshot: {path}")
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return path


def print_divergence(snapshot: dict[str, Any]) -> None:
    print(f"Wrote T6040 shadow snapshot for {snapshot['snapshotDate']}")
    print(f"Qualified players: {len(snapshot['players'])}")
    print(f"Estimated team games: {snapshot['qualifiedBy'].get('estimatedTeamGames')}")
    for title, key in [("Elevated by T6040", "elevatedByT6040"), ("Faded by T6040", "fadedByT6040")]:
        print(f"\n{title}:")
        for row in snapshot["divergenceLists"][key]:
            share = "NA" if row["thunderShare"] is None else f"{row['thunderShare']:.2f}"
            print(
                f"{row['rankDelta']:+4d} | T6040 {row['rankT6040']:>3} vs v1.3 {row['rankV13']:>3} | "
                f"{row['player']} ({row['team']}) | T6040 {row['t6040']:.1f} | "
                f"v1.3 {row['lbiV13']:.1f} | {row['t6040SignalLabel']} | Thunder share {share} | "
                f"BBE {row['bbe']} | HR {row['hr']}"
            )


def main() -> None:
    args = parse_args()
    payload = load_json(args.input)
    snapshot_date = parse_snapshot_date(payload, args.date)
    snapshot = build_snapshot(payload, snapshot_date, args.limit, args.input)
    path = write_snapshot(snapshot, args.output_dir, args.replace_existing)
    print_divergence(snapshot)
    print(f"\nSnapshot path: {path}")


if __name__ == "__main__":
    main()
