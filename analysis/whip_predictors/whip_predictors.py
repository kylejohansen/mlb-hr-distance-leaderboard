#!/usr/bin/env python3
"""Evaluate which current pitching metrics best predict future WHIP.

The project is intentionally cache-first. Raw FanGraphs and Statcast pulls are
saved under analysis/whip_predictors/data/raw, then all downstream results are
derived from those local files.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import subprocess
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


SEASONS = list(range(2015, 2026))
C_GRID = [100, 250, 500, 750, 1000, 1500]
C_IP_GRID = [20, 40, 60, 80, 100, 150]
C_TBF_GRID = [100, 200, 300, 500, 750, 1000]
ALPHA_GRID = [round(x / 100, 2) for x in range(0, 101, 5)]
LAMBDA_GRID = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50]
GAMMA_GRID = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50]
CUTOFFS = ["04-30", "05-31", "06-30", "07-31"]
ROLLING_WINDOWS = [
    ("first50_next100", 50, 100),
    ("first100_next100", 100, 100),
    ("first150_next150", 150, 150),
    ("first200_rest", 200, None),
]

HIT_EVENTS = {"single", "double", "triple", "home_run"}
HR_EVENTS = {"home_run"}
K_EVENTS = {"strikeout", "strikeout_double_play"}
BB_EVENTS = {"walk", "intent_walk"}
HBP_EVENTS = {"hit_by_pitch"}
SF_EVENTS = {"sac_fly", "sac_fly_double_play"}
SH_EVENTS = {"sac_bunt", "sac_bunt_double_play"}
CI_EVENTS = {"catcher_interf"}
NON_AB_EVENTS = BB_EVENTS | HBP_EVENTS | SF_EVENTS | SH_EVENTS | CI_EVENTS
BBE_DESCRIPTIONS = {
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}

OUTS_BY_EVENT = {
    "field_out": 1,
    "fielders_choice_out": 1,
    "force_out": 1,
    "grounded_into_double_play": 2,
    "double_play": 2,
    "sac_fly_double_play": 2,
    "strikeout_double_play": 2,
    "triple_play": 3,
    "strikeout": 1,
    "sac_fly": 1,
    "sac_bunt": 1,
    "other_out": 1,
}

ROLE_THRESHOLDS = {
    "all": (40.0, 30.0),
    "starter": (80.0, 60.0),
    "reliever": (25.0, 20.0),
}

PREDICTOR_DIRECTIONS = {
    "whip": "low",
    "kbb": "high",
    "xwhip_lgbabip": "low",
    "xwhip_regbabip_tuned": "low",
    "xwhip_statcast": "low",
    "wsi_raw": "high",
    "wsi_xlgbabip": "high",
    "wsi_xreg_tuned": "high",
    "wsi_xstatcast": "high",
    "wsi_ubb_xlgbabip": "high",
    "whip_reg_tuned": "low",
    "kbb_reg_tuned": "high",
    "wsi_reg_tuned": "high",
    "wsi_xwhip_regkbb_tuned": "high",
    "wsi_blend_tuned": "high",
    "wsi_tuned": "high",
}

BASE_MODEL_SPECS = [
    ("WHIP", ["whip"]),
    ("KBB", ["kbb"]),
    ("xWHIP_lgBABIP", ["xwhip_lgbabip"]),
    ("xWHIP_Statcast", ["xwhip_statcast"]),
    ("WSI_raw", ["wsi_raw"]),
    ("WSI_xWHIP_lgBABIP", ["wsi_xlgbabip"]),
    ("WSI_xWHIP_Statcast", ["wsi_xstatcast"]),
    ("WSI_uBB_xWHIP_lgBABIP", ["wsi_ubb_xlgbabip"]),
    ("WHIP_plus_KBB", ["whip", "kbb"]),
    ("xWHIP_lgBABIP_plus_KBB", ["xwhip_lgbabip", "kbb"]),
    ("xWHIP_Statcast_plus_KBB", ["xwhip_statcast", "kbb"]),
    ("WHIP_plus_xWHIP_lgBABIP_plus_KBB", ["whip", "xwhip_lgbabip", "kbb"]),
    ("Kpct_plus_BBpct_plus_xWHIP_lgBABIP", ["k_pct", "bb_pct", "xwhip_lgbabip"]),
    ("KBB_plus_xWHIP_lgBABIP_plus_logTBF", ["kbb", "xwhip_lgbabip", "log_current_tbf"]),
    ("Kpct_plus_BBpct_plus_xWHIP_lgBABIP_plus_logTBF", ["k_pct", "bb_pct", "xwhip_lgbabip", "log_current_tbf"]),
]


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    raw: Path
    processed: Path
    results_base: Path
    plots_base: Path
    run_id: str
    results: Path
    plots: Path

    @classmethod
    def from_root(cls, root: Path, run_id: str = "adhoc", raw_dir: str | None = None) -> "ProjectPaths":
        results_base = root / "results"
        plots_base = root / "plots"
        raw = Path(raw_dir).expanduser().resolve() if raw_dir else root / "data" / "raw"
        return cls(
            root=root,
            raw=raw,
            processed=root / "data" / "processed",
            results_base=results_base,
            plots_base=plots_base,
            run_id=run_id,
            results=results_base / run_id,
            plots=plots_base / run_id,
        )

    def ensure(self) -> None:
        for path in [self.raw, self.processed, self.results_base, self.plots_base, self.results, self.plots]:
            path.mkdir(parents=True, exist_ok=True)

    def update_latest_pointer(self) -> None:
        for base in [self.results_base, self.plots_base]:
            pointer = base / "latest_run.txt"
            pointer.write_text(f"{self.run_id}\n", encoding="utf-8")
            latest = base / "latest"
            try:
                if latest.is_symlink() or latest.exists():
                    latest.unlink()
                latest.symlink_to(self.run_id, target_is_directory=True)
            except OSError:
                pass


def safe_divide(numerator: pd.Series | float, denominator: pd.Series | float) -> pd.Series | float:
    if isinstance(denominator, pd.Series):
        return numerator / denominator.replace({0: np.nan})
    if denominator == 0 or pd.isna(denominator):
        return np.nan
    return numerator / denominator


def parse_baseball_ip(value: object) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if not text:
        return np.nan
    try:
        numeric = float(text)
    except ValueError:
        return np.nan
    whole = math.floor(numeric)
    frac_digit = int(round((numeric - whole) * 10))
    if frac_digit in {1, 2}:
        return whole + frac_digit / 3.0
    return numeric


def normalize_percent(series: pd.Series) -> pd.Series:
    if series.dtype == object or str(series.dtype).startswith("string"):
        cleaned = series.astype(str).str.replace("%", "", regex=False).str.strip()
        numeric = pd.to_numeric(cleaned, errors="coerce")
    else:
        numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().median() > 1.0:
        numeric = numeric / 100.0
    return numeric


def first_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lower_map = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
        found = lower_map.get(candidate.lower())
        if found is not None:
            return found
    return None


def numeric_column(frame: pd.DataFrame, candidates: Iterable[str], default: float = np.nan) -> pd.Series:
    column = first_column(frame, candidates)
    if column is None:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def text_column(frame: pd.DataFrame, candidates: Iterable[str], default: str = "") -> pd.Series:
    column = first_column(frame, candidates)
    if column is None:
        return pd.Series(default, index=frame.index, dtype="string")
    return frame[column].astype("string")


def call_pitching_stats(season: int) -> pd.DataFrame:
    from pybaseball import pitching_stats

    call_patterns = [
        lambda: pitching_stats(season, season, qual=0, ind=1),
        lambda: pitching_stats(season, season, qual=0),
        lambda: pitching_stats(season, season),
    ]
    last_exc: Exception | None = None
    for call in call_patterns:
        try:
            frame = call()
            if frame is not None and not frame.empty:
                return frame
        except Exception as exc:  # pragma: no cover - depends on pybaseball version
            last_exc = exc
    raise RuntimeError(f"Could not fetch FanGraphs pitching stats for {season}: {last_exc}")


def fetch_mlb_stats_pitching(season: int) -> pd.DataFrame:
    params = urllib.parse.urlencode(
        {
            "stats": "season",
            "group": "pitching",
            "playerPool": "ALL",
            "season": season,
            "sportIds": 1,
            "hydrate": "person",
            "limit": 5000,
        }
    )
    url = f"https://statsapi.mlb.com/api/v1/stats?{params}"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = []
    for split in payload.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        player = split.get("player", {})
        team = split.get("team", {})
        player_id = player.get("id")
        if player_id is None:
            continue
        rows.append(
            {
                "Name": player.get("fullName", ""),
                "IDfg": player_id,
                "MLBAMID": player_id,
                "Team": team.get("name", ""),
                "G": stat.get("gamesPitched", stat.get("gamesPlayed")),
                "GS": stat.get("gamesStarted"),
                "IP": stat.get("inningsPitched"),
                "TBF": stat.get("battersFaced"),
                "H": stat.get("hits"),
                "HR": stat.get("homeRuns"),
                "ER": stat.get("earnedRuns"),
                "ERA": stat.get("era"),
                "BB": stat.get("baseOnBalls"),
                "IBB": stat.get("intentionalWalks"),
                "SO": stat.get("strikeOuts"),
                "AB": stat.get("atBats"),
                "SF": stat.get("sacFlies"),
                "BBE": np.nan,
                "WHIP": stat.get("whip"),
                "source": "mlb_stats_api",
            }
        )
    if not rows:
        raise RuntimeError(f"MLB Stats API returned no pitching rows for {season}")
    return pd.DataFrame(rows)


def cache_fangraphs_pitching(paths: ProjectPaths, seasons: list[int], force: bool, season_source: str = "auto") -> None:
    for season in seasons:
        out = paths.raw / f"fangraphs_pitching_{season}.csv"
        if out.exists() and not force:
            continue
        if season_source == "mlb":
            frame = fetch_mlb_stats_pitching(season)
        else:
            try:
                frame = call_pitching_stats(season)
                frame["source"] = "fangraphs"
            except Exception as exc:
                if season_source == "fangraphs":
                    raise
                print(f"FanGraphs fetch failed for {season}; falling back to MLB Stats API: {exc}")
                frame = fetch_mlb_stats_pitching(season)
        frame.to_csv(out, index=False)


def normalize_fangraphs_pitching(frame: pd.DataFrame, season: int) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    out["season"] = season
    out["player_name"] = text_column(frame, ["Name", "PlayerName", "player_name"])
    out["idfg"] = numeric_column(frame, ["IDfg", "playerid", "IDfg+", "fangraphs_id"])
    out["mlbam_id"] = numeric_column(frame, ["MLBAMID", "mlbam_id", "key_mlbam", "xMLBAMID"])
    out["team"] = text_column(frame, ["Team"])
    out["g"] = numeric_column(frame, ["G"])
    out["gs"] = numeric_column(frame, ["GS"])
    out["ip"] = text_column(frame, ["IP"]).map(parse_baseball_ip)
    out["tbf"] = numeric_column(frame, ["TBF", "BF"])
    out["h"] = numeric_column(frame, ["H"])
    out["hr"] = numeric_column(frame, ["HR"])
    out["er"] = numeric_column(frame, ["ER", "earnedRuns", "EarnedRuns"])
    out["bb"] = numeric_column(frame, ["BB"])
    out["ibb"] = numeric_column(frame, ["IBB", "intentional_walks", "iBB"], default=0.0)
    out["k"] = numeric_column(frame, ["SO", "K"])
    out["ab"] = numeric_column(frame, ["AB"])
    out["sf"] = numeric_column(frame, ["SF"])
    out["source_bbe"] = numeric_column(frame, ["BBE", "Batted Balls", "BattedBalls"])
    out["source_whip"] = numeric_column(frame, ["WHIP"])
    out["source_era"] = numeric_column(frame, ["ERA"])
    out["source_babip"] = normalize_percent(frame[first_column(frame, ["BABIP"])] if first_column(frame, ["BABIP"]) else pd.Series(np.nan, index=frame.index))
    out["source_k_pct"] = normalize_percent(frame[first_column(frame, ["K%", "K_pct"])] if first_column(frame, ["K%", "K_pct"]) else pd.Series(np.nan, index=frame.index))
    out["source_bb_pct"] = normalize_percent(frame[first_column(frame, ["BB%", "BB_pct"])] if first_column(frame, ["BB%", "BB_pct"]) else pd.Series(np.nan, index=frame.index))
    out = out.dropna(subset=["idfg", "ip", "tbf"], how="all").copy()
    return add_derived_metrics(aggregate_player_seasons(out))


def aggregate_player_seasons(frame: pd.DataFrame) -> pd.DataFrame:
    key = "idfg" if frame["idfg"].notna().any() else "player_name"
    count_cols = ["g", "gs", "ip", "tbf", "h", "hr", "er", "bb", "ibb", "k", "ab", "sf"]
    source_metric_cols = ["source_whip", "source_era", "source_babip", "source_k_pct", "source_bb_pct", "source_bbe"]
    grouped_rows = []
    for _, group in frame.groupby(["season", key], dropna=False):
        row = {
            "season": group["season"].iloc[0],
            key: group[key].iloc[0],
            "player_name": group["player_name"].dropna().iloc[-1] if group["player_name"].notna().any() else "",
            "idfg": group["idfg"].dropna().iloc[0] if group["idfg"].notna().any() else np.nan,
            "mlbam_id": group["mlbam_id"].dropna().iloc[0] if group["mlbam_id"].notna().any() else np.nan,
            "team": "TOT" if len(group) > 1 else group["team"].iloc[0],
            "source_row_count": len(group),
            "source_teams": ",".join(sorted(group["team"].dropna().astype(str).unique())),
        }
        for column in count_cols:
            row[column] = pd.to_numeric(group[column], errors="coerce").sum(min_count=1)
        for column in source_metric_cols:
            if len(group) == 1:
                row[column] = group[column].iloc[0]
            else:
                row[column] = np.nan
        grouped_rows.append(row)
    return pd.DataFrame(grouped_rows)


def load_fangraphs_pitching(paths: ProjectPaths, seasons: list[int]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        path = paths.raw / f"fangraphs_pitching_{season}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run with --fetch first.")
        frames.append(normalize_fangraphs_pitching(pd.read_csv(path), season))
    return pd.concat(frames, ignore_index=True)


def season_dates(season: int) -> tuple[str, str]:
    return f"{season}-03-01", f"{season}-11-30"


def iter_date_chunks(start: str, end: str, chunk_days: int) -> Iterable[tuple[str, str]]:
    current = datetime.strptime(start, "%Y-%m-%d").date()
    stop = datetime.strptime(end, "%Y-%m-%d").date()
    while current <= stop:
        chunk_end = min(current + timedelta(days=chunk_days - 1), stop)
        yield current.isoformat(), chunk_end.isoformat()
        current = chunk_end + timedelta(days=1)


def cache_statcast(paths: ProjectPaths, seasons: list[int], force: bool, chunk_days: int) -> None:
    from pybaseball import statcast

    for season in seasons:
        start, end = season_dates(season)
        for chunk_start, chunk_end in iter_date_chunks(start, end, chunk_days):
            out = paths.raw / f"statcast_{season}_{chunk_start}_{chunk_end}.csv.gz"
            if out.exists() and not force:
                continue
            frame = statcast(chunk_start, chunk_end, verbose=False, parallel=True)
            frame.to_csv(out, index=False, compression="gzip")


def load_statcast(paths: ProjectPaths, seasons: list[int]) -> pd.DataFrame:
    frames = []
    needed = [
        "game_date",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher",
        "player_name",
        "events",
        "description",
        "type",
        "bb_type",
        "estimated_ba_using_speedangle",
        "inning",
        "outs_when_up",
        "game_type",
    ]
    for season in seasons:
        pattern = f"statcast_{season}_*.csv.gz"
        files = sorted(paths.raw.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No Statcast cache files for {season} under {paths.raw}")
        for path in files:
            frames.append(pd.read_csv(path, usecols=lambda column: column in needed, low_memory=False))
    if not frames:
        return pd.DataFrame(columns=needed + ["season"])
    frame = pd.concat(frames, ignore_index=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce")
    frame["season"] = frame["game_date"].dt.year
    for column in ["game_pk", "at_bat_number", "pitch_number", "pitcher", "inning", "outs_when_up"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["events"] = frame["events"].astype("string")
    frame["description"] = frame["description"].astype("string")
    if "game_type" in frame.columns:
        frame = frame[frame["game_type"].fillna("R").astype(str).eq("R")].copy()
    return frame


def terminal_pas(statcast_frame: pd.DataFrame) -> pd.DataFrame:
    frame = statcast_frame.copy()
    events = frame["events"].fillna("").astype(str).str.strip()
    frame = frame[events.ne("")].copy()
    frame = frame.dropna(subset=["pitcher", "game_pk", "at_bat_number", "game_date"])
    frame = frame.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])
    frame = frame.drop_duplicates(["game_pk", "at_bat_number", "pitcher"], keep="last")
    return add_pa_flags(frame)


def add_pa_flags(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    events = out["events"].fillna("").astype(str)
    descriptions = out["description"].fillna("").astype(str)
    out["_tbf"] = 1
    out["_k"] = events.isin(K_EVENTS).astype(int)
    out["_bb"] = events.isin(BB_EVENTS).astype(int)
    out["_ibb"] = events.eq("intent_walk").astype(int)
    out["_h"] = events.isin(HIT_EVENTS).astype(int)
    out["_hr"] = events.isin(HR_EVENTS).astype(int)
    out["_sf"] = events.isin(SF_EVENTS).astype(int)
    out["_ab"] = (~events.isin(NON_AB_EVENTS)).astype(int)
    out["_outs"] = events.map(OUTS_BY_EVENT).fillna(0).astype(int)
    out["_bip"] = (out["_ab"] - out["_k"] - out["_hr"] + out["_sf"]).clip(lower=0)
    xba = pd.to_numeric(out.get("estimated_ba_using_speedangle"), errors="coerce")
    bbe = descriptions.isin(BBE_DESCRIPTIONS) | out.get("bb_type", pd.Series("", index=out.index)).notna() | xba.notna()
    out["_bbe"] = bbe.astype(int)
    out["_xba_count"] = (bbe & xba.notna()).astype(int)
    out["_xba_sum"] = xba.where(bbe, np.nan).fillna(0.0)
    return out


def aggregate_pa_frame(frame: pd.DataFrame, group_cols: list[str], lg_babip: float | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_cols)
    grouped = frame.groupby(group_cols, dropna=False).agg(
        player_name=("player_name", "last"),
        tbf=("_tbf", "sum"),
        k=("_k", "sum"),
        bb=("_bb", "sum"),
        ibb=("_ibb", "sum"),
        h=("_h", "sum"),
        hr=("_hr", "sum"),
        ab=("_ab", "sum"),
        sf=("_sf", "sum"),
        outs=("_outs", "sum"),
        bbe=("_bbe", "sum"),
        xba_count=("_xba_count", "sum"),
        xba_sum=("_xba_sum", "sum"),
        games=("game_pk", "nunique"),
    ).reset_index()
    grouped["ip"] = grouped["outs"] / 3.0
    grouped["gs"] = estimate_games_started(frame, group_cols)
    return add_derived_metrics(grouped, lg_babip=lg_babip)


def estimate_games_started(frame: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    starter_like = frame[
        (pd.to_numeric(frame.get("inning"), errors="coerce") == 1)
        & (pd.to_numeric(frame.get("outs_when_up"), errors="coerce") == 0)
    ]
    if starter_like.empty:
        grouped = frame.groupby(group_cols, dropna=False).size().reset_index(name="gs")
        grouped["gs"] = 0
    else:
        grouped = starter_like.groupby(group_cols, dropna=False)["game_pk"].nunique().reset_index(name="gs")
    index = frame.groupby(group_cols, dropna=False).size().reset_index(name="_n")[group_cols]
    merged = index.merge(grouped, on=group_cols, how="left")
    return merged["gs"].fillna(0).astype(float)


def add_derived_metrics(frame: pd.DataFrame, lg_babip: float | None = None) -> pd.DataFrame:
    out = frame.copy()
    for column in ["tbf", "k", "bb", "ibb", "h", "hr", "er", "ab", "sf", "ip", "g", "gs"]:
        if column not in out.columns:
            out[column] = 0.0 if column == "ibb" else np.nan
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["bip"] = (out["ab"] - out["k"] - out["hr"] + out["sf"]).clip(lower=0)
    out["ubb"] = (out["bb"] - out["ibb"].fillna(0)).clip(lower=0)
    out["k_pct"] = safe_divide(out["k"], out["tbf"])
    out["bb_pct"] = safe_divide(out["bb"], out["tbf"])
    out["ubb_pct"] = safe_divide(out["ubb"], out["tbf"])
    out["kbb"] = out["k_pct"] - out["bb_pct"]
    out["k_ubb"] = out["k_pct"] - out["ubb_pct"]
    out["whip"] = safe_divide(out["bb"] + out["h"], out["ip"])
    out["hr9"] = safe_divide(9.0 * out["hr"], out["ip"])
    out["era"] = safe_divide(9.0 * out["er"], out["ip"])
    out["babip"] = safe_divide(out["h"] - out["hr"], out["bip"])
    out["log_current_tbf"] = np.log1p(out["tbf"])
    if lg_babip is None:
        lg_babip = safe_divide((out["h"] - out["hr"]).sum(), out["bip"].sum())
    out["lg_babip"] = lg_babip
    out["xhits_lgbabip"] = out["hr"] + out["lg_babip"] * out["bip"]
    out["xwhip_lgbabip"] = safe_divide(out["bb"] + out["xhits_lgbabip"], out["ip"])
    for c_value in C_GRID:
        r = safe_divide(out["bip"], out["bip"] + c_value)
        xb = out["lg_babip"] + r * (out["babip"] - out["lg_babip"])
        out[f"xwhip_regbabip_C{c_value}"] = safe_divide(out["bb"] + out["hr"] + xb * out["bip"], out["ip"])
    if "xba_sum" in out.columns:
        out["xhits_statcast"] = out["xba_sum"]
        out["xwhip_statcast"] = safe_divide(out["bb"] + out["xba_sum"], out["ip"])
        out["xba_coverage"] = safe_divide(out.get("xba_count", 0), out.get("bbe", 0))
        out["xwhip_statcast_cov90"] = out["xwhip_statcast"].where(out["xba_coverage"] >= 0.90)
        out["xwhip_statcast_cov95"] = out["xwhip_statcast"].where(out["xba_coverage"] >= 0.95)
    else:
        out["xhits_statcast"] = np.nan
        out["xwhip_statcast"] = np.nan
        out["xba_coverage"] = np.nan
        out["xwhip_statcast_cov90"] = np.nan
        out["xwhip_statcast_cov95"] = np.nan
    out["wsi_raw"] = safe_divide(100.0 * out["kbb"], out["whip"])
    out["wsi_xlgbabip"] = safe_divide(100.0 * out["kbb"], out["xwhip_lgbabip"])
    out["wsi_ubb_xlgbabip"] = safe_divide(100.0 * out["k_ubb"], out["xwhip_lgbabip"])
    for c_value in C_GRID:
        out[f"wsi_xreg_C{c_value}"] = safe_divide(100.0 * out["kbb"], out[f"xwhip_regbabip_C{c_value}"])
    out["wsi_xstatcast"] = safe_divide(100.0 * out["kbb"], out["xwhip_statcast"])
    out["role"] = np.where(safe_divide(out["gs"], out["g"]).fillna(0) >= 0.5, "starter", "reliever")
    return out.replace([np.inf, -np.inf], np.nan)


def write_data_checks(paths: ProjectPaths, pitching: pd.DataFrame) -> None:
    checks = []
    tolerances = {"whip": 0.01, "babip": 0.005, "k_pct": 0.002, "bb_pct": 0.002}
    for metric, source in [
        ("whip", "source_whip"),
        ("babip", "source_babip"),
        ("k_pct", "source_k_pct"),
        ("bb_pct", "source_bb_pct"),
    ]:
        if source not in pitching.columns:
            continue
        diff = (pitching[metric] - pitching[source]).abs()
        flagged = pitching[diff > tolerances[metric]].copy()
        if flagged.empty:
            continue
        flagged["metric"] = metric
        flagged["recalculated"] = flagged[metric]
        flagged["source"] = flagged[source]
        flagged["abs_diff"] = diff[diff > tolerances[metric]]
        checks.append(flagged[["season", "player_name", "idfg", "metric", "recalculated", "source", "abs_diff"]])
    if checks:
        out = pd.concat(checks, ignore_index=True)
    else:
        out = pd.DataFrame(columns=["season", "player_name", "idfg", "metric", "recalculated", "source", "abs_diff"])
    out.to_csv(paths.results / "data_checks.csv", index=False)


def map_statcast_to_fangraphs(statcast_features: pd.DataFrame, pitching: pd.DataFrame) -> pd.DataFrame:
    if statcast_features.empty:
        return pitching
    merged = pitching.copy()
    sc = statcast_features[["season", "pitcher", "xwhip_statcast", "xba_coverage", "xwhip_statcast_cov90", "xwhip_statcast_cov95"]].copy()
    sc = sc.rename(columns={"pitcher": "mlbam_id"})
    if merged["mlbam_id"].notna().any():
        return merged.merge(sc, on=["season", "mlbam_id"], how="left", suffixes=("", "_sc")).pipe(coalesce_statcast_columns)

    try:
        from pybaseball import playerid_reverse_lookup

        ids = sorted(sc["mlbam_id"].dropna().astype(int).unique().tolist())
        if ids:
            lookup = playerid_reverse_lookup(ids, key_type="mlbam")
            id_map = lookup.rename(columns={"key_mlbam": "mlbam_id", "key_fangraphs": "idfg"})
            sc = sc.merge(id_map[["mlbam_id", "idfg"]], on="mlbam_id", how="left")
            return merged.merge(sc.drop(columns=["mlbam_id"]), on=["season", "idfg"], how="left", suffixes=("", "_sc")).pipe(coalesce_statcast_columns)
    except Exception:
        pass
    return merged


def coalesce_statcast_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ["xwhip_statcast", "xba_coverage", "xwhip_statcast_cov90", "xwhip_statcast_cov95"]:
        alt = f"{column}_sc"
        if alt in out.columns:
            out[column] = out[column].combine_first(out[alt])
            out = out.drop(columns=[alt])
    out["wsi_xstatcast"] = safe_divide(100.0 * out["kbb"], out["xwhip_statcast"])
    return out


def write_statcast_reconciliation(paths: ProjectPaths, pitching: pd.DataFrame, statcast_features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    columns = [
        "season",
        "player_name",
        "idfg",
        "mlbam_id",
        "source_k",
        "statcast_k",
        "diff_k",
        "source_bb",
        "statcast_bb",
        "diff_bb",
        "source_h",
        "statcast_h",
        "diff_h",
        "source_hr",
        "statcast_hr",
        "diff_hr",
        "source_bbe",
        "statcast_bbe",
        "diff_bbe",
        "large_discrepancy",
    ]
    if statcast_features.empty:
        out = pd.DataFrame(columns=columns)
        out.to_csv(paths.results / "statcast_reconciliation.csv", index=False)
        return out, {"available": False, "large_discrepancy_count": 0}
    sc = statcast_features[["season", "pitcher", "k", "bb", "h", "hr", "bbe"]].rename(
        columns={"pitcher": "mlbam_id", "k": "statcast_k", "bb": "statcast_bb", "h": "statcast_h", "hr": "statcast_hr", "bbe": "statcast_bbe"}
    )
    source = pitching[["season", "player_name", "idfg", "mlbam_id", "k", "bb", "h", "hr", "source_bbe"]].rename(
        columns={"k": "source_k", "bb": "source_bb", "h": "source_h", "hr": "source_hr"}
    )
    if source["mlbam_id"].notna().any():
        out = source.merge(sc, on=["season", "mlbam_id"], how="left")
    else:
        out = source.copy()
        for column in ["statcast_k", "statcast_bb", "statcast_h", "statcast_hr", "statcast_bbe"]:
            out[column] = np.nan
    for metric in ["k", "bb", "h", "hr", "bbe"]:
        source_col = f"source_{metric}"
        statcast_col = f"statcast_{metric}"
        diff_col = f"diff_{metric}"
        if source_col not in out.columns:
            out[source_col] = np.nan
        out[diff_col] = pd.to_numeric(out[statcast_col], errors="coerce") - pd.to_numeric(out[source_col], errors="coerce")
    thresholds = {"k": 2, "bb": 2, "h": 2, "hr": 1, "bbe": 5}
    flags = []
    for metric, threshold in thresholds.items():
        source_col = f"source_{metric}"
        if out[source_col].notna().any():
            flags.append(out[f"diff_{metric}"].abs() > threshold)
    out["large_discrepancy"] = np.logical_or.reduce(flags) if flags else False
    out = out[columns]
    out.to_csv(paths.results / "statcast_reconciliation.csv", index=False)
    summary = {
        "available": True,
        "rows": int(len(out)),
        "matched_rows": int(out["statcast_k"].notna().sum()),
        "large_discrepancy_count": int(out["large_discrepancy"].sum()),
    }
    return out, summary


def write_result_sanity_checks(paths: ProjectPaths, frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, object]]:
    rows: list[dict[str, object]] = []

    def add_check(name: str, frame_name: str, count: int, severity: str = "error") -> None:
        rows.append({"check": name, "frame": frame_name, "bad_rows": int(count), "severity": severity})

    plausible = {
        "k_pct": (-0.001, 0.60),
        "bb_pct": (-0.001, 0.30),
        "ubb_pct": (-0.001, 0.30),
        "babip": (0.05, 0.55),
        "whip": (0.30, 3.50),
        "xwhip_lgbabip": (0.30, 3.50),
        "xwhip_statcast": (0.20, 4.00),
        "kbb": (-0.25, 0.55),
    }
    for frame_name, frame in frames.items():
        if frame.empty:
            continue
        wsi_cols = [column for column in frame.columns if column.startswith("wsi")]
        for column in wsi_cols:
            add_check(f"{column}_finite", frame_name, int(np.isinf(pd.to_numeric(frame[column], errors="coerce")).sum()))
        for column, (low, high) in plausible.items():
            if column in frame.columns:
                values = pd.to_numeric(frame[column], errors="coerce")
                eligible = pd.Series(True, index=frame.index)
                if frame_name == "pitching_features" and "ip" in frame.columns:
                    eligible = pd.to_numeric(frame["ip"], errors="coerce") >= ROLE_THRESHOLDS["reliever"][0]
                add_check(f"{column}_plausible_range", frame_name, int((((values < low) | (values > high)) & eligible).sum()))
        if "kbb" in frame.columns:
            add_check("kbb_decimal_not_percentage_points", frame_name, int((pd.to_numeric(frame["kbb"], errors="coerce").abs() > 1).sum()))
        if {"wsi_raw", "kbb", "whip"}.issubset(frame.columns):
            expected = safe_divide(100.0 * frame["kbb"], frame["whip"])
            diff = (pd.to_numeric(frame["wsi_raw"], errors="coerce") - expected).abs()
            add_check("wsi_raw_formula_100_decimal_kbb_over_denominator", frame_name, int((diff > 1e-9).sum()))
        if {"season", "idfg"}.issubset(frame.columns):
            keyed = frame.dropna(subset=["idfg"])
            add_check("one_row_per_pitcher_season_after_trade_aggregation", frame_name, int(keyed.duplicated(["season", "idfg"]).sum()))
        if "source_row_count" in frame.columns:
            add_check("traded_players_aggregated_to_player_season", frame_name, int((pd.to_numeric(frame["source_row_count"], errors="coerce") > 1).sum()), severity="info")

    out = pd.DataFrame(rows, columns=["check", "frame", "bad_rows", "severity"])
    out.to_csv(paths.results / "sanity_checks.csv", index=False)
    summary = {
        "error_count": int(out.loc[out["severity"].eq("error"), "bad_rows"].sum()) if not out.empty else 0,
        "info_count": int(out.loc[out["severity"].eq("info"), "bad_rows"].sum()) if not out.empty else 0,
        "checks": int(len(out)),
    }
    return out, summary


def make_season_dataset(pitching: pd.DataFrame, exclude_2020: bool) -> pd.DataFrame:
    current = pitching[pitching["season"].between(2015, 2024)].copy()
    future = pitching[pitching["season"].between(2016, 2025)].copy()
    if exclude_2020:
        current = current[current["season"] != 2020]
        future = future[future["season"] != 2020]
    current["future_season"] = current["season"] + 1
    key = "idfg" if current["idfg"].notna().any() else "player_name"
    future_cols = [key, "season", "whip", "ip", "tbf"]
    future = future[future_cols].rename(columns={"season": "future_season", "whip": "future_whip", "ip": "future_ip", "tbf": "future_tbf"})
    data = current.merge(future, on=[key, "future_season"], how="inner")
    data["scenario"] = "season_to_next"
    data["period"] = data["season"]
    data["pitcher_season"] = data[key].astype(str) + "-" + data["season"].astype(str)
    data["exclude_2020"] = exclude_2020
    return data


def make_inseason_datasets(statcast_pas: pd.DataFrame, exclude_2020: bool) -> pd.DataFrame:
    rows = []
    frame = statcast_pas.copy()
    if exclude_2020:
        frame = frame[frame["season"] != 2020]
    for season in sorted(frame["season"].dropna().astype(int).unique()):
        season_frame = frame[frame["season"] == season]
        for cutoff in CUTOFFS:
            cutoff_date = pd.Timestamp(f"{season}-{cutoff}")
            current = season_frame[season_frame["game_date"] <= cutoff_date].copy()
            future = season_frame[season_frame["game_date"] > cutoff_date].copy()
            if current.empty or future.empty:
                continue
            lg_babip = safe_divide((current["_h"] - current["_hr"]).sum(), current["_bip"].sum())
            current_agg = aggregate_pa_frame(current, ["season", "pitcher"], lg_babip=lg_babip)
            future_agg = aggregate_pa_frame(future, ["season", "pitcher"], lg_babip=lg_babip)
            future_agg = future_agg.rename(columns={"whip": "future_whip", "ip": "future_ip", "tbf": "future_tbf"})
            data = current_agg.merge(future_agg[["season", "pitcher", "future_whip", "future_ip", "future_tbf"]], on=["season", "pitcher"], how="inner")
            data["scenario"] = f"inseason_{cutoff.replace('-', '')}"
            data["period"] = season * 10000 + int(cutoff.replace("-", ""))
            data["pitcher_season"] = data["pitcher"].astype(str) + "-" + data["season"].astype(str)
            data["exclude_2020"] = exclude_2020
            rows.append(data)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def make_rolling_datasets(statcast_pas: pd.DataFrame, exclude_2020: bool) -> pd.DataFrame:
    frame = statcast_pas.copy()
    if exclude_2020:
        frame = frame[frame["season"] != 2020]
    rows = []
    frame = frame.sort_values(["pitcher", "season", "game_date", "game_pk", "at_bat_number"])
    frame["_pa_index"] = frame.groupby(["pitcher", "season"]).cumcount() + 1
    for label, current_tbf, future_tbf in ROLLING_WINDOWS:
        for (season, pitcher), group in frame.groupby(["season", "pitcher"], dropna=False):
            feature = group[group["_pa_index"] <= current_tbf]
            if future_tbf is None:
                future = group[group["_pa_index"] > current_tbf]
            else:
                future = group[(group["_pa_index"] > current_tbf) & (group["_pa_index"] <= current_tbf + future_tbf)]
            if len(feature) < current_tbf or future.empty:
                continue
            lg_babip = safe_divide((feature["_h"] - feature["_hr"]).sum(), feature["_bip"].sum())
            current_agg = aggregate_pa_frame(feature, ["season", "pitcher"], lg_babip=lg_babip)
            future_agg = aggregate_pa_frame(future, ["season", "pitcher"], lg_babip=lg_babip)
            data = current_agg.merge(
                future_agg[["season", "pitcher", "whip", "ip", "tbf"]].rename(columns={"whip": "future_whip", "ip": "future_ip", "tbf": "future_tbf"}),
                on=["season", "pitcher"],
                how="inner",
            )
            data["scenario"] = f"rolling_{label}"
            data["period"] = int(season)
            data["pitcher_season"] = data["pitcher"].astype(str) + "-" + data["season"].astype(str)
            data["exclude_2020"] = exclude_2020
            rows.append(data)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def weighted_lstsq_predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str], weight_col: str) -> np.ndarray:
    needed = features + ["future_whip", weight_col]
    train = train.dropna(subset=needed)
    test = test.dropna(subset=features)
    if train.empty or test.empty:
        return np.array([])
    x_train = np.column_stack([np.ones(len(train))] + [train[column].to_numpy(dtype=float) for column in features])
    y_train = train["future_whip"].to_numpy(dtype=float)
    weights = np.sqrt(train[weight_col].fillna(1.0).clip(lower=0.0).to_numpy(dtype=float))
    xw = x_train * weights[:, None]
    yw = y_train * weights
    beta = np.linalg.lstsq(xw, yw, rcond=None)[0]
    x_test = np.column_stack([np.ones(len(test))] + [test[column].to_numpy(dtype=float) for column in features])
    return x_test @ beta


def metric_summary(y_true: np.ndarray, y_pred: np.ndarray, weights: np.ndarray, baseline: float) -> dict[str, float]:
    if len(y_true) < 3:
        return {}
    err = y_pred - y_true
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1.0)
    sse = np.sum(weights * err * err)
    baseline_sse = np.sum(weights * (baseline - y_true) ** 2)
    return {
        "pearson": corr(y_pred, y_true, "pearson"),
        "spearman": corr(y_pred, y_true, "spearman"),
        "kendall": corr(y_pred, y_true, "kendall"),
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "weighted_rmse": float(np.sqrt(sse / np.sum(weights))),
        "weighted_mae": float(np.sum(weights * np.abs(err)) / np.sum(weights)),
        "oos_r2_vs_lg_avg": float(1.0 - sse / baseline_sse) if baseline_sse > 0 else np.nan,
    }


def corr(a: np.ndarray, b: np.ndarray, method: str) -> float:
    data = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(data) < 3 or data["a"].nunique() < 2 or data["b"].nunique() < 2:
        return np.nan
    return float(data["a"].corr(data["b"], method=method))


def choose_best_feature(
    train: pd.DataFrame,
    candidates: list[tuple[str, dict[str, float | int | str]]],
    weight_col: str,
) -> tuple[str | None, dict[str, float | int | str], float]:
    best_feature = None
    best_params: dict[str, float | int | str] = {}
    best_rmse = np.inf
    for feature, params in candidates:
        cols = [feature, "future_whip", weight_col]
        subset = train.dropna(subset=cols)
        if len(subset) < 20 or subset[feature].nunique() < 2:
            continue
        pred = weighted_lstsq_predict(subset, subset, [feature], weight_col)
        if len(pred) != len(subset):
            continue
        weights = subset[weight_col].fillna(1.0).to_numpy(dtype=float)
        rmse = metric_summary(subset["future_whip"].to_numpy(dtype=float), pred, weights, subset["future_whip"].mean()).get("weighted_rmse", np.inf)
        if rmse < best_rmse:
            best_feature = feature
            best_params = params
            best_rmse = rmse
    return best_feature, best_params, best_rmse


def one_feature_train_rmse(feature: pd.Series, target: pd.Series, weights: pd.Series) -> float:
    data = pd.DataFrame({"feature": feature, "target": target, "weights": weights}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 20 or data["feature"].nunique() < 2:
        return np.inf
    x = np.column_stack([np.ones(len(data)), data["feature"].to_numpy(dtype=float)])
    y = data["target"].to_numpy(dtype=float)
    w = np.sqrt(data["weights"].fillna(1.0).clip(lower=0).to_numpy(dtype=float))
    beta = np.linalg.lstsq(x * w[:, None], y * w, rcond=None)[0]
    pred = x @ beta
    return metric_summary(y, pred, data["weights"].to_numpy(dtype=float), float(y.mean())).get("weighted_rmse", np.inf)


def choose_best_generated_feature(
    train: pd.DataFrame,
    candidates: Iterable[tuple[pd.Series, dict[str, float | int | str]]],
) -> tuple[dict[str, float | int | str], float]:
    best_params: dict[str, float | int | str] = {}
    best_rmse = np.inf
    batch_values: list[np.ndarray] = []
    batch_params: list[dict[str, float | int | str]] = []

    def flush() -> None:
        nonlocal best_params, best_rmse, batch_values, batch_params
        if not batch_values:
            return
        matrix = np.column_stack(batch_values).astype(float)
        scores = one_feature_matrix_rmse(matrix, train["future_whip"], train["future_ip"])
        if np.isfinite(scores).any():
            idx = int(np.nanargmin(scores))
            if scores[idx] < best_rmse:
                best_rmse = float(scores[idx])
                best_params = batch_params[idx]
        batch_values = []
        batch_params = []

    for series, params in candidates:
        batch_values.append(pd.to_numeric(series, errors="coerce").to_numpy(dtype=float))
        batch_params.append(params)
        if len(batch_values) >= 256:
            flush()
    flush()
    return best_params, best_rmse


def one_feature_matrix_rmse(matrix: np.ndarray, target: pd.Series, weights: pd.Series) -> np.ndarray:
    y = pd.to_numeric(target, errors="coerce").to_numpy(dtype=float)
    w = pd.to_numeric(weights, errors="coerce").fillna(1.0).clip(lower=0).to_numpy(dtype=float)
    finite = np.isfinite(matrix) & np.isfinite(y)[:, None] & np.isfinite(w)[:, None] & (w[:, None] > 0)
    weighted = finite * w[:, None]
    sum_w = weighted.sum(axis=0)
    enough = (finite.sum(axis=0) >= 20) & (sum_w > 0)
    x = np.where(finite, matrix, 0.0)
    y_matrix = np.where(finite, y[:, None], 0.0)
    x_mean = np.divide((weighted * x).sum(axis=0), sum_w, out=np.full(matrix.shape[1], np.nan), where=sum_w > 0)
    y_mean = np.divide((weighted * y_matrix).sum(axis=0), sum_w, out=np.full(matrix.shape[1], np.nan), where=sum_w > 0)
    x_centered = np.where(finite, matrix - x_mean, 0.0)
    y_centered = np.where(finite, y[:, None] - y_mean, 0.0)
    var_x = (weighted * x_centered * x_centered).sum(axis=0)
    cov_xy = (weighted * x_centered * y_centered).sum(axis=0)
    beta1 = np.divide(cov_xy, var_x, out=np.full(matrix.shape[1], np.nan), where=var_x > 0)
    beta0 = y_mean - beta1 * x_mean
    pred = beta0 + beta1 * matrix
    err = np.where(finite, pred - y[:, None], 0.0)
    rmse = np.sqrt(np.divide((weighted * err * err).sum(axis=0), sum_w, out=np.full(matrix.shape[1], np.nan), where=sum_w > 0))
    rmse[~enough] = np.nan
    return rmse


def blended_wsi(frame: pd.DataFrame, c_value: int, alpha: float) -> pd.Series:
    pwhip = alpha * frame["whip"] + (1.0 - alpha) * frame[f"xwhip_regbabip_C{c_value}"]
    return safe_divide(100.0 * frame["kbb"], pwhip)


def tuned_wsi(frame: pd.DataFrame, c_value: int, alpha: float, lam: float, gamma: float) -> pd.Series:
    pwhip = alpha * frame["whip"] + (1.0 - alpha) * frame[f"xwhip_regbabip_C{c_value}"]
    numerator = 100.0 * (frame["k_pct"] - lam * frame["bb_pct"])
    return safe_divide(numerator, pwhip.pow(gamma))


def training_league_rates(train: pd.DataFrame) -> dict[str, float]:
    return {
        "lg_whip": safe_divide((train["bb"] + train["h"]).sum(), train["ip"].sum()),
        "lg_kbb": safe_divide(train["k"].sum(), train["tbf"].sum()) - safe_divide(train["bb"].sum(), train["tbf"].sum()),
    }


def reg_whip(frame: pd.DataFrame, c_ip: int, lg_whip: float) -> pd.Series:
    shrink = safe_divide(frame["ip"], frame["ip"] + c_ip)
    return lg_whip + shrink * (frame["whip"] - lg_whip)


def reg_kbb(frame: pd.DataFrame, c_tbf: int, lg_kbb: float) -> pd.Series:
    shrink = safe_divide(frame["tbf"], frame["tbf"] + c_tbf)
    return lg_kbb + shrink * (frame["kbb"] - lg_kbb)


def reg_wsi(frame: pd.DataFrame, c_ip: int, c_tbf: int, lg_whip: float, lg_kbb: float) -> pd.Series:
    return safe_divide(100.0 * reg_kbb(frame, c_tbf, lg_kbb), reg_whip(frame, c_ip, lg_whip))


def regkbb_xwhip_wsi(frame: pd.DataFrame, c_tbf: int, lg_kbb: float, xwhip_col: str = "xwhip_lgbabip") -> pd.Series:
    return safe_divide(100.0 * reg_kbb(frame, c_tbf, lg_kbb), frame[xwhip_col])


def add_dynamic_tuned_columns(train: pd.DataFrame, test: pd.DataFrame, hyper_rows: list[dict[str, object]], context: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = train.copy()
    test = test.copy()
    lg = training_league_rates(train)
    c_candidates = [(f"xwhip_regbabip_C{c_value}", {"C": c_value}) for c_value in C_GRID]
    feature, params, score = choose_best_feature(train, c_candidates, "future_ip")
    if feature is None:
        fallback_c = C_GRID[0]
        feature, params, score = f"xwhip_regbabip_C{fallback_c}", {"C": fallback_c, "fallback": 1}, np.nan
    train["xwhip_regbabip_tuned"] = train[feature]
    test["xwhip_regbabip_tuned"] = test[feature]
    hyper_rows.append({**context, "tuned_metric": "xWHIP_regBABIP", "train_weighted_rmse": score, **params})

    wsi_candidates = [(f"wsi_xreg_C{c_value}", {"C": c_value}) for c_value in C_GRID]
    feature, params, score = choose_best_feature(train, wsi_candidates, "future_ip")
    if feature is None:
        fallback_c = C_GRID[0]
        feature, params, score = f"wsi_xreg_C{fallback_c}", {"C": fallback_c, "fallback": 1}, np.nan
    train["wsi_xreg_tuned"] = train[feature]
    test["wsi_xreg_tuned"] = test[feature]
    hyper_rows.append({**context, "tuned_metric": "WSI_xWHIPreg", "train_weighted_rmse": score, **params})

    whip_reg_candidates = ((reg_whip(train, c_ip, lg["lg_whip"]), {"C_IP": c_ip}) for c_ip in C_IP_GRID)
    params, score = choose_best_generated_feature(train, whip_reg_candidates)
    if not params:
        params, score = {"C_IP": C_IP_GRID[0], "fallback": 1}, np.nan
    train["whip_reg_tuned"] = reg_whip(train, int(params["C_IP"]), lg["lg_whip"])
    test["whip_reg_tuned"] = reg_whip(test, int(params["C_IP"]), lg["lg_whip"])
    hyper_rows.append({**context, "tuned_metric": "WHIP_reg", "train_weighted_rmse": score, "lg_whip": lg["lg_whip"], **params})

    kbb_reg_candidates = ((reg_kbb(train, c_tbf, lg["lg_kbb"]), {"C_TBF": c_tbf}) for c_tbf in C_TBF_GRID)
    params, score = choose_best_generated_feature(train, kbb_reg_candidates)
    if not params:
        params, score = {"C_TBF": C_TBF_GRID[0], "fallback": 1}, np.nan
    train["kbb_reg_tuned"] = reg_kbb(train, int(params["C_TBF"]), lg["lg_kbb"])
    test["kbb_reg_tuned"] = reg_kbb(test, int(params["C_TBF"]), lg["lg_kbb"])
    hyper_rows.append({**context, "tuned_metric": "KBB_reg", "train_weighted_rmse": score, "lg_kbb": lg["lg_kbb"], **params})

    wsi_reg_candidates = (
        (reg_wsi(train, c_ip, c_tbf, lg["lg_whip"], lg["lg_kbb"]), {"C_IP": c_ip, "C_TBF": c_tbf})
        for c_ip, c_tbf in itertools.product(C_IP_GRID, C_TBF_GRID)
    )
    params, score = choose_best_generated_feature(train, wsi_reg_candidates)
    if not params:
        params, score = {"C_IP": C_IP_GRID[0], "C_TBF": C_TBF_GRID[0], "fallback": 1}, np.nan
    train["wsi_reg_tuned"] = reg_wsi(train, int(params["C_IP"]), int(params["C_TBF"]), lg["lg_whip"], lg["lg_kbb"])
    test["wsi_reg_tuned"] = reg_wsi(test, int(params["C_IP"]), int(params["C_TBF"]), lg["lg_whip"], lg["lg_kbb"])
    hyper_rows.append({**context, "tuned_metric": "WSI_reg", "train_weighted_rmse": score, "lg_whip": lg["lg_whip"], "lg_kbb": lg["lg_kbb"], **params})

    wsi_regkbb_xwhip_candidates = (
        (regkbb_xwhip_wsi(train, c_tbf, lg["lg_kbb"], "xwhip_lgbabip"), {"C_TBF": c_tbf, "xwhip": "xwhip_lgbabip"})
        for c_tbf in C_TBF_GRID
    )
    params, score = choose_best_generated_feature(train, wsi_regkbb_xwhip_candidates)
    if not params:
        params, score = {"C_TBF": C_TBF_GRID[0], "xwhip": "xwhip_lgbabip", "fallback": 1}, np.nan
    train["wsi_xwhip_regkbb_tuned"] = regkbb_xwhip_wsi(train, int(params["C_TBF"]), lg["lg_kbb"], "xwhip_lgbabip")
    test["wsi_xwhip_regkbb_tuned"] = regkbb_xwhip_wsi(test, int(params["C_TBF"]), lg["lg_kbb"], "xwhip_lgbabip")
    hyper_rows.append({**context, "tuned_metric": "WSI_xWHIP_regKBB", "train_weighted_rmse": score, "lg_kbb": lg["lg_kbb"], **params})

    blend_candidates = (
        (blended_wsi(train, c_value, alpha), {"C": c_value, "alpha": alpha})
        for c_value, alpha in itertools.product(C_GRID, ALPHA_GRID)
    )
    params, score = choose_best_generated_feature(train, blend_candidates)
    if not params:
        params, score = {"C": 500, "alpha": 0.5, "fallback": 1}, np.nan
    train["wsi_blend_tuned"] = blended_wsi(train, int(params["C"]), float(params["alpha"]))
    test["wsi_blend_tuned"] = blended_wsi(test, int(params["C"]), float(params["alpha"]))
    hyper_rows.append({**context, "tuned_metric": "WSI_blend", "train_weighted_rmse": score, **params})

    tuned_candidates = (
        (
            tuned_wsi(train, c_value, alpha, lam, gamma),
            {"C": c_value, "alpha": alpha, "lambda": lam, "gamma": gamma},
        )
        for c_value, alpha, lam, gamma in itertools.product(C_GRID, ALPHA_GRID, LAMBDA_GRID, GAMMA_GRID)
    )
    params, score = choose_best_generated_feature(train, tuned_candidates)
    if not params:
        params, score = {"C": 500, "alpha": 0.5, "lambda": 1.0, "gamma": 1.0, "fallback": 1}, np.nan
    train["wsi_tuned"] = tuned_wsi(train, int(params["C"]), float(params["alpha"]), float(params["lambda"]), float(params["gamma"]))
    test["wsi_tuned"] = tuned_wsi(test, int(params["C"]), float(params["alpha"]), float(params["lambda"]), float(params["gamma"]))
    hyper_rows.append({**context, "tuned_metric": "WSI_tuned", "train_weighted_rmse": score, **params})
    return train, test


def all_model_specs() -> list[tuple[str, list[str]]]:
    tuned = [
        ("xWHIP_regBABIP_tuned", ["xwhip_regbabip_tuned"]),
        ("WSI_xWHIPreg_tuned", ["wsi_xreg_tuned"]),
        ("WHIP_reg_tuned", ["whip_reg_tuned"]),
        ("KBB_reg_tuned", ["kbb_reg_tuned"]),
        ("WSI_reg_tuned", ["wsi_reg_tuned"]),
        ("WSI_xWHIP_regKBB_tuned", ["wsi_xwhip_regkbb_tuned"]),
        ("WSI_blend_tuned", ["wsi_blend_tuned"]),
        ("WSI_tuned", ["wsi_tuned"]),
        ("xWHIP_regBABIP_tuned_plus_KBB", ["xwhip_regbabip_tuned", "kbb"]),
        ("KBB_reg_plus_xWHIP_lgBABIP", ["kbb_reg_tuned", "xwhip_lgbabip"]),
        ("KBB_reg_plus_xWHIP_lgBABIP_plus_logTBF", ["kbb_reg_tuned", "xwhip_lgbabip", "log_current_tbf"]),
        ("WHIP_plus_xWHIP_regBABIP_tuned_plus_KBB", ["whip", "xwhip_regbabip_tuned", "kbb"]),
        ("Kpct_plus_BBpct_plus_xWHIP_regBABIP_tuned", ["k_pct", "bb_pct", "xwhip_regbabip_tuned"]),
    ]
    return BASE_MODEL_SPECS + tuned


def filtered_split(data: pd.DataFrame, split: str) -> pd.DataFrame:
    if split == "all":
        return data.copy()
    return data[data["role"] == split].copy()


def apply_thresholds(data: pd.DataFrame, split: str) -> pd.DataFrame:
    current_min, future_min = ROLE_THRESHOLDS[split]
    return data[(data["ip"] >= current_min) & (data["future_ip"] >= future_min)].copy()


def evaluate_dataset(data: pd.DataFrame, scenario_group: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics_rows: list[dict[str, object]] = []
    prediction_rows: list[pd.DataFrame] = []
    hyper_rows: list[dict[str, object]] = []
    specs = all_model_specs()
    spec_map = dict(specs)
    if data.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    for exclude_2020, ex_data in data.groupby("exclude_2020", dropna=False):
        for scenario, scenario_data in ex_data.groupby("scenario", dropna=False):
            for split in ["all", "starter", "reliever"]:
                split_data = apply_thresholds(filtered_split(scenario_data, split), split)
                if split_data.empty:
                    continue
                periods = sorted(split_data["period"].dropna().unique().tolist())
                preds_by_model: dict[str, list[pd.DataFrame]] = {model_name: [] for model_name, _ in specs}
                for period in periods:
                    train = split_data[split_data["period"] < period].copy()
                    test = split_data[split_data["period"] == period].copy()
                    if len(train) < 30 or len(test) < 3:
                        continue
                    context = {
                        "scenario_group": scenario_group,
                        "scenario": scenario,
                        "split": split,
                        "exclude_2020": bool(exclude_2020),
                        "test_period": period,
                        "model": "period_tuning",
                    }
                    train, test = add_dynamic_tuned_columns(train, test, hyper_rows, context)
                    for model_name, model_features in specs:
                        missing = [feature for feature in model_features if feature not in train.columns]
                        if missing:
                            continue
                        fit_train = train.dropna(subset=model_features + ["future_whip", "future_ip"])
                        fit_test = test.dropna(subset=model_features + ["future_whip", "future_ip"])
                        if len(fit_train) < 30 or len(fit_test) < 3:
                            continue
                        pred = weighted_lstsq_predict(fit_train, fit_test, model_features, "future_ip")
                        if len(pred) != len(fit_test):
                            continue
                        out = fit_test[["scenario", "season", "period", "player_name", "future_whip", "future_ip", "future_tbf", "pitcher_season"]].copy()
                        out["scenario_group"] = scenario_group
                        out["split"] = split
                        out["exclude_2020"] = bool(exclude_2020)
                        out["model"] = model_name
                        out["prediction"] = pred
                        for feature in set(model_features + list(PREDICTOR_DIRECTIONS)):
                            if feature in fit_test.columns:
                                out[feature] = fit_test[feature].to_numpy()
                        preds_by_model[model_name].append(out)
                for model_name, preds in preds_by_model.items():
                    if not preds:
                        continue
                    model_features = spec_map[model_name]
                    pred_frame = pd.concat(preds, ignore_index=True)
                    y_true = pred_frame["future_whip"].to_numpy(dtype=float)
                    y_pred = pred_frame["prediction"].to_numpy(dtype=float)
                    weights = pred_frame["future_ip"].fillna(1.0).to_numpy(dtype=float)
                    baseline = weighted_average(split_data["future_whip"], split_data["future_ip"])
                    summary = metric_summary(y_true, y_pred, weights, baseline)
                    if not summary:
                        continue
                    metrics_rows.append(
                        {
                            "scenario_group": scenario_group,
                            "scenario": scenario,
                            "split": split,
                            "exclude_2020": bool(exclude_2020),
                            "model": model_name,
                            "features": "+".join(model_features),
                            "n": len(pred_frame),
                            "periods": pred_frame["period"].nunique(),
                            **summary,
                        }
                    )
                    prediction_rows.append(pred_frame)
    return (
        pd.DataFrame(metrics_rows),
        pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame(),
        pd.DataFrame(hyper_rows),
    )


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    data = pd.DataFrame({"values": values, "weights": weights}).dropna()
    if data.empty:
        return np.nan
    weights_arr = data["weights"].clip(lower=0).to_numpy(dtype=float)
    if weights_arr.sum() <= 0:
        return float(data["values"].mean())
    return float(np.average(data["values"].to_numpy(dtype=float), weights=weights_arr))


def build_deciles(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return pd.DataFrame()
    predictor_cols = [column for column in PREDICTOR_DIRECTIONS if column in predictions.columns]
    group_cols = ["scenario_group", "scenario", "split", "exclude_2020"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        base = dict(zip(group_cols, keys))
        for predictor in predictor_cols:
            values = group.dropna(subset=[predictor, "future_whip", "future_ip"]).copy()
            if len(values) < 20 or values[predictor].nunique() < 10:
                continue
            ascending = PREDICTOR_DIRECTIONS[predictor] == "low"
            values["_rank_value"] = values[predictor].rank(method="first", ascending=ascending)
            values["decile"] = pd.qcut(values["_rank_value"], 10, labels=False, duplicates="drop") + 1
            for decile, decile_frame in values.groupby("decile"):
                rows.append(
                    {
                        **base,
                        "predictor": predictor,
                        "decile": int(decile),
                        "n": len(decile_frame),
                        "avg_predictor": decile_frame[predictor].mean(),
                        "future_whip": weighted_average(decile_frame["future_whip"], decile_frame["future_ip"]),
                        "future_ip": decile_frame["future_ip"].sum(),
                    }
                )
    return pd.DataFrame(rows)


def build_luck_buckets(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty or "xwhip_lgbabip" not in predictions.columns:
        return pd.DataFrame()
    group_cols = ["scenario_group", "scenario", "split", "exclude_2020"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        data = group.dropna(subset=["whip", "xwhip_lgbabip", "future_whip", "future_ip"]).copy()
        if len(data) < 30:
            continue
        data["whip_minus_xwhip"] = data["whip"] - data["xwhip_lgbabip"]
        try:
            data["luck_bucket"] = pd.qcut(
                data["whip_minus_xwhip"],
                q=[0, 0.2, 0.4, 0.6, 0.8, 1],
                labels=["xWHIP much worse", "xWHIP worse", "neutral", "WHIP worse", "WHIP much worse"],
                duplicates="drop",
            )
        except ValueError:
            continue
        base = dict(zip(group_cols, keys))
        for bucket, bucket_frame in data.groupby("luck_bucket", observed=True):
            rows.append(
                {
                    **base,
                    "luck_bucket": str(bucket),
                    "n": len(bucket_frame),
                    "avg_whip": bucket_frame["whip"].mean(),
                    "avg_xwhip": bucket_frame["xwhip_lgbabip"].mean(),
                    "avg_whip_minus_xwhip": bucket_frame["whip_minus_xwhip"].mean(),
                    "future_whip": weighted_average(bucket_frame["future_whip"], bucket_frame["future_ip"]),
                    "future_ip": bucket_frame["future_ip"].sum(),
                }
            )
    return pd.DataFrame(rows)


def build_buy_low_sell_high(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if predictions.empty:
        return pd.DataFrame()
    score_col = "wsi_xreg_tuned" if "wsi_xreg_tuned" in predictions.columns else "wsi_xlgbabip"
    if score_col not in predictions.columns:
        return pd.DataFrame()
    group_cols = ["scenario_group", "scenario", "split", "exclude_2020"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        data = group.dropna(subset=["whip", score_col, "future_whip", "future_ip"]).copy()
        if len(data) < 30:
            continue
        whip_med = data["whip"].median()
        score_q75 = data[score_col].quantile(0.75)
        score_q25 = data[score_col].quantile(0.25)
        labels = {
            "buy_low": (data["whip"] >= whip_med) & (data[score_col] >= score_q75),
            "sell_high": (data["whip"] <= whip_med) & (data[score_col] <= score_q25),
            "neutral": ~(((data["whip"] >= whip_med) & (data[score_col] >= score_q75)) | ((data["whip"] <= whip_med) & (data[score_col] <= score_q25))),
        }
        base = dict(zip(group_cols, keys))
        for label, mask in labels.items():
            bucket = data[mask]
            if bucket.empty:
                continue
            rows.append(
                {
                    **base,
                    "bucket": label,
                    "score": score_col,
                    "n": len(bucket),
                    "avg_current_whip": bucket["whip"].mean(),
                    "avg_score": bucket[score_col].mean(),
                    "future_whip": weighted_average(bucket["future_whip"], bucket["future_ip"]),
                    "future_ip": bucket["future_ip"].sum(),
                }
            )
    return pd.DataFrame(rows)


def bootstrap_rolling(predictions: pd.DataFrame, reps: int, seed: int) -> pd.DataFrame:
    if predictions.empty or reps <= 0:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    rows = []
    group_cols = ["scenario", "split", "exclude_2020", "model"]
    rolling = predictions[predictions["scenario_group"] == "rolling"].copy()
    for keys, group in rolling.groupby(group_cols, dropna=False):
        clusters = group["pitcher_season"].dropna().unique()
        if len(clusters) < 10:
            continue
        stats = []
        for _ in range(reps):
            sampled = rng.choice(clusters, size=len(clusters), replace=True)
            sample = pd.concat([group[group["pitcher_season"] == cluster] for cluster in sampled], ignore_index=True)
            summary = metric_summary(
                sample["future_whip"].to_numpy(dtype=float),
                sample["prediction"].to_numpy(dtype=float),
                sample["future_ip"].fillna(1.0).to_numpy(dtype=float),
                weighted_average(group["future_whip"], group["future_ip"]),
            )
            if summary:
                stats.append(summary)
        if not stats:
            continue
        stat_frame = pd.DataFrame(stats)
        base = dict(zip(group_cols, keys))
        for metric in ["pearson", "rmse", "weighted_rmse", "mae", "weighted_mae", "oos_r2_vs_lg_avg"]:
            rows.append(
                {
                    **base,
                    "metric": metric,
                    "ci_low": stat_frame[metric].quantile(0.025),
                    "ci_high": stat_frame[metric].quantile(0.975),
                    "bootstrap_reps": reps,
                }
            )
    return pd.DataFrame(rows)


def make_plots(paths: ProjectPaths, predictions: pd.DataFrame, deciles: pd.DataFrame, hyper: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not predictions.empty:
        plot_data = predictions[(predictions["split"] == "all") & (~predictions["exclude_2020"])].copy()
        plot_data = plot_data.drop_duplicates(["scenario_group", "scenario", "period", "player_name", "future_whip"])
        predictors = [
            ("whip", "Current WHIP"),
            ("kbb", "K-BB%"),
            ("xwhip_lgbabip", "xWHIP lgBABIP"),
            ("wsi_raw", "WSI raw"),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)
        for ax, (column, title) in zip(axes.ravel(), predictors):
            data = plot_data.dropna(subset=[column, "future_whip"]).sample(min(2500, len(plot_data.dropna(subset=[column, "future_whip"]))), random_state=7)
            ax.scatter(data[column], data["future_whip"], s=9, alpha=0.25)
            ax.set_title(title)
            ax.set_xlabel(column)
            ax.set_ylabel("Future WHIP")
        fig.suptitle("Predictors vs Future WHIP")
        fig.savefig(paths.plots / "scatter_predictor_vs_future_whip.png", dpi=160)
        plt.close(fig)

        rank_data = plot_data.dropna(subset=["wsi_raw", "wsi_xlgbabip"]).copy()
        if not rank_data.empty:
            rank_data["raw_rank"] = rank_data.groupby(["scenario_group", "scenario", "period"])["wsi_raw"].rank(ascending=False)
            rank_data["x_rank"] = rank_data.groupby(["scenario_group", "scenario", "period"])["wsi_xlgbabip"].rank(ascending=False)
            rank_data["rank_change"] = rank_data["raw_rank"] - rank_data["x_rank"]
            fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
            ax.hist(rank_data["rank_change"].dropna(), bins=50, color="#3d6f8e", alpha=0.85)
            ax.axvline(0, color="#222222", linewidth=1)
            ax.set_title("Raw WSI vs xWSI rank change")
            ax.set_xlabel("Raw rank minus xWSI rank")
            ax.set_ylabel("Pitcher-windows")
            fig.savefig(paths.plots / "raw_vs_xwsi_rank_change.png", dpi=160)
            plt.close(fig)

    if not deciles.empty:
        decile_plot = deciles[(deciles["split"] == "all") & (~deciles["exclude_2020"]) & (deciles["predictor"].isin(["whip", "kbb", "xwhip_lgbabip", "wsi_raw", "wsi_xreg_tuned"]))]
        if not decile_plot.empty:
            fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
            for predictor, group in decile_plot.groupby("predictor"):
                averaged = group.groupby("decile", as_index=False).agg(future_whip=("future_whip", "mean"))
                ax.plot(averaged["decile"], averaged["future_whip"], marker="o", label=predictor)
            ax.set_title("Future WHIP by current predictor decile")
            ax.set_xlabel("Decile (1 is best)")
            ax.set_ylabel("Future WHIP")
            ax.legend()
            fig.savefig(paths.plots / "decile_future_whip.png", dpi=160)
            plt.close(fig)

    if not hyper.empty:
        tuned = hyper[hyper["tuned_metric"].eq("WSI_tuned")].copy()
        if not tuned.empty and {"alpha", "gamma", "train_weighted_rmse"}.issubset(tuned.columns):
            pivot = tuned.groupby(["gamma", "alpha"], as_index=False)["train_weighted_rmse"].mean().pivot(index="gamma", columns="alpha", values="train_weighted_rmse")
            fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)
            image = ax.imshow(pivot.values, aspect="auto", origin="lower", cmap="viridis_r")
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels([f"{x:.2f}" for x in pivot.columns], rotation=90)
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels([f"{x:.2f}" for x in pivot.index])
            ax.set_title("WSI_tuned train weighted RMSE by alpha/gamma")
            ax.set_xlabel("alpha")
            ax.set_ylabel("gamma")
            fig.colorbar(image, ax=ax, label="Train weighted RMSE")
            fig.savefig(paths.plots / "hyperparameter_heatmaps.png", dpi=160)
            plt.close(fig)


def write_generated_summary(paths: ProjectPaths, metrics: pd.DataFrame) -> None:
    summary_path = paths.results / "summary_answers.md"
    if metrics.empty:
        summary_path.write_text("No evaluation metrics were generated.\n", encoding="utf-8")
        return
    primary = metrics[(metrics["scenario_group"] == "season") & (metrics["split"] == "all") & (~metrics["exclude_2020"])].copy()
    if primary.empty:
        primary = metrics[(metrics["split"] == "all") & (~metrics["exclude_2020"])].copy()
    primary = primary.sort_values(["weighted_rmse", "rmse"], ascending=True)
    best = primary.iloc[0]

    def model_metric(name: str) -> pd.Series | None:
        found = primary[primary["model"].eq(name)]
        return None if found.empty else found.iloc[0]

    comparisons = [
        ("Which single stat best predicts future WHIP?", f"{best['model']} had the lowest weighted RMSE in the primary all-pitcher run."),
    ]
    pairs = [
        ("Does xWHIP beat WHIP?", "xWHIP_lgBABIP", "WHIP"),
        ("Does WSI_raw beat WHIP?", "WSI_raw", "WHIP"),
        ("Does WSI_xWHIP beat WSI_raw?", "WSI_xWHIP_lgBABIP", "WSI_raw"),
        ("Does WSI_xWHIP beat xWHIP alone?", "WSI_xWHIP_lgBABIP", "xWHIP_lgBABIP"),
        ("Does the simple two-variable model beat the quotient?", "WHIP_plus_KBB", "WSI_raw"),
    ]
    for question, left, right in pairs:
        left_row = model_metric(left)
        right_row = model_metric(right)
        if left_row is None or right_row is None:
            answer = "Not available in this run."
        else:
            winner = left if left_row["weighted_rmse"] < right_row["weighted_rmse"] else right
            answer = f"{winner} was better by weighted RMSE ({left}: {left_row['weighted_rmse']:.4f}; {right}: {right_row['weighted_rmse']:.4f})."
        comparisons.append((question, answer))
    text = ["# WHIP Predictor Findings", ""]
    for question, answer in comparisons:
        text.append(f"## {question}")
        text.append(answer)
        text.append("")
    text.append("See luck_bucket_results.csv for whether xWHIP helped most among BABIP-luck outliers.")
    summary_path.write_text("\n".join(text), encoding="utf-8")


def default_run_id(args: argparse.Namespace) -> str:
    prefix = "selftest" if args.self_test else "run"
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}"


def git_hash(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def cache_file_counts(paths: ProjectPaths, seasons: list[int]) -> dict[str, object]:
    source_counts: dict[str, int] = {}
    for season in seasons:
        path = paths.raw / f"fangraphs_pitching_{season}.csv"
        if not path.exists():
            continue
        try:
            source = pd.read_csv(path, usecols=lambda column: column == "source")
            for value, count in source["source"].fillna("unknown").value_counts().items():
                source_counts[str(value)] = source_counts.get(str(value), 0) + int(count)
        except Exception:
            source_counts["unknown"] = source_counts.get("unknown", 0) + 1
    return {
        "raw_dir": str(paths.raw),
        "processed_dir": str(paths.processed),
        "fangraphs_files": {str(season): str(paths.raw / f"fangraphs_pitching_{season}.csv") for season in seasons},
        "statcast_file_count": len(list(paths.raw.glob("statcast_*.csv.gz"))),
        "season_stat_source_row_counts": source_counts,
    }


def write_manifest(
    paths: ProjectPaths,
    args: argparse.Namespace,
    row_counts: dict[str, int],
    sanity_summary: dict[str, object],
    reconciliation_summary: dict[str, object],
) -> None:
    manifest = {
        "run_id": paths.run_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "git_hash": git_hash(paths.root.parents[1] if paths.root.name == "whip_predictors" else paths.root),
        "args": vars(args),
        "seasons": args.seasons,
        "fetch": args.fetch,
        "self_test": args.self_test,
        "include_statcast": args.include_statcast,
        "bootstrap_reps": args.bootstrap_reps,
        "fast_grid": args.fast_grid,
        "C_grid": C_GRID,
        "alpha_grid": ALPHA_GRID,
        "lambda_grid": LAMBDA_GRID,
        "gamma_grid": GAMMA_GRID,
        "C_IP_grid": C_IP_GRID,
        "C_TBF_grid": C_TBF_GRID,
        "row_counts": row_counts,
        "cache_paths": cache_file_counts(paths, args.seasons),
        "sanity_summary": sanity_summary,
        "statcast_reconciliation_summary": reconciliation_summary,
    }
    (paths.results / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_analysis(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    run_id = args.run_id or default_run_id(args)
    paths = ProjectPaths.from_root(root, run_id, args.raw_dir)
    paths.ensure()
    os.environ.setdefault("MPLCONFIGDIR", str(paths.root / ".mplconfig"))
    (paths.root / ".mplconfig").mkdir(exist_ok=True)

    seasons = args.seasons
    if args.fetch:
        cache_fangraphs_pitching(paths, seasons, args.force, args.season_source)
        if args.include_statcast:
            cache_statcast(paths, seasons, args.force, args.chunk_days)

    pitching = load_fangraphs_pitching(paths, seasons)

    statcast_pas = pd.DataFrame()
    full_sc = pd.DataFrame()
    if args.include_statcast:
        statcast = load_statcast(paths, seasons)
        statcast_pas = terminal_pas(statcast)
        full_sc = aggregate_pa_frame(statcast_pas, ["season", "pitcher"])
        pitching = map_statcast_to_fangraphs(full_sc, pitching)
        full_sc.to_csv(paths.processed / "statcast_season_pitching_features.csv", index=False)

    write_data_checks(paths, pitching)
    _, reconciliation_summary = write_statcast_reconciliation(paths, pitching, full_sc)
    pitching.to_csv(paths.processed / "fangraphs_season_pitching_features.csv", index=False)

    datasets = []
    for exclude_2020 in [False, True]:
        datasets.append(("season", make_season_dataset(pitching, exclude_2020)))
        if args.include_statcast and not statcast_pas.empty:
            datasets.append(("inseason", make_inseason_datasets(statcast_pas, exclude_2020)))
            datasets.append(("rolling", make_rolling_datasets(statcast_pas, exclude_2020)))

    metrics_frames = []
    prediction_frames = []
    hyper_frames = []
    for scenario_group, dataset in datasets:
        metrics, predictions, hyper = evaluate_dataset(dataset, scenario_group)
        if not metrics.empty:
            metrics_frames.append(metrics)
        if not predictions.empty:
            prediction_frames.append(predictions)
        if not hyper.empty:
            hyper_frames.append(hyper)

    metrics_all = pd.concat(metrics_frames, ignore_index=True) if metrics_frames else pd.DataFrame()
    predictions_all = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    hyper_all = pd.concat(hyper_frames, ignore_index=True) if hyper_frames else pd.DataFrame()
    deciles = build_deciles(predictions_all)
    luck = build_luck_buckets(predictions_all)
    buy_sell = build_buy_low_sell_high(predictions_all)
    bootstrap = bootstrap_rolling(predictions_all, args.bootstrap_reps, args.seed)
    _, sanity_summary = write_result_sanity_checks(
        paths,
        {
            "pitching_features": pitching,
            "oos_predictions": predictions_all,
        },
    )

    metrics_all.to_csv(paths.results / "overall_metrics.csv", index=False)
    metrics_all[metrics_all.get("split", pd.Series(dtype=str)).ne("all")].to_csv(paths.results / "split_metrics.csv", index=False)
    deciles.to_csv(paths.results / "decile_results.csv", index=False)
    luck.to_csv(paths.results / "luck_bucket_results.csv", index=False)
    buy_sell.to_csv(paths.results / "buy_low_sell_high_results.csv", index=False)
    hyper_all.to_csv(paths.results / "hyperparameter_results.csv", index=False)
    bootstrap.to_csv(paths.results / "rolling_bootstrap_ci.csv", index=False)
    if not predictions_all.empty:
        predictions_all.to_csv(paths.results / "oos_predictions.csv", index=False)
    make_plots(paths, predictions_all, deciles, hyper_all)
    write_generated_summary(paths, metrics_all)
    row_counts = {
        "pitching_features": int(len(pitching)),
        "statcast_terminal_pa": int(len(statcast_pas)),
        "statcast_pitcher_seasons": int(len(full_sc)),
        "metrics": int(len(metrics_all)),
        "predictions": int(len(predictions_all)),
        "hyperparameters": int(len(hyper_all)),
        "deciles": int(len(deciles)),
        "luck_buckets": int(len(luck)),
        "buy_low_sell_high": int(len(buy_sell)),
    }
    write_manifest(paths, args, row_counts, sanity_summary, reconciliation_summary)
    paths.update_latest_pointer()


def write_self_test_cache(paths: ProjectPaths) -> None:
    rng = np.random.default_rng(7)
    paths.raw.mkdir(parents=True, exist_ok=True)
    fg_frames = []
    for season in range(2015, 2026):
        n = 90
        pitcher_ids = np.arange(1000, 1000 + n)
        tbf = rng.integers(180, 760, n)
        ip = tbf / rng.uniform(3.9, 4.5, n)
        k_rate = rng.normal(0.23, 0.045, n).clip(0.10, 0.38)
        bb_rate = rng.normal(0.08, 0.025, n).clip(0.025, 0.16)
        babip = rng.normal(0.295, 0.035, n).clip(0.22, 0.38)
        hr = rng.poisson(tbf * 0.028)
        er = np.round((tbf / 4.25) * rng.normal(4.1, 0.7, n).clip(2.0, 7.0) / 9.0)
        k = np.round(tbf * k_rate)
        bb = np.round(tbf * bb_rate)
        bip = np.maximum(tbf - k - bb - hr - rng.integers(8, 25, n), 10)
        h = np.round(hr + babip * bip)
        ab = bip + k + hr - rng.integers(4, 12, n)
        sf = rng.integers(1, 8, n)
        frame = pd.DataFrame(
            {
                "Name": [f"Pitcher {pid}" for pid in pitcher_ids],
                "IDfg": pitcher_ids,
                "MLBAMID": pitcher_ids + 100000,
                "Team": "TST",
                "G": rng.integers(30, 65, n),
                "GS": rng.integers(0, 32, n),
                "IP": [f"{int(x)}.{int(round((x - int(x)) * 3))}" for x in ip],
                "TBF": tbf,
                "H": h,
                "HR": hr,
                "ER": er,
                "BB": bb,
                "SO": k,
                "AB": ab,
                "SF": sf,
            }
        )
        whip = (frame["BB"] + frame["H"]) / frame["IP"].map(parse_baseball_ip)
        frame["WHIP"] = whip
        frame["ERA"] = 9.0 * frame["ER"] / frame["IP"].map(parse_baseball_ip)
        frame["BABIP"] = (frame["H"] - frame["HR"]) / (frame["AB"] - frame["SO"] - frame["HR"] + frame["SF"])
        frame["K%"] = frame["SO"] / frame["TBF"]
        frame["BB%"] = frame["BB"] / frame["TBF"]
        frame.to_csv(paths.raw / f"fangraphs_pitching_{season}.csv", index=False)
        fg_frames.append(frame)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent), help="Analysis project root.")
    parser.add_argument("--seasons", nargs="+", type=int, default=SEASONS, help="Complete seasons to include.")
    parser.add_argument("--fetch", action="store_true", help="Fetch FanGraphs and optional Statcast raw data into the cache.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing raw cache files while fetching.")
    parser.add_argument("--season-source", choices=["auto", "fangraphs", "mlb"], default="auto", help="Season pitching stat source for --fetch.")
    parser.add_argument("--include-statcast", action="store_true", help="Include Statcast xBA, in-season, and rolling-window analyses.")
    parser.add_argument("--chunk-days", type=int, default=7, help="Date chunk size for Statcast fetches.")
    parser.add_argument("--bootstrap-reps", type=int, default=200, help="Clustered bootstrap reps for rolling-window confidence intervals.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--run-id", default=None, help="Optional run id for results/<run_id> and plots/<run_id>.")
    parser.add_argument("--raw-dir", default=None, help="Optional raw cache directory override.")
    parser.add_argument("--fast-grid", action="store_true", help="Use a reduced hyperparameter grid for smoke tests.")
    parser.add_argument("--self-test", action="store_true", help="Create a synthetic cache and run the season-level pipeline.")
    return parser.parse_args()


def configure_grids(fast_grid: bool) -> None:
    global C_GRID, C_IP_GRID, C_TBF_GRID, ALPHA_GRID, LAMBDA_GRID, GAMMA_GRID
    if not fast_grid:
        return
    C_GRID = [250, 1000]
    C_IP_GRID = [40, 100]
    C_TBF_GRID = [200, 750]
    ALPHA_GRID = [0.0, 0.5, 1.0]
    LAMBDA_GRID = [0.5, 1.0, 1.5]
    GAMMA_GRID = [0.5, 1.0, 1.5]


def main() -> None:
    args = parse_args()
    if args.self_test:
        args.fast_grid = True
        if args.raw_dir is None:
            args.raw_dir = str(Path(args.project_root).resolve() / "data" / "self_test_raw")
        paths = ProjectPaths.from_root(Path(args.project_root).resolve(), "self_test_seed", args.raw_dir)
        write_self_test_cache(paths)
        args.fetch = False
        args.include_statcast = False
        args.bootstrap_reps = 0
    configure_grids(args.fast_grid)
    run_analysis(args)


if __name__ == "__main__":
    main()
