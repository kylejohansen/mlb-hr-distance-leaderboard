#!/usr/bin/env python3
"""Update internal Stack Watch HR park-factor context from Baseball Savant.

This is an internal maintenance helper for the private Stack Watch prototype.
It reads Baseball Savant's Statcast Park Factors page and uses only the
HR-specific factor (`index_hr`). Do not use overall park factor, run factor, or
carry/distance factor for Stack Watch park tags.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


OUTPUT_PATH = Path("data/park-factors.json")
SAVANT_URL = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update internal Stack Watch HR park factors.")
    parser.add_argument("--year", default="2026", help="Savant park-factor season.")
    parser.add_argument("--rolling", default="1", help="Savant rolling-years selector.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def hr_park_tag(value: Any) -> str | None:
    if value is None:
        return None
    factor = float(value)
    if factor >= 115:
        return "Significant HR Boost"
    if factor >= 105:
        return "Slight HR Boost"
    if factor >= 97:
        return "Neutral"
    if factor >= 90:
        return "Slight HR Suppressor"
    if factor >= 80:
        return "Significant HR Suppressor"
    return "Major HR Suppressor"


def savant_park_factor_url(year: str, rolling: str) -> str:
    params = {
        "batSide": "",
        "condition": "All",
        "parks": "mlb",
        "rolling": rolling,
        "stat": "index_wOBA",
        "type": "year",
        "year": year,
    }
    return f"{SAVANT_URL}?{urlencode(params)}"


def fetch_html(url: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (OSError, urllib.error.URLError, TimeoutError):
        result = subprocess.run(
            ["curl", "-fsSL", "-A", "Mozilla/5.0", url],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


def embedded_park_data(html: str) -> list[dict[str, Any]]:
    match = re.search(r"var\s+data\s*=\s*(\[.*?\]);", html, flags=re.S)
    if not match:
        raise RuntimeError("Could not find embedded Baseball Savant park-factor data.")
    data = json.loads(match.group(1))
    if not isinstance(data, list):
        raise RuntimeError("Embedded Baseball Savant park-factor data was not a list.")
    return data


def build_output(rows: list[dict[str, Any]], year: str, rolling: str, source_url: str) -> dict[str, Any]:
    parks = []
    for row in rows:
        venue_id = row.get("venue_id")
        venue_name = row.get("venue_name")
        hr_factor = row.get("index_hr")
        if venue_id is None or not venue_name or hr_factor in {None, ""}:
            continue
        factor = float(hr_factor)
        parks.append(
            {
                "venueId": int(venue_id),
                "venueName": str(venue_name),
                "team": row.get("name_display_club"),
                "hrFactor": round(factor, 1),
                "hrTag": hr_park_tag(factor),
                "source": "Baseball Savant Statcast Park Factors index_hr",
                "season": int(year),
                "rollingWindow": f"{rolling} year" if rolling == "1" else f"{rolling} years",
                "pa": int(row["n_pa"]) if str(row.get("n_pa") or "").isdigit() else None,
            }
        )
    parks.sort(key=lambda park: park["venueName"])
    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Baseball Savant Statcast Park Factors index_hr",
        "sourceUrl": source_url,
        "season": int(year),
        "rollingWindow": f"{rolling} year" if rolling == "1" else f"{rolling} years",
        "notes": "Internal Stack Watch context. Uses HR-specific Baseball Savant park factor only; do not use overall/run park factor.",
        "tagThresholds": {
            "significantHrBoost": ">= 115",
            "slightHrBoost": "105-114",
            "neutral": "97-104",
            "slightHrSuppressor": "90-96",
            "significantHrSuppressor": "80-89",
            "majorHrSuppressor": "< 80",
        },
        "parks": parks,
    }


def main() -> None:
    args = parse_args()
    url = savant_park_factor_url(args.year, args.rolling)
    html = fetch_html(url)
    rows = embedded_park_data(html)
    output = build_output(rows, args.year, args.rolling, url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote {len(output['parks'])} HR park factors to {args.output}")
    for park in sorted(output["parks"], key=lambda item: item["hrFactor"], reverse=True)[:5]:
        print(f"- {park['venueName']}: {park['hrFactor']:.0f} ({park['hrTag']})")


if __name__ == "__main__":
    main()
