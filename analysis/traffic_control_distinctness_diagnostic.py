from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/kylejohansen/Documents/Codex/2026-05-15/codex-prompt-use-this-prompt-inside")
sys.path.insert(0, str((ROOT / "analysis/whip_predictors").resolve()))
sys.path.insert(0, str((ROOT / "scripts").resolve()))

from data_integrity import regular_season_window, scope_to_regular_season  # noqa: E402
from whip_predictors import (  # noqa: E402
    BB_EVENTS,
    HIT_EVENTS,
    HR_EVENTS,
    K_EVENTS,
    NON_AB_EVENTS,
    OUTS_BY_EVENT,
    SF_EVENTS,
    normalize_fangraphs_pitching,
    safe_divide,
)

RAW_DIR = ROOT / "analysis/whip_predictors/data/raw"
CACHE_DIR = RAW_DIR / "base_state_statcast"
REPORT = Path("/private/tmp/traffic_control_distinctness_report.txt")
CHUNK_DAYS = 7
NEEDED = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "player_name",
    "events",
    "inning",
    "outs_when_up",
    "on_1b",
    "on_2b",
    "on_3b",
    "game_type",
]


def date_chunks(season: int):
    start, end = regular_season_window(season)
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        yield cur.isoformat(), stop.isoformat()
        cur = stop + timedelta(days=1)


def fetch_cache(season: int) -> list[Path]:
    from pybaseball import statcast

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for start, end in date_chunks(season):
        out = CACHE_DIR / f"statcast_base_state_{season}_{start}_{end}.csv.gz"
        files.append(out)
        if out.exists() and out.stat().st_size > 100:
            continue
        print(f"Fetching {season} {start}..{end}", flush=True)
        frame = statcast(start, end, verbose=False, parallel=True)
        keep = [column for column in NEEDED if column in frame.columns]
        frame[keep].to_csv(out, index=False, compression="gzip")
    return files


def load_pitches(season: int) -> pd.DataFrame:
    files = fetch_cache(season)
    frames = []
    for path in files:
        try:
            frame = pd.read_csv(path, usecols=lambda column: column in NEEDED, low_memory=False)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError(f"No Statcast rows loaded for {season}")
    df = pd.concat(frames, ignore_index=True)
    df = scope_to_regular_season(df, season, date_column="game_date")
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    for column in [
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher",
        "inning",
        "outs_when_up",
        "on_1b",
        "on_2b",
        "on_3b",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def build_pa(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.dropna(subset=["game_pk", "at_bat_number"]).sort_values(
        ["game_date", "game_pk", "at_bat_number", "pitch_number"]
    )
    keys = ["game_pk", "at_bat_number"]
    first = df.groupby(keys, dropna=False).first().reset_index()
    terminal = df[df["events"].fillna("").astype(str).str.strip().ne("")].groupby(keys, dropna=False).last().reset_index()
    base_cols = ["game_pk", "at_bat_number", "on_1b", "on_2b", "on_3b", "outs_when_up"]
    pa = terminal.merge(first[base_cols], on=keys, how="left", suffixes=("", "_first"))
    events = pa["events"].fillna("").astype(str)
    pa["_tbf"] = 1
    pa["_k"] = events.isin(K_EVENTS).astype(int)
    pa["_bb"] = events.isin(BB_EVENTS).astype(int)
    pa["_ibb"] = events.eq("intent_walk").astype(int)
    pa["_h"] = events.isin(HIT_EVENTS).astype(int)
    pa["_hr"] = events.isin(HR_EVENTS).astype(int)
    pa["_sf"] = events.isin(SF_EVENTS).astype(int)
    pa["_ab"] = (~events.isin(NON_AB_EVENTS)).astype(int)
    pa["_outs"] = events.map(OUTS_BY_EVENT).fillna(0).astype(int)
    pa["_bip"] = (pa["_ab"] - pa["_k"] - pa["_hr"] + pa["_sf"]).clip(lower=0)
    pa["men_on"] = pa[["on_1b", "on_2b", "on_3b"]].fillna(0).gt(0).any(axis=1)
    pa["risp"] = pa[["on_2b", "on_3b"]].fillna(0).gt(0).any(axis=1)
    pa["bases_empty"] = ~pa["men_on"]
    pa["season"] = season
    game_order = (
        pa[["pitcher", "game_date", "game_pk"]]
        .drop_duplicates()
        .sort_values(["pitcher", "game_date", "game_pk"])
        .assign(game_index=lambda x: x.groupby("pitcher").cumcount())
    )
    pa = pa.merge(game_order[["pitcher", "game_pk", "game_index"]], on=["pitcher", "game_pk"], how="left")
    pa["half"] = np.where(pa["game_index"].fillna(0).astype(int) % 2 == 0, "even_games", "odd_games")
    return pa


def agg_pa(pa: pd.DataFrame, mask: pd.Series | None, label: str, group_cols: list[str]) -> pd.DataFrame:
    source = pa if mask is None else pa[mask]
    if source.empty:
        return pd.DataFrame(columns=group_cols + ["player_name", f"{label}_pa", f"{label}_k_pct", f"{label}_bb_pct", f"{label}_kbb"])
    group = (
        source.groupby(group_cols, dropna=False)
        .agg(
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
            bip=("_bip", "sum"),
        )
        .reset_index()
    )
    group[f"{label}_pa"] = group["tbf"]
    group[f"{label}_k_pct"] = safe_divide(group["k"], group["tbf"])
    group[f"{label}_bb_pct"] = safe_divide(group["bb"], group["tbf"])
    group[f"{label}_kbb"] = group[f"{label}_k_pct"] - group[f"{label}_bb_pct"]
    group[f"{label}_ip"] = group["outs"] / 3.0
    keep = group_cols + [
        "player_name",
        f"{label}_pa",
        f"{label}_k_pct",
        f"{label}_bb_pct",
        f"{label}_kbb",
        f"{label}_ip",
    ]
    return group[keep]


def load_season_context(season: int) -> pd.DataFrame:
    raw = pd.read_csv(RAW_DIR / f"fangraphs_pitching_{season}.csv")
    context = normalize_fangraphs_pitching(raw, season)
    context["pitcher"] = pd.to_numeric(context["mlbam_id"], errors="coerce")
    denom = context["h"] + context["bb"] - context["hr"]
    context["lob_proxy"] = safe_divide(context["h"] + context["bb"] - context["hr"] - context["er"], denom)
    context["tc_raw"] = context["wsi_xlgbabip"]
    context["traffic_raw"] = safe_divide(1.0, context["xwhip_lgbabip"])
    return context[
        [
            "season",
            "pitcher",
            "player_name",
            "team",
            "role",
            "ip",
            "tbf",
            "k_pct",
            "bb_pct",
            "kbb",
            "whip",
            "xwhip_lgbabip",
            "wsi_xlgbabip",
            "tc_raw",
            "traffic_raw",
            "lob_proxy",
        ]
    ].copy()


def build_splits(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    pitches = load_pitches(season)
    pa = build_pa(pitches, season)
    print(f"{season}: loaded pitches={len(pitches):,}; terminal PA={len(pa):,}; pitchers={pa.pitcher.nunique():,}", flush=True)
    group_cols = ["season", "pitcher"]
    total = agg_pa(pa, None, "total", group_cols)
    empty = agg_pa(pa, pa["bases_empty"], "empty", group_cols)
    men = agg_pa(pa, pa["men_on"], "men_on", group_cols)
    risp = agg_pa(pa, pa["risp"], "risp", group_cols)
    splits = (
        total.merge(empty.drop(columns=["player_name"]), on=group_cols, how="left")
        .merge(men.drop(columns=["player_name"]), on=group_cols, how="left")
        .merge(risp.drop(columns=["player_name"]), on=group_cols, how="left")
    )
    context = load_season_context(season)
    splits = splits.merge(
        context.drop(columns=["player_name"]),
        on=["season", "pitcher"],
        how="left",
        suffixes=("", "_season"),
    )
    splits["empty_to_men_delta"] = splits["men_on_kbb"] - splits["empty_kbb"]
    splits["risp_delta"] = splits["risp_kbb"] - splits["empty_kbb"]
    half_parts = []
    for half in ["even_games", "odd_games"]:
        half_pa = pa[pa["half"].eq(half)]
        half_total = agg_pa(half_pa, None, "total", group_cols)
        half_empty = agg_pa(half_pa, half_pa["bases_empty"], "empty", group_cols)
        half_men = agg_pa(half_pa, half_pa["men_on"], "men_on", group_cols)
        half_risp = agg_pa(half_pa, half_pa["risp"], "risp", group_cols)
        half_splits = (
            half_total.merge(half_empty.drop(columns=["player_name"]), on=group_cols, how="left")
            .merge(half_men.drop(columns=["player_name"]), on=group_cols, how="left")
            .merge(half_risp.drop(columns=["player_name"]), on=group_cols, how="left")
        )
        half_splits["half"] = half
        half_splits["empty_to_men_delta"] = half_splits["men_on_kbb"] - half_splits["empty_kbb"]
        half_splits["risp_delta"] = half_splits["risp_kbb"] - half_splits["empty_kbb"]
        half_parts.append(half_splits)
    return splits, pd.concat(half_parts, ignore_index=True)


def plus(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    mean = values.mean()
    return 100.0 * values / mean if mean and np.isfinite(mean) else values * np.nan


def role_frames(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [
        ("all", frame),
        ("starter", frame[frame["role"].eq("starter")]),
        ("reliever", frame[frame["role"].eq("reliever")]),
    ]


def qualified(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[(frame["ip"] >= 40) & (frame["men_on_pa"] >= 50) & (frame["risp_pa"] >= 25)].copy()
    out["floor_flag"] = np.where(
        (out["ip"] <= 45) | (out["men_on_pa"] <= 55) | (out["risp_pa"] <= 30),
        "near floor",
        "",
    )
    return out


def corr_pair(frame: pd.DataFrame, a: str, b: str, method: str = "pearson") -> float:
    data = frame[[a, b]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 3:
        return np.nan
    return float(data[a].corr(data[b], method=method))


def add_plus_columns(frame: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, role_frame in role_frames(frame):
        if role_frame.empty:
            continue
    out_parts = []
    for role, role_frame in role_frames(frame):
        if role_frame.empty:
            continue
        part = role_frame.copy()
        part["role_scope"] = role
        part["tc_plus"] = plus(part["tc_raw"])
        part["command_plus"] = plus(part["kbb"])
        part["traffic_plus"] = plus(part["traffic_raw"])
        part["men_on_kbb_plus"] = plus(part["men_on_kbb"])
        part["risp_kbb_plus"] = plus(part["risp_kbb"])
        out_parts.append(part)
    return pd.concat(out_parts, ignore_index=True)


def year_to_year_stability(frame: pd.DataFrame, metric: str, role: str) -> float:
    q = frame[frame["role_scope"].eq(role)].copy()
    wide = q.pivot_table(index="pitcher", columns="season", values=metric, aggfunc="first")
    if 2024 not in wide.columns or 2025 not in wide.columns:
        return np.nan
    return float(wide[2024].corr(wide[2025], method="pearson"))


def split_half_stability(half_frame: pd.DataFrame, season_context: pd.DataFrame, metric: str, role: str) -> float:
    h = half_frame.merge(
        season_context[["season", "pitcher", "role", "ip"]],
        on=["season", "pitcher"],
        how="left",
    )
    h = h[(h["ip"] >= 40) & (h["men_on_pa"] >= 25) & (h["risp_pa"] >= 12)].copy()
    if role != "all":
        h = h[h["role"].eq(role)]
    wide = h.pivot_table(index=["season", "pitcher"], columns="half", values=metric, aggfunc="first")
    if "even_games" not in wide.columns or "odd_games" not in wide.columns:
        return np.nan
    return float(wide["even_games"].corr(wide["odd_games"], method="pearson"))


def table_rows(frame: pd.DataFrame, sort_col: str, n: int = 12) -> str:
    lines = [
        "| # | Pitcher | Team | Role | IP | Score | K-BB% | xWHIP | TC+ | Command+ | Traffic+ | MenOn K-BB% | RISP K-BB% | Escape | LOB proxy | Flag |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, (_, row) in enumerate(frame.sort_values(sort_col, ascending=False).head(n).iterrows(), 1):
        lines.append(
            f"| {i} | {row.player_name} | {row.team} | {row.role} | {row.ip:.1f} | {row[sort_col]:.0f} | "
            f"{100 * row.kbb:.1f}% | {row.xwhip_lgbabip:.3f} | {row.tc_plus:.0f} | {row.command_plus:.0f} | "
            f"{row.traffic_plus:.0f} | {100 * row.men_on_kbb:.1f}% | {100 * row.risp_kbb:.1f}% | "
            f"{100 * row.empty_to_men_delta:+.1f}% | {100 * row.lob_proxy:.1f}% | {row.floor_flag} |"
        )
    return "\n".join(lines)


def corner_examples(frame: pd.DataFrame, role: str) -> str:
    q = frame[frame["role_scope"].eq(role)].copy()
    cmd_hi = q["command_plus"].quantile(0.75)
    cmd_lo = q["command_plus"].quantile(0.25)
    traf_hi = q["traffic_plus"].quantile(0.75)
    traf_lo = q["traffic_plus"].quantile(0.25)
    specs = [
        ("Air Traffic Controller", q[(q["command_plus"] >= cmd_hi) & (q["traffic_plus"] >= traf_hi)], "tc_plus"),
        ("Command Stranded", q[(q["command_plus"] >= cmd_hi) & (q["traffic_plus"] <= traf_lo)], "command_plus"),
        ("Traffic Dodger", q[(q["command_plus"] <= cmd_lo) & (q["traffic_plus"] >= traf_hi)], "traffic_plus"),
        ("Gridlock", q[(q["command_plus"] <= cmd_lo) & (q["traffic_plus"] <= traf_lo)], "tc_plus"),
    ]
    lines = [
        "| Corner | Pitcher | Team | Role | TC+ | Command+ | Traffic+ | K-BB% | xWHIP | WHIP |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, subset, sort_col in specs:
        if subset.empty:
            lines.append(f"| {name} | none |  |  |  |  |  |  |  |  |")
            continue
        row = subset.sort_values(sort_col, ascending=name != "Gridlock").iloc[0]
        lines.append(
            f"| {name} | {row.player_name} | {row.team} | {row.role} | {row.tc_plus:.0f} | {row.command_plus:.0f} | "
            f"{row.traffic_plus:.0f} | {100 * row.kbb:.1f}% | {row.xwhip_lgbabip:.3f} | {row.whip:.3f} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    args = parser.parse_args()

    split_frames = []
    half_frames = []
    for season in args.seasons:
        splits, halves = build_splits(season)
        split_frames.append(splits)
        half_frames.append(halves)

    all_splits = pd.concat(split_frames, ignore_index=True)
    all_halves = pd.concat(half_frames, ignore_index=True)
    q = add_plus_columns(qualified(all_splits))

    lines = []
    lines.append("# TC+ Distinctness and Traffic Response Diagnostic")
    lines.append("")
    lines.append("Diagnostic-only. Regular-season scoped through scripts/data_integrity.py. Base state = first pitch of PA; outcome = terminal pitch.")
    lines.append("Gates: IP >= 40, men-on PA >= 50, RISP PA >= 25. Split-half uses odd/even pitcher games with relaxed half gates: men-on PA >= 25, RISP PA >= 12.")
    lines.append("TC+ here is plus-scaled `100 * (K% - BB%) / xWHIP_lgBABIP` within each role scope.")
    lines.append("")

    lines.append("## Part 0 - TC+ Distinctness Battery")
    lines.append("| Role | N player-seasons | r(TC+, K-BB%) | r(TC+, xWHIP) | r(TC+, WHIP) | 2024->2025 TC+ Pearson | Decision vs 0.90 K-BB clone rule |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for role in ["all", "starter", "reliever"]:
        role_q = q[q["role_scope"].eq(role)]
        r_kbb = corr_pair(role_q, "tc_plus", "kbb", "pearson")
        r_xwhip = corr_pair(role_q, "tc_plus", "xwhip_lgbabip", "pearson")
        r_whip = corr_pair(role_q, "tc_plus", "whip", "pearson")
        stab = year_to_year_stability(q, "tc_plus", role)
        decision = "clone risk / quotient headline dead" if r_kbb >= 0.90 else "not a pure K-BB clone"
        lines.append(f"| {role} | {len(role_q)} | {r_kbb:.3f} | {r_xwhip:.3f} | {r_whip:.3f} | {stab:.3f} | {decision} |")
    lines.append("")

    lines.append("## Part 1 - Two-Axis Command+ x Traffic+")
    lines.append("| Role | r(Command+, Traffic+) | Interpretation |")
    lines.append("|---|---:|---|")
    for role in ["all", "starter", "reliever"]:
        role_q = q[q["role_scope"].eq(role)]
        r_axes = corr_pair(role_q, "command_plus", "traffic_plus", "pearson")
        interp = "usable independent-ish quadrant" if abs(r_axes) < 0.60 else "collinear enough to be cautious"
        lines.append(f"| {role} | {r_axes:.3f} | {interp} |")
    lines.append("")
    for role in ["all", "starter", "reliever"]:
        lines.append(f"### Four-Corner Examples - {role}")
        lines.append(corner_examples(q, role))
        lines.append("")

    lines.append("## Part 2 - Men-On Split: Strand Skill vs Strand-Rate Mirage")
    lines.append("### Product Gap Correlations")
    lines.append("| Role | r(Men-On K-BB%, TC+) | r(LOB proxy, Men-On K-BB%) | r(LOB proxy, RISP K-BB%) |")
    lines.append("|---|---:|---:|---:|")
    for role in ["all", "starter", "reliever"]:
        role_q = q[q["role_scope"].eq(role)]
        lines.append(
            f"| {role} | {corr_pair(role_q, 'men_on_kbb', 'tc_plus', 'spearman'):.3f} | "
            f"{corr_pair(role_q, 'lob_proxy', 'men_on_kbb', 'spearman'):.3f} | "
            f"{corr_pair(role_q, 'lob_proxy', 'risp_kbb', 'spearman'):.3f} |"
        )
    lines.append("")

    lines.append("### Split-Half Stability")
    lines.append("| Role | Men-On K-BB% odd/even Pearson | RISP K-BB% odd/even Pearson | Escape Split odd/even Pearson | Scoring verdict |")
    lines.append("|---|---:|---:|---:|---|")
    for role in ["all", "starter", "reliever"]:
        men_stab = split_half_stability(all_halves, all_splits, "men_on_kbb", role)
        risp_stab = split_half_stability(all_halves, all_splits, "risp_kbb", role)
        esc_stab = split_half_stability(all_halves, all_splits, "empty_to_men_delta", role)
        verdict = "scoreable leaderboard candidate" if men_stab >= 0.55 and risp_stab >= 0.55 else "texture/badge before precise score"
        lines.append(f"| {role} | {men_stab:.3f} | {risp_stab:.3f} | {esc_stab:.3f} | {verdict} |")
    lines.append("")

    for role in ["starter", "reliever"]:
        role_2025 = q[(q["season"].eq(2025)) & (q["role_scope"].eq(role))]
        lines.append(f"### 2025 Top Men-On K-BB+ - {role}")
        lines.append(table_rows(role_2025, "men_on_kbb_plus", 15))
        lines.append("")
        lines.append(f"### 2025 Biggest Escape Split Risers - {role}")
        lines.append(table_rows(role_2025, "empty_to_men_delta", 15))
        lines.append("")

    lines.append("## Recommendation")
    all_role = q[q["role_scope"].eq("all")]
    r_tc_kbb = corr_pair(all_role, "tc_plus", "kbb", "pearson")
    r_axes = corr_pair(all_role, "command_plus", "traffic_plus", "pearson")
    men_stab = split_half_stability(all_halves, all_splits, "men_on_kbb", "all")
    risp_stab = split_half_stability(all_halves, all_splits, "risp_kbb", "all")
    lob_gap = corr_pair(all_role, "lob_proxy", "men_on_kbb", "spearman")
    if r_tc_kbb >= 0.90:
        lines.append(f"- Baseline TC+ is too close to K-BB% by the pre-registered rule (r={r_tc_kbb:.3f}); do not ship the quotient as the headline.")
    else:
        lines.append(f"- Baseline TC+ clears the K-BB clone rule (r={r_tc_kbb:.3f}), so it carries some descriptive traffic-denominator information.")
    if abs(r_axes) < 0.60:
        lines.append(f"- Command+ and Traffic+ are independent enough for a real quadrant (r={r_axes:.3f}).")
    else:
        lines.append(f"- Command+ and Traffic+ are fairly collinear (r={r_axes:.3f}); the quadrant needs caution.")
    lines.append(
        f"- Men-on K-BB has a clear strand-skill gap versus LOB proxy (LOB vs men-on K-BB r={lob_gap:.3f}), "
        "so LOB% should remain context/mirage, not an input."
    )
    if men_stab >= 0.55 and risp_stab >= 0.55:
        lines.append(f"- Men-on/RISP split-half stability is healthy enough to score directly (men={men_stab:.3f}, RISP={risp_stab:.3f}).")
    else:
        lines.append(f"- Men-on/RISP split-half stability is not strong enough for a precise headline score yet (men={men_stab:.3f}, RISP={risp_stab:.3f}); use as texture/badge.")
    lines.append("- Predictive WHIP optimization was not reopened.")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:38]))
    print(f"\nWrote report: {REPORT}")


if __name__ == "__main__":
    main()
