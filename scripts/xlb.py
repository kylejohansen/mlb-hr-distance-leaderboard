#!/usr/bin/env python3
"""Expected Long Balls (xLB) v0.2 model helpers.

xLB scores terminal batted balls with a hierarchically smoothed home-run
probability based on exit velocity, launch angle, and batter-relative spray.
The production Hot Dog Stand loads a committed historical model artifact and
uses this module to score the current season without refitting live.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from data_integrity import scope_to_regular_season


ROOT = Path(__file__).resolve().parents[1]
XLB_VERSION = "0.2"
EVENT_UNIVERSE = "terminal_bbe"
DEFAULT_MODEL_PATH = ROOT / "data/models/xlb-v0.2-2021-2025.json"
EV_BIN_WIDTH = 2.5
LA_BIN_WIDTH = 4.0
EV_MIN = 50.0
EV_MAX = 122.5
LA_MIN = -50.0
LA_MAX = 70.0
EV_LA_PRIOR_BBE = 100.0
SPRAY_PRIOR_BBE = 50.0
REQUIRED_COLUMNS = {
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "events",
    "launch_speed",
    "launch_angle",
    "hc_x",
    "stand",
}


@dataclass
class XlbModel:
    global_hr_rate: float
    ev_la_rates: pd.Series
    directional_rates: pd.Series
    training_seasons: tuple[int, ...]
    training_bbe: int


def prepare_terminal_bbe(frame: pd.DataFrame, season: int | None = None) -> pd.DataFrame:
    """Return one terminal, EV/LA-tracked batted ball per plate appearance."""
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"xLB input is missing required columns: {', '.join(sorted(missing))}")

    bbe = frame.copy()
    if season is not None:
        bbe = scope_to_regular_season(bbe, season)
    bbe["launch_speed"] = pd.to_numeric(bbe["launch_speed"], errors="coerce")
    bbe["launch_angle"] = pd.to_numeric(bbe["launch_angle"], errors="coerce")
    bbe = bbe[
        bbe["events"].notna()
        & bbe["launch_speed"].notna()
        & bbe["launch_angle"].notna()
    ].copy()

    for column in ["game_pk", "at_bat_number", "pitch_number", "pitcher"]:
        bbe[column] = pd.to_numeric(bbe[column], errors="coerce").astype("Int64")
    bbe = bbe.dropna(subset=["pitcher", "game_pk", "at_bat_number"])
    bbe = bbe.sort_values(["game_pk", "at_bat_number", "pitch_number"])
    bbe = bbe.drop_duplicates(["game_pk", "at_bat_number", "pitcher"], keep="last")
    bbe["is_hr"] = bbe["events"].astype("string").str.lower().eq("home_run")

    stand = bbe["stand"].astype("string").str.upper()
    hc_x = pd.to_numeric(bbe["hc_x"], errors="coerce")
    pull = (stand.eq("R") & hc_x.lt(125)) | (stand.eq("L") & hc_x.gt(125))
    oppo = (stand.eq("R") & hc_x.gt(125)) | (stand.eq("L") & hc_x.lt(125))
    bbe["spray_side"] = np.select([pull, oppo], ["pull", "oppo"], default="unknown")
    bbe["ev_bin"] = np.floor(
        bbe["launch_speed"].clip(EV_MIN, EV_MAX) / EV_BIN_WIDTH
    ) * EV_BIN_WIDTH
    bbe["la_bin"] = np.floor(
        bbe["launch_angle"].clip(LA_MIN, LA_MAX) / LA_BIN_WIDTH
    ) * LA_BIN_WIDTH
    return bbe


def fit_xlb_model(training: pd.DataFrame, training_seasons: Iterable[int]) -> XlbModel:
    if training.empty:
        raise ValueError("Cannot fit xLB model on an empty training set")

    global_rate = float(training["is_hr"].mean())
    ev_la = training.groupby(["ev_bin", "la_bin"], observed=True)["is_hr"].agg(["sum", "count"])
    ev_la["rate"] = (ev_la["sum"] + EV_LA_PRIOR_BBE * global_rate) / (
        ev_la["count"] + EV_LA_PRIOR_BBE
    )

    directional = training.groupby(
        ["ev_bin", "la_bin", "spray_side"], observed=True
    )["is_hr"].agg(["sum", "count"])
    directional = directional.join(ev_la["rate"].rename("ev_la_rate"), on=["ev_bin", "la_bin"])
    directional["rate"] = (
        directional["sum"] + SPRAY_PRIOR_BBE * directional["ev_la_rate"]
    ) / (directional["count"] + SPRAY_PRIOR_BBE)
    return XlbModel(
        global_hr_rate=global_rate,
        ev_la_rates=ev_la["rate"],
        directional_rates=directional["rate"],
        training_seasons=tuple(sorted(training_seasons)),
        training_bbe=len(training),
    )


def score_terminal_bbe(frame: pd.DataFrame, model: XlbModel) -> pd.DataFrame:
    scored = frame.copy()
    keys = pd.MultiIndex.from_frame(scored[["ev_bin", "la_bin", "spray_side"]])
    scored["xlb_event"] = model.directional_rates.reindex(keys).to_numpy()
    missing = scored["xlb_event"].isna()
    if missing.any():
        ev_la_keys = pd.MultiIndex.from_frame(scored.loc[missing, ["ev_bin", "la_bin"]])
        scored.loc[missing, "xlb_event"] = model.ev_la_rates.reindex(ev_la_keys).to_numpy()
    scored["xlb_event"] = scored["xlb_event"].fillna(model.global_hr_rate).clip(0, 1)
    return scored


def aggregate_pitcher_xlb(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame(columns=["pitcher_id", "xlb_bbe", "xlb", "xlb_per_bbe"])
    grouped = scored.groupby("pitcher", observed=True).agg(
        xlb_bbe=("xlb_event", "size"),
        xlb=("xlb_event", "sum"),
    )
    grouped["xlb_per_bbe"] = grouped["xlb"] / grouped["xlb_bbe"].where(grouped["xlb_bbe"].gt(0))
    return grouped.reset_index().rename(columns={"pitcher": "pitcher_id"})


def _series_from_records(records: list[dict[str, Any]], keys: list[str]) -> pd.Series:
    if not records:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(records)
    index = pd.MultiIndex.from_frame(frame[keys])
    return pd.Series(frame["rate"].to_numpy(dtype=float), index=index)


def load_xlb_model(path: Path = DEFAULT_MODEL_PATH) -> XlbModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("version")) != XLB_VERSION:
        raise ValueError(f"Expected xLB model v{XLB_VERSION}, found {payload.get('version')}")
    return XlbModel(
        global_hr_rate=float(payload["globalHrRate"]),
        ev_la_rates=_series_from_records(payload["evLaRates"], ["ev_bin", "la_bin"]),
        directional_rates=_series_from_records(
            payload["directionalRates"], ["ev_bin", "la_bin", "spray_side"]
        ),
        training_seasons=tuple(int(value) for value in payload["trainingSeasons"]),
        training_bbe=int(payload["trainingBbe"]),
    )


def write_xlb_model(path: Path, model: XlbModel, source_paths: list[Path]) -> None:
    ev_la = model.ev_la_rates.rename("rate").reset_index().to_dict(orient="records")
    directional = model.directional_rates.rename("rate").reset_index().to_dict(orient="records")
    payload = {
        "version": XLB_VERSION,
        "eventUniverse": EVENT_UNIVERSE,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "trainingSeasons": list(model.training_seasons),
        "trainingBbe": model.training_bbe,
        "sourcePaths": [str(source.relative_to(ROOT)) for source in source_paths],
        "globalHrRate": model.global_hr_rate,
        "binning": {
            "exitVelocityMph": EV_BIN_WIDTH,
            "launchAngleDegrees": LA_BIN_WIDTH,
            "spray": "batter-relative pull/oppo/unknown from per-PA stand and hc_x centerline",
        },
        "priors": {
            "evLaBbe": EV_LA_PRIOR_BBE,
            "sprayBbe": SPRAY_PRIOR_BBE,
        },
        "evLaRates": ev_la,
        "directionalRates": directional,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the committed xLB v0.2 model artifact.")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024, 2025])
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_paths = [ROOT / f"data/raw/statcast-bbe-events-{season}.csv" for season in args.seasons]
    frames = []
    for season, source in zip(args.seasons, source_paths):
        if not source.exists():
            raise FileNotFoundError(f"Missing historical xLB source: {source}")
        chunks = []
        for chunk in pd.read_csv(source, chunksize=250_000):
            prepared = prepare_terminal_bbe(chunk, season)
            if not prepared.empty:
                chunks.append(prepared)
        season_frame = pd.concat(chunks, ignore_index=True)
        season_frame = season_frame.sort_values(["game_pk", "at_bat_number", "pitch_number"])
        season_frame = season_frame.drop_duplicates(
            ["game_pk", "at_bat_number", "pitcher"], keep="last"
        )
        frames.append(season_frame)
    training = pd.concat(frames, ignore_index=True)
    model = fit_xlb_model(training, args.seasons)
    write_xlb_model(args.output, model, source_paths)
    print(f"Wrote xLB v{XLB_VERSION} model ({model.training_bbe:,} terminal BBE) to {args.output}")


if __name__ == "__main__":
    main()
