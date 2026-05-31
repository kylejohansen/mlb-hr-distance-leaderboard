"""Shared data-integrity guards for Long Ball stat generation.

These helpers protect formulas from a recurring failure mode: Statcast batted
ball inputs are present, but the Home Run Tracker/HRT side is missing and would
otherwise be coerced to zero. Real zero HRT damage is allowed to remain zero;
only physically suspicious missing-HRT rows are flagged for quarantine.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

REGULAR_SEASON_WINDOWS = {
    2021: (date(2021, 4, 1), date(2021, 10, 3)),
    2022: (date(2022, 4, 7), date(2022, 10, 5)),
    2023: (date(2023, 3, 30), date(2023, 10, 1)),
    2024: (date(2024, 3, 28), date(2024, 9, 30)),
    2025: (date(2025, 3, 27), date(2025, 9, 28)),
    2026: (date(2026, 3, 26), date(2026, 10, 4)),
}

MIN_HRT_DETAIL_BATTERS = {
    2021: 450,
    2022: 450,
    2023: 450,
    2024: 450,
    2025: 450,
    2026: 300,
}


def regular_season_window(season: int) -> tuple[date, date]:
    try:
        return REGULAR_SEASON_WINDOWS[season]
    except KeyError as error:
        raise ValueError(f"Missing regular-season date window for {season}") from error


def scope_to_regular_season(
    frame: pd.DataFrame,
    season: int,
    *,
    date_column: str = "game_date",
) -> pd.DataFrame:
    """Return rows inside the configured regular-season date window.

    This is intentionally date-boundary based. The current pitch cache does not
    preserve `game_type`, so date scoping is the least invasive way to align the
    Statcast source with Home Run Tracker for LBI/HDI diagnostics.
    """

    if frame.empty or date_column not in frame.columns:
        return frame.copy()

    start, end = regular_season_window(season)
    scoped = frame.copy()
    dates = pd.to_datetime(scoped[date_column], errors="coerce").dt.date
    return scoped[dates.between(start, end, inclusive="both")].copy()


def validate_hrt_detail_completeness(details: pd.DataFrame, season: int, *, label: str = "HRT detail cache") -> None:
    if details.empty or "batter_id" not in details.columns:
        raise RuntimeError(f"{label} for {season} is empty or missing batter_id")

    unique_batters = pd.to_numeric(details["batter_id"], errors="coerce").dropna().astype(int).nunique()
    minimum = MIN_HRT_DETAIL_BATTERS.get(season)
    if minimum is not None and unique_batters < minimum:
        raise RuntimeError(
            f"{label} for {season} looks incomplete: {unique_batters} unique batters, "
            f"expected at least {minimum}. Refresh from the full Savant aggregate min=0 list."
        )


def to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def is_missing_hrt_statcast_contradiction(
    *,
    hrt_missing: bool,
    bbe: Any,
    ev90: Any = None,
    thunder_bbe: Any = None,
    barrels: Any = None,
    hr: Any = None,
    min_bbe: int = 50,
) -> tuple[bool, str | None]:
    """Return whether a missing-HRT row should be quarantined.

    The guard is intentionally conservative. A player with no HRT row and no
    meaningful power contact is a legitimate zero. A player with enough BBE and
    obvious Statcast power markers should not be silently treated as zero xHR.
    """

    if not hrt_missing:
        return False, None

    bbe_value = to_number(bbe) or 0
    if bbe_value < min_bbe:
        return False, None

    ev90_value = to_number(ev90)
    thunder_value = to_number(thunder_bbe) or 0
    barrel_value = to_number(barrels) or 0
    hr_value = to_number(hr) or 0

    if hr_value > 0:
        return True, "missing HRT despite actual HR"
    if thunder_value > 0:
        return True, "missing HRT despite HR-window thunder"
    if ev90_value is not None and ev90_value >= 105:
        return True, "missing HRT despite EV90 >= 105"
    if barrel_value >= 5:
        return True, "missing HRT despite 5+ barrels"

    return False, None


def print_integrity_quarantine(
    label: str,
    rows: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> None:
    if not rows:
        return

    print(f"{label}: quarantined {len(rows)} missing-HRT/Statcast contradiction rows")
    for row in rows[:limit]:
        player = row.get("player") or row.get("name") or row.get("batter") or "unknown"
        batter = row.get("batter") or row.get("batterId") or ""
        reason = row.get("integrityReason") or row.get("reason") or "missing HRT"
        bbe = row.get("bbe") or row.get("firstBbe") or ""
        ev90 = row.get("ev90") or row.get("firstEv90") or ""
        thunder = row.get("hrWindowThunderBbe") or row.get("firstLa25_40_105Bbe") or ""
        print(f"  - {player} ({batter}) | BBE {bbe} | EV90 {ev90} | Thunder {thunder} | {reason}")
