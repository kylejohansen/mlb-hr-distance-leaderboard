"""Production helpers for Longball Index v1.4.

LBI v1.4 is descriptive and model-free at scoring time: eligibility and event
scores use observed batted-ball physics plus standard park-count geometry. xHR,
adjusted xHR, and HRT modeled quality scores are intentionally not inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd


LBI_V14_VERSION = "1.4"
LBI_V14_MIN_LAUNCH_ANGLE = 14.0
LBI_V14_MAX_LAUNCH_ANGLE = 50.0
LBI_V14_ACTUAL_HR_MIN_STANDARD_PARKS = 1.0
LBI_V14_ROBBED_MIN_STANDARD_PARKS = 8.0
LBI_V14_LA_BIN_WIDTH = 3
LBI_V14_IMPROB_SHRINK_K = 8.0
LBI_V14_MIN_EVENTS_FOR_ARCHETYPE = 8
LBI_V14_MIN_PA_FOR_NORMALIZATION = 170
LBI_V14_SPRAY_CENTER_X = 125.0
LBI_V14_SPRAY_HOME_Y = 199.0
LBI_V14_CENTER_ANGLE_DEGREES = 15.0
LBI_V14_THUMP_EV_WEIGHT = 0.50
LBI_V14_THUMP_DISTANCE_WEIGHT = 0.50


def _number(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value) or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(event: Mapping[str, Any] | pd.Series, *names: str) -> Any:
    for name in names:
        if name in event:
            value = event[name]
            if value is not None and not pd.isna(value):
                return value
    return None


def compute_true_spray_angle(
    hc_x: Any,
    hc_y: Any,
    stand: Any,
    *,
    center_x: float = LBI_V14_SPRAY_CENTER_X,
    home_y: float = LBI_V14_SPRAY_HOME_Y,
) -> float | None:
    """Return batter-relative spray angle; positive means opposite field."""
    x = _number(hc_x)
    y = _number(hc_y)
    side = str(stand or "").strip().upper()
    if x is None or y is None or side not in {"L", "R"}:
        return None
    y_distance = home_y - y
    if y_distance <= 0:
        return None
    field_angle = math.degrees(math.atan2(x - center_x, y_distance))
    return -field_angle if side == "L" else field_angle


def classify_batter_relative_spray(
    spray_angle: Any,
    *,
    center_degrees: float = LBI_V14_CENTER_ANGLE_DEGREES,
) -> str | None:
    angle = _number(spray_angle)
    if angle is None:
        return None
    if angle < -center_degrees:
        return "pull"
    if angle > center_degrees:
        return "oppo"
    return "center"


def is_lbi_v14_eligible_long_ball_physics_only(event: Mapping[str, Any] | pd.Series) -> tuple[bool, str]:
    """Physics-only LBI v1.4 long-ball gate; does not read xHR/adjusted xHR."""
    launch_angle = _number(_field(event, "launch_angle", "launch_angle_detail", "launch_angle_statcast"))
    if launch_angle is None:
        return False, "missing_launch_angle"
    if launch_angle < LBI_V14_MIN_LAUNCH_ANGLE:
        return False, "launch_angle_below_14"
    if launch_angle > LBI_V14_MAX_LAUNCH_ANGLE:
        return False, "launch_angle_above_50"

    standard_parks = _number(
        _field(event, "standard_parks_cleared", "standard_ct", "ct", "parks_cleared")
    )
    if standard_parks is None:
        return False, "missing_standard_parks_cleared"

    result = str(_field(event, "result_norm", "result", "events") or "").strip().lower()
    actual_over_fence = result == "home_run" and standard_parks >= LBI_V14_ACTUAL_HR_MIN_STANDARD_PARKS
    robbed_long_ball = result != "home_run" and standard_parks >= LBI_V14_ROBBED_MIN_STANDARD_PARKS
    if actual_over_fence:
        return True, "actual_over_fence_hr_standard_parks_1_plus"
    if robbed_long_ball:
        return True, "non_hr_standard_parks_8_plus"
    return False, "not_actual_hr_or_8_plus_parks"


def _zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    std = numeric.std(ddof=0)
    if not std or pd.isna(std):
        return pd.Series(0.0, index=values.index)
    return (numeric - numeric.mean()) / std


def compute_lbi_v14_thump_event(
    exit_velocity: Any,
    park_neutral_estimated_distance: Any,
    *,
    ev_mean: float,
    ev_std: float,
    distance_mean: float,
    distance_std: float,
    shift: float = 0.0,
) -> float | None:
    ev = _number(exit_velocity)
    distance = _number(park_neutral_estimated_distance)
    if ev is None or distance is None or not ev_std or not distance_std:
        return None
    ev_z = (ev - ev_mean) / ev_std
    distance_z = (distance - distance_mean) / distance_std
    return LBI_V14_THUMP_EV_WEIGHT * ev_z + LBI_V14_THUMP_DISTANCE_WEIGHT * distance_z + shift


def compute_lbi_v14_improbability_event(cell_probability: Any) -> float | None:
    probability = _number(cell_probability)
    if probability is None or probability <= 0:
        return None
    return -math.log(probability)


def shrink_lbi_v14_improbability(
    improb_raw: Any,
    event_count: Any,
    league_average: float,
    *,
    shrink_k: float = LBI_V14_IMPROB_SHRINK_K,
) -> float | None:
    value = _number(improb_raw)
    count = _number(event_count)
    if value is None or count is None:
        return None
    return ((count * value) + (shrink_k * league_average)) / (count + shrink_k)


def compute_lbi_v14_archetype(
    thump_index: Any,
    improbability_index: Any,
    event_count: Any,
    *,
    min_events: int = LBI_V14_MIN_EVENTS_FOR_ARCHETYPE,
) -> str:
    thump = _number(thump_index)
    improb = _number(improbability_index)
    count = _number(event_count) or 0
    if thump is None or improb is None or count < min_events:
        return "Balanced Power"
    if thump >= 110 and improb >= 110:
        return "Apex Power"
    if thump >= 108 and improb < 104:
        return "Pure Masher"
    if improb >= 108 and thump < 104:
        return "Artist"
    return "Balanced Power"


def add_lbi_v14_event_columns(
    events: pd.DataFrame,
    *,
    standard_parks_col: str = "standard_parks_cleared",
    result_col: str = "result_norm",
    ev_col: str = "exit_velocity",
    distance_col: str = "hr_distance",
    launch_angle_col: str = "launch_angle",
    hc_x_col: str = "hc_x",
    hc_y_col: str = "hc_y",
    stand_col: str = "stand",
    la_bin_width: int = LBI_V14_LA_BIN_WIDTH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = events.copy()
    rows["standard_parks_cleared"] = pd.to_numeric(rows[standard_parks_col], errors="coerce")
    rows["result_norm"] = rows[result_col].astype("string").str.lower()
    rows["exit_velocity"] = pd.to_numeric(rows[ev_col], errors="coerce")
    rows["hr_distance"] = pd.to_numeric(rows[distance_col], errors="coerce")
    rows["launch_angle"] = pd.to_numeric(rows[launch_angle_col], errors="coerce")

    rows["spray_angle"] = [
        compute_true_spray_angle(hc_x, hc_y, stand)
        for hc_x, hc_y, stand in zip(rows.get(hc_x_col), rows.get(hc_y_col), rows.get(stand_col))
    ]
    rows["spray_bucket"] = rows["spray_angle"].map(classify_batter_relative_spray)

    gate = rows.apply(is_lbi_v14_eligible_long_ball_physics_only, axis=1)
    rows["lbi_v14_eligible"] = [passed for passed, _reason in gate]
    rows["lbi_v14_eligibility_reason"] = [reason for _passed, reason in gate]
    eligible = rows[rows["lbi_v14_eligible"]].copy()

    ev_mean = float(eligible["exit_velocity"].mean())
    ev_std = float(eligible["exit_velocity"].std(ddof=0))
    distance_mean = float(eligible["hr_distance"].mean())
    distance_std = float(eligible["hr_distance"].std(ddof=0))
    raw = (
        LBI_V14_THUMP_EV_WEIGHT * _zscore(eligible["exit_velocity"])
        + LBI_V14_THUMP_DISTANCE_WEIGHT * _zscore(eligible["hr_distance"])
    )
    shift = abs(float(raw.min())) + 0.01 if len(raw.dropna()) else 0.0
    eligible["thump_evt"] = [
        compute_lbi_v14_thump_event(
            ev,
            distance,
            ev_mean=ev_mean,
            ev_std=ev_std,
            distance_mean=distance_mean,
            distance_std=distance_std,
            shift=shift,
        )
        for ev, distance in zip(eligible["exit_velocity"], eligible["hr_distance"])
    ]

    eligible["la_bin"] = (
        eligible["launch_angle"] // la_bin_width * la_bin_width
    ).astype("Int64").astype("string")
    valid_cell = eligible["spray_bucket"].notna() & eligible["launch_angle"].notna()
    eligible["improb_cell"] = eligible["spray_bucket"].astype("string") + "|" + eligible["la_bin"].astype("string")
    cell_counts = eligible.loc[valid_cell, "improb_cell"].value_counts()
    total = int(cell_counts.sum())
    cell_rates = pd.DataFrame(columns=["cell", "cell_probability", "improb_evt", "event_count"])
    if total:
        cell_rates = (cell_counts / total).rename("cell_probability").reset_index()
        cell_rates = cell_rates.rename(columns={"improb_cell": "cell"})
        cell_rates["improb_evt"] = cell_rates["cell_probability"].map(compute_lbi_v14_improbability_event)
        cell_rates["event_count"] = cell_rates["cell"].map(cell_counts.to_dict())
        lookup = dict(zip(cell_rates["cell"], cell_rates["improb_evt"]))
        eligible["improb_evt"] = eligible["improb_cell"].map(lookup)
        pool_mean = float(eligible.loc[valid_cell, "improb_evt"].mean())
    else:
        eligible["improb_evt"] = pd.NA
        pool_mean = float("nan")
    eligible["improb_missing_spray"] = eligible["improb_evt"].isna()
    if not math.isnan(pool_mean):
        eligible["improb_evt"] = eligible["improb_evt"].fillna(pool_mean)
    return eligible, cell_rates.sort_values("improb_evt", ascending=False)


def apply_lbi_v14_player_scores(
    players: list[dict[str, Any]],
    eligible_events: pd.DataFrame,
    *,
    shrink_k: float = LBI_V14_IMPROB_SHRINK_K,
    min_events_for_archetype: int = LBI_V14_MIN_EVENTS_FOR_ARCHETYPE,
    min_pa_for_normalization: int = LBI_V14_MIN_PA_FOR_NORMALIZATION,
) -> dict[str, Any]:
    if not players:
        return {
            "lbiV14EligibleEvents": 0,
            "lbiV14LeagueThumpRate": None,
            "lbiV14LeagueImprobability": None,
            "lbiV14NormalizationPlayers": 0,
            "lbiV14MinPaForNormalization": min_pa_for_normalization,
        }

    grouped = eligible_events.groupby("batter_id", dropna=False).agg(
        longBallEventCount=("lbi_v14_eligible", "size"),
        lbiActualHrEvents=("result_norm", lambda s: int(s.astype("string").str.lower().eq("home_run").sum())),
        lbiRobbedEvents=("lbi_v14_eligibility_reason", lambda s: int((s == "non_hr_standard_parks_8_plus").sum())),
        thump_sum=("thump_evt", "sum"),
        thump_event_mean=("thump_evt", "mean"),
        improbability_raw=("improb_evt", "mean"),
        improb_missing_spray_rate=("improb_missing_spray", "mean"),
        pull_events=("spray_bucket", lambda s: int((s == "pull").sum())),
        center_events=("spray_bucket", lambda s: int((s == "center").sum())),
        oppo_events=("spray_bucket", lambda s: int((s == "oppo").sum())),
    )
    by_batter = grouped.to_dict("index")
    pool_mean_improb = float(eligible_events["improb_evt"].mean()) if not eligible_events.empty else float("nan")

    for player in players:
        batter = player.get("batter")
        row = by_batter.get(batter, {})
        pa = _number(player.get("pa")) or 0.0
        count = int(row.get("longBallEventCount") or 0)
        thump_sum = _number(row.get("thump_sum")) or 0.0
        thump_rate = thump_sum / pa if pa else None
        improb_raw = _number(row.get("improbability_raw"))
        if math.isnan(pool_mean_improb):
            improb_stab = None
        elif count == 0:
            improb_stab = pool_mean_improb
        else:
            improb_stab = shrink_lbi_v14_improbability(improb_raw, count, pool_mean_improb, shrink_k=shrink_k)
        known_spray = int(row.get("pull_events") or 0) + int(row.get("center_events") or 0) + int(row.get("oppo_events") or 0)
        spray_shares = []
        if known_spray:
            spray_shares = [
                (int(row.get("pull_events") or 0) / known_spray),
                (int(row.get("center_events") or 0) / known_spray),
                (int(row.get("oppo_events") or 0) / known_spray),
            ]
        entropy = -sum(share * math.log(share, 3) for share in spray_shares if share > 0) if spray_shares else None
        player["_lbiV14ThumpRate"] = thump_rate
        player["_lbiV14ImprobabilityShrunk"] = improb_stab
        player["_lbiV14NormalizationQualified"] = (
            thump_rate is not None
            and improb_stab is not None
            and count >= min_events_for_archetype
            and pa >= min_pa_for_normalization
        )
        player["longBallEventCount"] = count
        player["lbiActualHrEvents"] = int(row.get("lbiActualHrEvents") or 0)
        player["lbiRobbedEvents"] = int(row.get("lbiRobbedEvents") or 0)
        player["sprayDiversity"] = round(float(entropy), 3) if entropy is not None else None
        player["lbiV14PullPct"] = round(float((int(row.get("pull_events") or 0) / known_spray)), 3) if known_spray else None
        player["lbiV14CenterPct"] = round(float((int(row.get("center_events") or 0) / known_spray)), 3) if known_spray else None
        player["lbiV14OppoPct"] = round(float((int(row.get("oppo_events") or 0) / known_spray)), 3) if known_spray else None
        player["lbiV14ImprobMissingSprayRate"] = (
            round(float(row.get("improb_missing_spray_rate")), 3)
            if row.get("improb_missing_spray_rate") is not None and not pd.isna(row.get("improb_missing_spray_rate"))
            else None
        )

    normalization_players = [player for player in players if player.get("_lbiV14NormalizationQualified")]
    thump_rates = [
        player.get("_lbiV14ThumpRate")
        for player in normalization_players
        if player.get("_lbiV14ThumpRate") is not None
    ]
    improb_values = [
        player.get("_lbiV14ImprobabilityShrunk")
        for player in normalization_players
        if player.get("_lbiV14ImprobabilityShrunk") is not None
    ]
    league_thump = sum(thump_rates) / len(thump_rates) if thump_rates else None
    league_improb = sum(improb_values) / len(improb_values) if improb_values else None

    for player in players:
        thump_rate = player.pop("_lbiV14ThumpRate", None)
        improb_stab = player.pop("_lbiV14ImprobabilityShrunk", None)
        thump_index = 100 * thump_rate / league_thump if league_thump and thump_rate is not None else None
        improb_index = 100 * improb_stab / league_improb if league_improb and improb_stab is not None else None
        player["thumpIndex"] = round(float(thump_index), 1) if thump_index is not None else None
        player["improbabilityIndex"] = round(float(improb_index), 1) if improb_index is not None else None
        player["longballIndex"] = (
            round(float(0.5 * thump_index + 0.5 * improb_index), 1)
            if thump_index is not None and improb_index is not None
            else 0
        )
        player["lbiArchetype"] = compute_lbi_v14_archetype(
            thump_index,
            improb_index,
            player.get("longBallEventCount"),
            min_events=min_events_for_archetype,
        )
        player["lbiSampleFlag"] = (
            "Full confidence"
            if (player.get("longBallEventCount") or 0) >= min_events_for_archetype
            else "Low long-ball event sample"
        )

    return {
        "lbiV14EligibleEvents": int(len(eligible_events)),
        "lbiV14LeagueThumpRate": league_thump,
        "lbiV14LeagueImprobability": league_improb,
        "lbiV14NormalizationPlayers": len(normalization_players),
        "lbiV14MinPaForNormalization": min_pa_for_normalization,
        "lbiV14ImprobabilityShrinkK": shrink_k,
        "lbiV14MinEventsForArchetype": min_events_for_archetype,
    }
