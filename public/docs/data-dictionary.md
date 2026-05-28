# The Long Ball Data Dictionary

This document describes the major frontend JSON fields used by The Long Ball.

| Field | Applies To | Definition | Source / Notes |
|---|---|---|---|
| `longballIndex` | Hitters | Plus-style score for home-run-quality contact per batted-ball event. 100 is league average among qualified hitters. | Computed by The Long Ball from LBI v1.3 components. |
| `xhrPerBbe` | Hitters | Adjusted expected home runs per batted-ball event. | Baseball Savant Home Run Tracker, Adjusted mode, divided by Statcast BBE. |
| `barrelRate` | Hitters | Share of batted balls classified as barrels. | Derived from Statcast batted-ball events. |
| `hrWindowThunderBbe` | Hitters | Count of BBE hit 105+ mph with launch angle between 25 and 40 degrees. | Numerator for HR-Window Thunder Rate. |
| `hrWindowThunderRate` | Hitters | Share of BBE hit 105+ mph with launch angle between 25 and 40 degrees. | LBI v1.3 component. Measures home-run-shaped top-end contact. |
| `hardHitRate` | Hitters | Share of batted balls hit at 95 mph or harder. | Derived from Statcast batted-ball events. |
| `avgDistanceOnBarrels` | Hitters | Average projected distance on barreled batted balls. | Reference stat only. It is not part of LBI v1.3. |
| `pulledAirBbe` | Hitters | Count of pulled batted balls with launch angle between 15 and 45 degrees. | Derived from Statcast batted-ball events using batter handedness and hit-coordinate pull-side classification. Context stat only. |
| `crushedPulledAirBbe` | Hitters | Count of pulled-air batted balls hit at 105 mph or harder. | Numerator for Pull-Air Juice. Context stat only. |
| `pullAirJuice` | Hitters | Pulled-air balls hit 105+ mph per plate appearance. | Pull-Air Juice measures how often a hitter yanks loud airborne contact. It is a context stat, not currently part of LBI. |
| `pullAirJuicePer100Pa` | Hitters | Pulled-air balls hit 105+ mph per 100 PA. | Display version of Pull-Air Juice for player detail views. |
| `actualDoubterHr` | Hitters | Count of actual home runs classified as Doubters. | Baseball Savant Home Run Tracker event detail joined to Statcast HR events. Doubters clear only 1-7 parks. |
| `cheapieRate` | Hitters | Actual Doubter HR divided by actual HR total. | Used by the CHEAPIES card when actual HR classification is available. |
| `hotDogIndex` | Pitchers | Plus-style score for pitchers allowing loud, home-run-quality contact. | Computed by The Long Ball from pitcher-side Home Run Tracker and Statcast fields. |
| `cookedPer100Bbe` | Pitchers | Hot Dog damage allowed per 100 batted balls in play. | Rate companion to Hot Dog Index. |
| `hrCapableBbeAllowed` | Pitchers | Count of batted balls allowed with home-run potential in at least one MLB park. | Baseball Savant Home Run Tracker classifications. |
| `noDoubtersAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear all 30 MLB parks. | Baseball Savant Home Run Tracker. |
| `mostlyGoneAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear many parks, but not all. | Baseball Savant Home Run Tracker. |
| `doubtersAllowed` | Pitchers | Count of HR-capable batted balls allowed that would clear only a small number of parks. | Baseball Savant Home Run Tracker. |
| `dailyDong` | Daily Features | The day's loudest actual home run. | Selected from actual HR events on the latest available game date using parks-cleared strength, distance, and exit velocity. |
| `hotDogRobbery` | Daily Features | The strongest HR-capable batted ball that stayed in the yard. | Selected from Home Run Tracker event rows joined to Statcast where the outcome was not an actual HR. |
| `cheapestDong` | Daily Features | The flimsiest actual home run that still counted. | Prefers actual Doubter HRs, then lowest parks-cleared or shortest actual HR when no Doubter is available. |

## Data Files

- `/data/hr-distance-latest.json`: current Longball Index data and daily longball features.
- `/data/longball-index-YYYY.json`: season-specific Longball Index data.
- `/data/hot-dog-stand-latest.json`: current Hot Dog Stand pitcher data.
- `/data/hot-dog-index-YYYY.json`: season-specific Hot Dog Index data.
- `/data/daily-features-YYYY.json`: archived Daily Dong, Hot Dog Robbery, and Cheapest Dong selections by game date.
- `/data/tale-of-the-tape/YYYY-MM-DD.json`: date-stamped Daily Dong, Hot Dog Robbery, and Cheapest Dong archive for one game date.
- `/data/weekly-movers-latest.json`: generated weekly movement report when prior snapshots exist.

## Stable Concept Links

- Longball Index: `https://thelongball.app/about/longball-index`
- Hot Dog Index: `https://thelongball.app/about/hot-dog-index`
- Cheapies: `https://thelongball.app/about/cheapies`
- Daily Dong: `https://thelongball.app/about/daily-dong`
- Hot Dog Robbery: `https://thelongball.app/about/hot-dog-robbery`
- Cheapest Dong: `https://thelongball.app/about/cheapest-dong`
