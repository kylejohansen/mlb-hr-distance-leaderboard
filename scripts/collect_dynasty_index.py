#!/usr/bin/env python3
"""Collect an internal, point-in-time fantasy dynasty market snapshot.

This is a shadow-data pilot. It captures free/public dynasty ranking pages,
joins them to local MLBAM identities with conservative rules, and writes dated
raw/composite files. It does not touch public app output or production formulas.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import re
import statistics
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


SOURCES = {
    "fantasypros": {
        "name": "FantasyPros",
        "url": "https://www.fantasypros.com/mlb/rankings/dynasty-overall.php",
        "captureMethod": "embedded JSON object in public HTML",
        "cleanEnoughForWeeklyCollection": True,
    },
    "rotowire": {
        "name": "RotoWire",
        "url": "https://www.rotowire.com/baseball/tables/dynasty-rankings.php?pos=All&league=3&team=noTeam",
        "pageUrl": "https://www.rotowire.com/baseball/dynasty-rankings.php",
        "captureMethod": "public table JSON endpoint referenced by page JavaScript",
        "cleanEnoughForWeeklyCollection": False,
    },
    "fantrax": {
        "name": "FantraxHQ",
        "url": "https://www.fantraxhq.com/fantasy-baseball-dynasty-rankings/",
        "captureMethod": "HTML table parse from public article",
        "cleanEnoughForWeeklyCollection": False,
    },
    "rotoballer": {
        "name": "RotoBaller Eric Cross",
        "url": "https://www.rotoballer.com/top-200-fantasy-baseball-dynasty-rankings-may-2026-update/1867770",
        "captureMethod": "HTML table parse from public article",
        "cleanEnoughForWeeklyCollection": False,
    },
    "harryknowsball": {
        "name": "HarryKnowsBall",
        "url": "https://harryknowsball.com/rankings",
        "captureMethod": "Next.js JSON payload in public HTML",
        "cleanEnoughForWeeklyCollection": True,
    },
}

MIN_ROWS_FOR_COMPOSITE = 50

RAW_FIELDS = [
    "captureDate",
    "captureTimestampCentral",
    "sourceName",
    "sourceUrl",
    "sourcePublishedDate",
    "sourceRank",
    "sourcePlayerName",
    "sourceTeam",
    "sourcePosition",
    "sourceAge",
    "sourcePlayerId",
    "sourceMlbamId",
    "rawRankType",
    "rawLevel",
    "rawNotes",
]

DYNASTY_IDENTITY_MAP_FIELDS = [
    "normalizedName",
    "sourceName",
    "sourcePlayerName",
    "sourceTeam",
    "sourcePosition",
    "mlbamId",
    "playerId",
    "matchedName",
    "matchStatus",
    "notes",
    "lastReviewedDate",
]

JOIN_REVIEW_FIELDS = [
    "source",
    "sourceRank",
    "sourcePlayerName",
    "normalizedName",
    "sourceTeam",
    "sourcePosition",
    "sourceAge",
    "matchedPlayerId",
    "mlbamId",
    "matchedName",
    "matchedTeam",
    "joinMethod",
    "joinConfidence",
    "joinStatus",
    "reason",
]

COMPOSITE_FIELDS = [
    "mlbamId",
    "player",
    "normalizedName",
    "team",
    "position",
    "age",
    "dynastyCompositePct",
    "dynastyCompositeRank",
    "sourceCoverage",
    "sourcesRanked",
    "disagreementPctStdDev",
    "rankStdDev",
    "rankRange",
    "bestSource",
    "bestRank",
    "worstSource",
    "worstRank",
    "highestSourcePct",
    "lowestSourcePct",
    "compositeConfidence",
    "contextLabels",
    "fantasyprosRank",
    "fantasyprosDepth",
    "fantasyprosPct",
    "rotowireRank",
    "rotowireDepth",
    "rotowirePct",
    "fantraxRank",
    "fantraxDepth",
    "fantraxPct",
    "rotoballerRank",
    "rotoballerDepth",
    "rotoballerPct",
    "harryknowsballRank",
    "harryknowsballDepth",
    "harryknowsballPct",
]

TEAM_ALIASES = {
    "AZ": "ARI",
    "ARZ": "ARI",
    "KCR": "KC",
    "KAN": "KC",
    "SFG": "SF",
    "SDP": "SD",
    "TBR": "TB",
    "CHW": "CWS",
    "CWS": "CWS",
    "WSN": "WSH",
    "OAK": "ATH",
    "ATH": "ATH",
}


def central_now() -> dt.datetime:
    if ZoneInfo is not None:
        return dt.datetime.now(ZoneInfo("America/Chicago"))
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace(".", " ")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_team(value: str) -> str:
    team = (value or "").strip().upper()
    return TEAM_ALIASES.get(team, team)


def clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "TheLongBall dynasty index pilot"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing dated file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing dated file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def source_row(
    capture_date: str,
    captured_at: str,
    source_key: str,
    source_url: str,
    source_published_date: str,
    rank: Any,
    player: str,
    team: str = "",
    position: str = "",
    age: Any = "",
    source_player_id: Any = "",
    source_mlbam_id: Any = "",
    raw_rank_type: str = "",
    raw_level: str = "",
    raw_notes: str = "",
) -> dict[str, Any]:
    return {
        "captureDate": capture_date,
        "captureTimestampCentral": captured_at,
        "sourceName": SOURCES[source_key]["name"],
        "sourceUrl": source_url,
        "sourcePublishedDate": source_published_date,
        "sourceRank": rank,
        "sourcePlayerName": player,
        "sourceTeam": team,
        "sourcePosition": position,
        "sourceAge": age,
        "sourcePlayerId": source_player_id,
        "sourceMlbamId": source_mlbam_id,
        "rawRankType": raw_rank_type,
        "rawLevel": raw_level,
        "rawNotes": raw_notes,
    }


def parse_fantasypros(text: str, capture_date: str, captured_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    match = re.search(r"var ecrData\s*=\s*(\{.*?\});", text, re.S)
    if not match:
        raise ValueError("FantasyPros ecrData object not found")
    data = json.loads(match.group(1))
    rows: list[dict[str, Any]] = []
    for player in data.get("players", []):
        rows.append(
            source_row(
                capture_date,
                captured_at,
                "fantasypros",
                SOURCES["fantasypros"]["url"],
                data.get("last_updated", ""),
                player.get("rank_ecr"),
                player.get("player_name", ""),
                player.get("player_team_id", ""),
                player.get("player_positions") or player.get("primary_position", ""),
                player.get("player_age", ""),
                player.get("player_id", ""),
                "",
                "ECR",
                "",
                f"total_experts={data.get('total_experts', '')}; rank_min={player.get('rank_min', '')}; rank_max={player.get('rank_max', '')}",
            )
        )
    return rows, {"sourcePublishedDate": data.get("last_updated", ""), "rawMeta": {k: data.get(k) for k in ("count", "total_experts", "last_updated", "year", "type")}}


def parse_rotowire(text: str, capture_date: str, captured_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(text)
    rows = [
        source_row(
            capture_date,
            captured_at,
            "rotowire",
            SOURCES["rotowire"].get("pageUrl", SOURCES["rotowire"]["url"]),
            "Updated as of June 10, 2026",
            item.get("rank", ""),
            item.get("player", ""),
            item.get("team", ""),
            item.get("position", ""),
            item.get("age", ""),
            item.get("playerID", ""),
            "",
            "overall",
            item.get("level", ""),
            f"avgStatus={item.get('avgStatus', '')}",
        )
        for item in data
    ]
    return rows, {"sourcePublishedDate": "Updated as of June 10, 2026", "rawMeta": {"endpointRows": len(data)}}


def table_rows(text: str, table_pattern: str | None = None) -> list[list[str]]:
    if table_pattern:
        match = re.search(table_pattern, text, re.S)
        if not match:
            return []
        table = match.group(0)
    else:
        idx = text.find("<table")
        if idx < 0:
            return []
        end = text.find("</table>", idx)
        table = text[idx : end + len("</table>")]
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        if cells:
            rows.append([clean_text(cell) for cell in cells])
    return rows


def parse_fantrax(text: str, capture_date: str, captured_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = table_rows(text, r'<table id="tablepress-3805".*?</table>')
    parsed: list[dict[str, Any]] = []
    for cells in rows[1:]:
        if len(cells) < 7:
            continue
        parsed.append(
            source_row(
                capture_date,
                captured_at,
                "fantrax",
                SOURCES["fantrax"]["url"],
                "2026-02-23",
                cells[1],
                cells[3],
                cells[5],
                cells[4],
                cells[6],
                "",
                "",
                "Roto",
                cells[7] if len(cells) > 7 else "",
                f"pointsRank={cells[0]}; change={cells[2]}; eta={cells[8] if len(cells) > 8 else ''}",
            )
        )
    return parsed, {"sourcePublishedDate": "2026-02-23", "rawMeta": {"tableRows": len(parsed)}}


def parse_rotoballer(text: str, capture_date: str, captured_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = table_rows(text)
    parsed: list[dict[str, Any]] = []
    for cells in rows[1:]:
        if len(cells) < 6:
            continue
        rank, player, pos, team, age, previous = cells[:6]
        source_id = ""
        row_html_match = re.search(
            rf"<tr[^>]*>\s*<td>\s*{re.escape(rank)}\s*</td>.*?</tr>",
            text,
            re.S | re.I,
        )
        if row_html_match:
            id_match = re.search(r'data-id="(\d+)"', row_html_match.group(0))
            if id_match:
                source_id = id_match.group(1)
        parsed.append(
            source_row(
                capture_date,
                captured_at,
                "rotoballer",
                SOURCES["rotoballer"]["url"],
                "2026-06-01",
                rank,
                player,
                team,
                pos,
                age,
                source_id,
                source_id,
                "Top 200",
                "",
                f"previousRank={previous}",
            )
        )
    return parsed, {"sourcePublishedDate": "2026-06-01", "rawMeta": {"tableRows": len(parsed)}}


def parse_harry(text: str, capture_date: str, captured_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise ValueError("HarryKnowsBall __NEXT_DATA__ payload not found")
    data = json.loads(match.group(1))
    players = data.get("props", {}).get("pageProps", {}).get("players", [])
    rows: list[dict[str, Any]] = []
    for player in players:
        rows.append(
            source_row(
                capture_date,
                captured_at,
                "harryknowsball",
                SOURCES["harryknowsball"]["url"],
                "",
                player.get("rank", ""),
                player.get("name", ""),
                player.get("team", ""),
                "/".join(player.get("positions") or []),
                player.get("age", ""),
                player.get("id", ""),
                "",
                "crowd value rank",
                player.get("level", ""),
                f"value={player.get('value', '')}; rankChange30Days={player.get('rankChange30Days', '')}; prospect={player.get('prospect', '')}",
            )
        )
    return rows, {"sourcePublishedDate": "", "rawMeta": {"nextPlayers": len(players)}}


PARSERS = {
    "fantasypros": parse_fantasypros,
    "rotowire": parse_rotowire,
    "fantrax": parse_fantrax,
    "rotoballer": parse_rotoballer,
    "harryknowsball": parse_harry,
}


def add_identity(
    identities: dict[int, dict[str, Any]],
    source: str,
    mlbam_id: Any,
    name: str,
    team: str = "",
    position: str = "",
    age: Any = "",
) -> None:
    try:
        player_id = int(str(mlbam_id).strip())
    except (TypeError, ValueError):
        return
    if not name:
        return
    current = identities.setdefault(
        player_id,
        {"mlbamId": player_id, "names": set(), "teams": set(), "positions": set(), "ages": [], "sources": set()},
    )
    current["names"].add(name)
    if team:
        current["teams"].add(clean_team(team))
    if position:
        current["positions"].add(position)
    if age not in ("", None):
        current["ages"].append(str(age))
    current["sources"].add(source)


def load_dynasty_identity_map(identities: dict[int, dict[str, Any]], path: Path) -> None:
    if not path.exists():
        return
    with path.open(newline="") as file:
        for row in csv.DictReader(file):
            status = (row.get("matchStatus") or "").strip().lower()
            if status != "resolved":
                continue
            player_id = row.get("mlbamId") or row.get("playerId")
            matched_name = row.get("matchedName") or row.get("sourcePlayerName")
            source_name = row.get("sourceName") or "dynasty_identity_map"
            add_identity(
                identities,
                source_name,
                player_id,
                matched_name,
                row.get("sourceTeam", ""),
                row.get("sourcePosition", ""),
            )
            add_identity(
                identities,
                f"{source_name}_alias",
                player_id,
                row.get("sourcePlayerName", ""),
                row.get("sourceTeam", ""),
                row.get("sourcePosition", ""),
            )


def load_identity_index(dynasty_identity_map: Path | None = None) -> dict[str, Any]:
    identities: dict[int, dict[str, Any]] = {}

    if dynasty_identity_map is not None:
        load_dynasty_identity_map(identities, dynasty_identity_map)

    map_path = Path("data/shadow/dfs-salaries/dk-player-identity-map.csv")
    if map_path.exists():
        with map_path.open(newline="") as file:
            for row in csv.DictReader(file):
                add_identity(identities, "dk_identity_map", row.get("mlbamId"), row.get("mlbName") or row.get("aliasName"), row.get("teamAbbrev"), row.get("positionFirstSeen"))
                add_identity(identities, "dk_identity_map_alias", row.get("mlbamId"), row.get("aliasName"), row.get("teamAbbrev"), row.get("positionFirstSeen"))

    people_path = Path("data/cache/longball-threat-backtest/player-people-cache.json")
    if people_path.exists():
        payload = json.loads(people_path.read_text())
        for person in payload.get("people", []):
            add_identity(identities, "people_cache", person.get("id"), person.get("fullName"), "", "", person.get("currentAge"))

    for path, list_key, id_key, name_key, team_key, pos_key in [
        (Path("public/data/hr-distance-latest.json"), "players", "batter", "player", "team", ""),
        (Path("public/data/hot-dog-stand-latest.json"), "pitchers", "pitcherId", "pitcher", "team", "pitcherRole"),
        (Path("data/shadow/storm_watch/snapshot_2026-06-05.json"), "players", "playerId", "player", "team", ""),
    ]:
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        for row in payload.get(list_key, []):
            add_identity(identities, str(path), row.get(id_key), row.get(name_key), row.get(team_key), row.get(pos_key) if pos_key else "")

    exact: dict[tuple[str, str], set[int]] = defaultdict(set)
    by_name: dict[str, set[int]] = defaultdict(set)
    by_id = identities
    for player_id, item in identities.items():
        for name in item["names"]:
            normalized = normalize_name(name)
            if not normalized:
                continue
            by_name[normalized].add(player_id)
            for team in item["teams"]:
                exact[(normalized, team)].add(player_id)

    return {"by_id": by_id, "exact": exact, "by_name": by_name}


def representative_identity(identity: dict[str, Any]) -> dict[str, Any]:
    # Prefer fuller display names when aliases differ ("Bobby Witt Jr." over
    # "Bobby Witt", accented names over stripped aliases where present).
    name = sorted(identity["names"], key=lambda item: (-len(item), item))[0] if identity["names"] else ""
    teams = sorted(identity["teams"])
    positions = sorted(identity["positions"])
    return {
        "mlbamId": identity["mlbamId"],
        "player": name,
        "normalizedName": normalize_name(name),
        "team": teams[0] if teams else "",
        "position": positions[0] if positions else "",
        "age": identity["ages"][0] if identity["ages"] else "",
    }


def join_rows(rows_by_source: dict[str, list[dict[str, Any]]], identity_index: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    joined: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    by_id = identity_index["by_id"]
    exact = identity_index["exact"]
    by_name = identity_index["by_name"]

    for source_key, rows in rows_by_source.items():
        for row in rows:
            name = row.get("sourcePlayerName", "")
            normalized = normalize_name(name)
            team = clean_team(row.get("sourceTeam", ""))
            source_id = str(row.get("sourceMlbamId") or "").strip()
            ids: set[int] = set()
            method = ""
            confidence = ""
            status = ""
            reason = ""

            if source_id.isdigit() and int(source_id) in by_id:
                ids = {int(source_id)}
                method = "source_mlbam_id"
                confidence = "high"
                status = "joined"
                reason = "source provided MLBAM-compatible id present in local people cache"
            elif team and (normalized, team) in exact:
                ids = exact[(normalized, team)]
                if len(ids) == 1:
                    method = "exact_normalized_name_team"
                    confidence = "high"
                    status = "joined"
                    reason = "exact normalized name + normalized source team"
                else:
                    method = "exact_normalized_name_team"
                    confidence = "low"
                    status = "ambiguous"
                    reason = f"name/team matched multiple local ids: {sorted(ids)}"
            elif normalized in by_name:
                ids = by_name[normalized]
                if len(ids) == 1:
                    method = "unique_normalized_name"
                    confidence = "medium"
                    status = "joined"
                    reason = "unique local normalized-name match; team missing/stale/different"
                else:
                    method = "normalized_name"
                    confidence = "low"
                    status = "ambiguous"
                    reason = f"name matched multiple local ids: {sorted(ids)}"
            else:
                method = "none"
                confidence = "no_match"
                status = "unmatched"
                reason = "no local exact-name candidate"

            matched_id = next(iter(ids)) if len(ids) == 1 else ""
            matched = representative_identity(by_id[matched_id]) if matched_id else {}
            review_row = {
                "source": SOURCES[source_key]["name"],
                "sourceRank": row.get("sourceRank", ""),
                "sourcePlayerName": name,
                "normalizedName": normalized,
                "sourceTeam": row.get("sourceTeam", ""),
                "sourcePosition": row.get("sourcePosition", ""),
                "sourceAge": row.get("sourceAge", ""),
                "matchedPlayerId": matched_id,
                "mlbamId": matched_id,
                "matchedName": matched.get("player", ""),
                "matchedTeam": matched.get("team", ""),
                "joinMethod": method,
                "joinConfidence": confidence,
                "joinStatus": status,
                "reason": reason,
            }
            review.append(review_row)
            if status == "joined":
                joined_row = dict(row)
                joined_row.update(matched)
                joined_row["mlbamId"] = matched_id
                joined_row["joinMethod"] = method
                joined_row["joinConfidence"] = confidence
                joined_row["joinStatus"] = status
                joined_row["sourceKey"] = source_key
                joined.append(joined_row)
    return joined, review


def to_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def build_composite(joined_rows: list[dict[str, Any]], depths: dict[str, int]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in joined_rows:
        if row.get("joinStatus") != "joined":
            continue
        rank = to_int(row.get("sourceRank"))
        if rank is None:
            continue
        source_key = row["sourceKey"]
        depth = depths.get(source_key, 0)
        if depth <= 1:
            continue
        pct = 1 - ((rank - 1) / (depth - 1))
        row["sourceRankPct"] = max(0.0, min(1.0, pct))
        row["sourceDepth"] = depth
        grouped[int(row["mlbamId"])].append(row)

    composite_rows: list[dict[str, Any]] = []
    for player_id, rows in grouped.items():
        pcts = [float(row["sourceRankPct"]) for row in rows]
        ranks = [int(row["sourceRank"]) for row in rows if to_int(row.get("sourceRank")) is not None]
        best = min(rows, key=lambda row: int(row["sourceRank"]))
        worst = max(rows, key=lambda row: int(row["sourceRank"]))
        rep = rows[0]
        coverage = len({row["sourceKey"] for row in rows})
        pct_std = statistics.pstdev(pcts) if len(pcts) > 1 else 0.0
        rank_std = statistics.pstdev(ranks) if len(ranks) > 1 else 0.0
        rank_range = max(ranks) - min(ranks) if ranks else 0
        if coverage >= 4:
            confidence = "high coverage"
        elif coverage >= 2:
            confidence = "medium coverage"
        else:
            confidence = "one-source flyer"
        labels: list[str] = []
        mean_pct = statistics.mean(pcts)
        if mean_pct >= 0.9 and coverage >= 3 and pct_std <= 0.08:
            labels.append("Consensus Favorite")
        if coverage >= 2 and pct_std >= 0.18:
            labels.append("Market Split")
        if coverage == 1:
            labels.append("One-Source Flyer")

        out = {
            "mlbamId": player_id,
            "player": rep.get("player", rep.get("sourcePlayerName", "")),
            "normalizedName": rep.get("normalizedName", normalize_name(rep.get("sourcePlayerName", ""))),
            "team": rep.get("team", ""),
            "position": rep.get("position", rep.get("sourcePosition", "")),
            "age": rep.get("age", rep.get("sourceAge", "")),
            "dynastyCompositePct": round(mean_pct, 6),
            "sourceCoverage": coverage,
            "sourcesRanked": "|".join(sorted({row["sourceKey"] for row in rows})),
            "disagreementPctStdDev": round(pct_std, 6),
            "rankStdDev": round(rank_std, 3),
            "rankRange": rank_range,
            "bestSource": SOURCES[best["sourceKey"]]["name"],
            "bestRank": best.get("sourceRank", ""),
            "worstSource": SOURCES[worst["sourceKey"]]["name"],
            "worstRank": worst.get("sourceRank", ""),
            "highestSourcePct": round(max(pcts), 6),
            "lowestSourcePct": round(min(pcts), 6),
            "compositeConfidence": confidence,
            "contextLabels": "|".join(labels) if labels else "Neutral Context",
        }
        for source_key in SOURCES:
            source_rows = [row for row in rows if row["sourceKey"] == source_key]
            if source_rows:
                source_row = sorted(source_rows, key=lambda row: int(row["sourceRank"]))[0]
                out[f"{source_key}Rank"] = source_row.get("sourceRank", "")
                out[f"{source_key}Depth"] = source_row.get("sourceDepth", "")
                out[f"{source_key}Pct"] = round(float(source_row.get("sourceRankPct", 0)), 6)
            else:
                out[f"{source_key}Rank"] = ""
                out[f"{source_key}Depth"] = ""
                out[f"{source_key}Pct"] = ""
        composite_rows.append(out)

    composite_rows.sort(key=lambda row: (-float(row["dynastyCompositePct"]), -int(row["sourceCoverage"]), row["player"]))
    for idx, row in enumerate(composite_rows, start=1):
        row["dynastyCompositeRank"] = idx
    return composite_rows


def source_depth(rows: list[dict[str, Any]]) -> int:
    ranks = [to_int(row.get("sourceRank")) for row in rows]
    ranks = [rank for rank in ranks if rank is not None]
    return max(ranks) if ranks else len(rows)


def summarize_join(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row["joinStatus"] for row in rows)
    confidence = Counter(row["joinConfidence"] for row in rows)
    methods = Counter(row["joinMethod"] for row in rows)
    top_unmatched = [
        {
            "rank": row["sourceRank"],
            "player": row["sourcePlayerName"],
            "team": row["sourceTeam"],
            "position": row["sourcePosition"],
            "status": row["joinStatus"],
            "reason": row["reason"],
        }
        for row in rows
        if row["joinStatus"] != "joined" and (to_int(row["sourceRank"]) or 999999) <= 100
    ][:25]
    return {
        "rows": len(rows),
        "joined": statuses.get("joined", 0),
        "joinedPct": round(statuses.get("joined", 0) / len(rows), 4) if rows else 0,
        "unmatched": statuses.get("unmatched", 0),
        "ambiguous": statuses.get("ambiguous", 0),
        "confidence": dict(confidence),
        "joinMethods": dict(methods),
        "top100UnmatchedOrAmbiguous": top_unmatched,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--output-dir", default="data/shadow/dynasty-index")
    parser.add_argument("--join-review", default="")
    parser.add_argument("--dynasty-identity-map", default="data/shadow/dynasty-index/dynasty-player-identity-map.csv")
    parser.add_argument("--use-existing-raw", action="store_true", help="Read dated raw source captures if present instead of fetching them again.")
    parser.add_argument("--output-suffix", default="", help="Optional suffix for composite/manifest files, for example .clean-v0.")
    parser.add_argument("--explicitly-dropped-sources", nargs="*", default=[], choices=list(SOURCES.keys()))
    parser.add_argument("--sources", nargs="*", default=list(SOURCES.keys()), choices=list(SOURCES.keys()))
    args = parser.parse_args()

    capture_date = args.date
    captured_at = central_now().isoformat(timespec="seconds")
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    join_review_path = Path(args.join_review) if args.join_review else Path(f"/tmp/dynasty-index-join-review-{capture_date}.csv")

    rows_by_source: dict[str, list[dict[str, Any]]] = {}
    source_meta: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for source_key in args.sources:
        source = SOURCES[source_key]
        try:
            raw_path = raw_dir / f"{source_key}-{capture_date}.csv"
            if args.use_existing_raw and raw_path.exists():
                with raw_path.open(newline="") as file:
                    rows = list(csv.DictReader(file))
                meta = {
                    "sourcePublishedDate": rows[0].get("sourcePublishedDate", "") if rows else "",
                    "rawMeta": {"loadedFromExistingRaw": True},
                }
            else:
                text = fetch_text(source["url"])
                rows, meta = PARSERS[source_key](text, capture_date, captured_at)
                write_csv(raw_path, rows, RAW_FIELDS)
            if not rows:
                raise ValueError("parsed zero rows")
            rows_by_source[source_key] = rows
            source_meta[source_key] = meta
            source_meta[source_key]["rawFilePath"] = str(raw_path)
        except Exception as exc:  # noqa: BLE001 - report and continue source audit.
            warnings.append(f"{source['name']}: {exc}")
            source_meta[source_key] = {"error": str(exc), "rawFilePath": ""}

    if "fantasypros" not in rows_by_source:
        raise RuntimeError("FantasyPros anchor capture failed; stopping before composite.")

    dynasty_identity_map = Path(args.dynasty_identity_map) if args.dynasty_identity_map else None
    identity_index = load_identity_index(dynasty_identity_map)
    joined_rows, join_review = join_rows(rows_by_source, identity_index)
    write_csv(join_review_path, join_review, JOIN_REVIEW_FIELDS)

    depths = {source_key: source_depth(rows) for source_key, rows in rows_by_source.items()}
    included_sources: list[str] = []
    dropped_sources: list[str] = []
    join_by_source: dict[str, dict[str, Any]] = {}
    for source_key, rows in rows_by_source.items():
        source_review = [row for row in join_review if row["source"] == SOURCES[source_key]["name"]]
        summary = summarize_join(source_review)
        join_by_source[source_key] = summary
        if summary["joinedPct"] >= 0.75 and len(rows) >= MIN_ROWS_FOR_COMPOSITE:
            included_sources.append(source_key)
        else:
            dropped_sources.append(source_key)
    for source_key in args.explicitly_dropped_sources:
        if source_key not in included_sources and source_key not in dropped_sources:
            dropped_sources.append(source_key)

    included_joined = [row for row in joined_rows if row["sourceKey"] in included_sources]
    composite_rows = build_composite(included_joined, {key: depths[key] for key in included_sources})

    suffix = args.output_suffix
    composite_csv = output_dir / f"composite-{capture_date}{suffix}.csv"
    composite_json = output_dir / f"composite-{capture_date}{suffix}.json"
    manifest_path = output_dir / f"manifest-{capture_date}{suffix}.json"
    write_csv(composite_csv, composite_rows, COMPOSITE_FIELDS)
    write_json(composite_json, composite_rows)

    manifest_sources: list[dict[str, Any]] = []
    for source_key in [*args.sources, *[key for key in args.explicitly_dropped_sources if key not in args.sources]]:
        source_review = [row for row in join_review if row["source"] == SOURCES[source_key]["name"]]
        summary = join_by_source.get(source_key, {})
        explicitly_dropped = source_key in args.explicitly_dropped_sources and source_key not in rows_by_source
        manifest_sources.append(
            {
                "sourceName": SOURCES[source_key]["name"],
                "sourceUrl": SOURCES[source_key].get("pageUrl") or SOURCES[source_key]["url"],
                "captureDate": capture_date,
                "captureTimestampCentral": captured_at,
                "sourcePublishedDate": source_meta.get(source_key, {}).get("sourcePublishedDate", ""),
                "rankDepth": depths.get(source_key, 0),
                "rawRowCount": len(rows_by_source.get(source_key, [])),
                "joinedRowCount": summary.get("joined", 0),
                "unmatchedCount": summary.get("unmatched", 0),
                "ambiguousCount": summary.get("ambiguous", 0),
                "captureMethod": SOURCES[source_key]["captureMethod"],
                "rawFilePath": "" if explicitly_dropped else source_meta.get(source_key, {}).get("rawFilePath", ""),
                "cleanEnoughForWeeklyCollection": SOURCES[source_key]["cleanEnoughForWeeklyCollection"],
                "includedInComposite": source_key in included_sources,
                "exclusionReason": ""
                if source_key in included_sources
                else (
                    "explicitly excluded from clean v0"
                    if explicitly_dropped
                    else
                    source_meta.get(source_key, {}).get("error")
                    or (
                        f"raw row count below {MIN_ROWS_FOR_COMPOSITE} threshold"
                        if len(rows_by_source.get(source_key, [])) < MIN_ROWS_FOR_COMPOSITE
                        else "join rate below 75% threshold"
                    )
                ),
                "joinSummary": summary,
                "notes": source_meta.get(source_key, {}).get("rawMeta", {}),
                "top100UnmatchedOrAmbiguous": summary.get("top100UnmatchedOrAmbiguous", []),
            }
        )

    manifest = {
        "compositeDate": capture_date,
        "captureTimestampCentral": captured_at,
        "compositeRows": len(composite_rows),
        "includedSources": included_sources,
        "droppedSources": dropped_sources,
        "sourceCount": len(included_sources),
        "identityMapUsed": [
            str(dynasty_identity_map) if dynasty_identity_map else "",
            "data/shadow/dfs-salaries/dk-player-identity-map.csv",
            "data/cache/longball-threat-backtest/player-people-cache.json",
            "public/data/hr-distance-latest.json",
            "public/data/hot-dog-stand-latest.json",
            "data/shadow/storm_watch/snapshot_2026-06-05.json",
        ],
        "joinReviewPath": str(join_review_path),
        "compositeCsvPath": str(composite_csv),
        "compositeJsonPath": str(composite_json),
        "sources": manifest_sources,
        "warnings": warnings,
        "nextRecommendedAction": "Review unmatched/ambiguous top-100 rows and decide whether to promote a dynasty identity-map layer before automation.",
    }
    write_json(manifest_path, manifest)

    print(json.dumps({
        "captureDate": capture_date,
        "rawSources": {key: len(value) for key, value in rows_by_source.items()},
        "includedSources": included_sources,
        "droppedSources": dropped_sources,
        "joinBySource": join_by_source,
        "compositeRows": len(composite_rows),
        "outputs": {
            "compositeCsv": str(composite_csv),
            "compositeJson": str(composite_json),
            "manifest": str(manifest_path),
            "joinReview": str(join_review_path),
        },
        "warnings": warnings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
