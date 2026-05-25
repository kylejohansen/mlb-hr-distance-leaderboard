# The Long Ball Data Dictionary

This document describes the major frontend JSON fields used by The Long Ball.

| Field | Applies To | Definition | Source / Notes |
|---|---|---|---|
| `longballIndex` | Hitters | Plus-style score for home-run-quality contact per batted-ball event. 100 is league average among qualified hitters. | Computed by The Long Ball from LBI v1.2 components. |
| `xhrPerBbe` | Hitters | Adjusted expected home runs per batted-ball event. | Baseball Savant Home Run Tracker, Adjusted mode, divided by Statcast BBE. |
| `barrelRate` | Hitters | Share of batted balls classified as barrels. | Derived from Statcast batted-ball events. |
| `hardHitRate` | Hitters | Share of batted balls hit at 95 mph or harder. | Derived from Statcast batted-ball events. |
| `avgDistanceOnBarrels` | Hitters | Average projected distance on barreled batted balls. | Derived from Statcast batted-ball events. Null or downweighted for small barrel samples. |
| `actualDoubterHr` | Hitters | Count of actual home runs classified as Doubters. | Baseball Savant Home Run Tracker event detail joined to Statcast HR events. Doubters clear only 1-7 parks. |
| `cheapieRate` | Hitters | Actual Doubter HR divided by actual HR total. | Used by the CHEAPIES card when actual HR classification is available. |
| `hotDogIndex` | Pitchers | Plus-style score for pitchers allowing loud, home-run-quality contact. | Computed by The Long Ball from pitcher-side Home Run Tracker and Statcast fields. |
| `cookedPer100Bbe` | Pitchers | Hot Dog damage allowed per 100 batted balls in play. | Rate companion to Hot Dog Index. |
| `hrCapableBbeAllowed` | Pitchers | Count of batted balls allowed with home-run potential in at least one MLB park. | Baseball Savant Home Run Tracker classifications. |
| `noDoubtersAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear all 30 MLB parks. | Baseball Savant Home Run Tracker. |
| `mostlyGoneAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear many parks, but not all. | Baseball Savant Home Run Tracker. |
| `doubtersAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear only a small number of parks. | Baseball Savant Home Run Tracker. |

## Data Files

- `/data/hr-distance-latest.json`: current Longball Index data and daily longball features.
- `/data/longball-index-YYYY.json`: season-specific Longball Index data.
- `/data/hot-dog-stand-latest.json`: current Hot Dog Stand pitcher data.
- `/data/hot-dog-index-YYYY.json`: season-specific Hot Dog Index data.
- `/data/daily-features-YYYY.json`: archived Daily Dong, Hot Dog Robbery, and Cheapest Dong selections by game date.
- `/data/weekly-movers-latest.json`: generated weekly movement report when prior snapshots exist.

## Stable Concept Links

- Longball Index: `https://thelongball.app/about/longball-index`
- Hot Dog Index: `https://thelongball.app/about/hot-dog-index`
- Cheapies: `https://thelongball.app/about/cheapies`
- Daily Dong: `https://thelongball.app/about/daily-dong`
- Hot Dog Robbery: `https://thelongball.app/about/hot-dog-robbery`
- Cheapest Dong: `https://thelongball.app/about/cheapest-dong`
