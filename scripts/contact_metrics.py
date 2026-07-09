#!/usr/bin/env python3
"""Public contact-rate helper for Longball Index context stats.

This module is intentionally separate from Storm Watch shadow code. It derives
plain contact metrics from the full pitch-level cache so public generators can
publish Pesky without depending on internal Power Access / Damage Access logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_integrity import scope_to_regular_season


PITCH_CONTEXT_COLUMNS = [
    "game_date",
    "batter",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "events",
    "description",
]

SWING_DESCRIPTIONS = {
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

CONTACT_DESCRIPTIONS = {
    "foul",
    "foul_tip",
    "foul_bunt",
    "bunt_foul_tip",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}

AT_BAT_EXCLUDED_EVENTS = {
    "catcher_interf",
    "caught_stealing_2b",
    "caught_stealing_3b",
    "caught_stealing_home",
    "hit_by_pitch",
    "intent_walk",
    "other_out",
    "pickoff_1b",
    "pickoff_2b",
    "pickoff_3b",
    "pickoff_caught_stealing_2b",
    "pickoff_caught_stealing_3b",
    "pickoff_caught_stealing_home",
    "sac_bunt",
    "sac_bunt_double_play",
    "sac_fly",
    "sac_fly_double_play",
    "stolen_base_2b",
    "stolen_base_3b",
    "stolen_base_home",
    "truncated_pa",
    "walk",
}

HIT_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
}


@dataclass(frozen=True)
class ContactMetricDiagnostics:
    source_rows: int
    regular_season_rows: int
    terminal_pa_rows: int
    batter_count: int


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def read_pitch_context(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PITCH_CONTEXT_COLUMNS)
    return pd.read_csv(path, usecols=lambda column: column in PITCH_CONTEXT_COLUMNS)


def normalize_pitch_context(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in PITCH_CONTEXT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    for column in ["batter", "game_pk", "at_bat_number", "pitch_number"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["batter"]).copy()
    if frame.empty:
        return frame[PITCH_CONTEXT_COLUMNS]
    frame["batter"] = frame["batter"].astype(int)
    frame["events"] = frame["events"].astype("string")
    frame["description"] = frame["description"].astype("string")
    return frame[PITCH_CONTEXT_COLUMNS]


def build_contact_metrics(
    pitches: pd.DataFrame,
    season: int,
) -> tuple[dict[int, dict[str, Any]], ContactMetricDiagnostics]:
    """Return batter-level contact metrics from a full pitch cache.

    Contact% is contacts divided by swings. Fouls and balls hit into play count
    as contact. True PA is counted from terminal pitch rows in the full pitch
    sequence, not from the batted-ball-only LBI frame.
    """

    source_rows = len(pitches)
    pitches = normalize_pitch_context(pitches)
    pitches = scope_to_regular_season(pitches, season)
    pitches = normalize_pitch_context(pitches)
    regular_season_rows = len(pitches)

    if pitches.empty:
        diagnostics = ContactMetricDiagnostics(
            source_rows=source_rows,
            regular_season_rows=regular_season_rows,
            terminal_pa_rows=0,
            batter_count=0,
        )
        return {}, diagnostics

    description = pitches["description"].fillna("").astype(str)
    events = pitches["events"].fillna("").astype(str).str.strip()
    pitches["_swing"] = description.isin(SWING_DESCRIPTIONS)
    pitches["_contact"] = description.isin(CONTACT_DESCRIPTIONS)

    terminal = (
        pitches[events.ne("")]
        .sort_values(["game_pk", "at_bat_number", "pitch_number"])
        .drop_duplicates(["game_pk", "at_bat_number", "batter"], keep="last")
    )
    pa_by_batter = terminal.groupby("batter").size()
    terminal_events = terminal["events"].fillna("").astype(str).str.strip().str.lower()
    terminal = terminal.assign(
        _event=terminal_events,
        _ab=~terminal_events.isin(AT_BAT_EXCLUDED_EVENTS),
        _hit=terminal_events.isin(HIT_EVENTS),
        _double=terminal_events.eq("double"),
        _triple=terminal_events.eq("triple"),
        _home_run=terminal_events.eq("home_run"),
    )
    batting_line = terminal.groupby("batter").agg(
        ab=("_ab", "sum"),
        hits=("_hit", "sum"),
        doubles=("_double", "sum"),
        triples=("_triple", "sum"),
        battingHomeRuns=("_home_run", "sum"),
    )

    grouped = pitches.groupby("batter").agg(
        contactSwings=("_swing", "sum"),
        contactContacts=("_contact", "sum"),
    )

    metrics: dict[int, dict[str, Any]] = {}
    for batter, row in grouped.iterrows():
        swings = int(row["contactSwings"])
        contacts = int(row["contactContacts"])
        batting_row = batting_line.loc[batter] if batter in batting_line.index else None
        metrics[int(batter)] = {
            "contactSwings": swings,
            "contactContacts": contacts,
            "contactPa": int(pa_by_batter.get(batter, 0)),
            "contactPct": safe_divide(float(contacts), float(swings)),
            "ab": int(batting_row["ab"]) if batting_row is not None else 0,
            "hits": int(batting_row["hits"]) if batting_row is not None else 0,
            "doubles": int(batting_row["doubles"]) if batting_row is not None else 0,
            "triples": int(batting_row["triples"]) if batting_row is not None else 0,
            "battingHomeRuns": int(batting_row["battingHomeRuns"]) if batting_row is not None else 0,
        }

    diagnostics = ContactMetricDiagnostics(
        source_rows=source_rows,
        regular_season_rows=regular_season_rows,
        terminal_pa_rows=int(len(terminal)),
        batter_count=len(metrics),
    )
    return metrics, diagnostics


def contact_metrics_from_cache(path: Path, season: int) -> tuple[dict[int, dict[str, Any]], ContactMetricDiagnostics]:
    return build_contact_metrics(read_pitch_context(path), season)
