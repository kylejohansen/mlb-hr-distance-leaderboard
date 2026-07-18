# The Long Ball Data Dictionary

This document describes the major frontend JSON fields used by The Long Ball.

| Field | Applies To | Definition | Source / Notes |
|---|---|---|---|
| `longballIndex` | Hitters | LBI v1.4 long-ball contact quality index. 100 is league average among qualified hitters. | 50% Thump and 50% Artistry. Descriptive, not predictive. |
| `thumpIndex` | Hitters | Long-ball authority from exit velocity and park-neutral estimated distance, accumulated per PA. 100 is average. | LBI v1.4 scoring axis. |
| `improbabilityIndex` | Hitters | Stable internal JSON field for the public Artistry axis: how rare/difficult the hitter's spray-direction x launch-angle route to long-ball contact was, averaged per qualifying long-ball event with shrinkage. 100 is average. | LBI v1.4 scoring axis; displayed publicly as Artistry. |
| `longBallEventCount` | Hitters | Count of qualifying LBI v1.4 long-ball events. | Actual over-the-fence HRs plus non-HR contact that would clear 8+ standard parks. |
| `lbiArchetype` | Hitters | Official public display label: Apex Power, Thumper, Specialist, or Balanced Power. | Derived from Thump and Artistry with sample gating. |
| `sprayDiversity` | Hitters | Spread of qualifying long balls across pull, center, and opposite field. | Read-only context for LBI v1.4 archetypes. |
| `xhrPerBbe` | Hitters | Adjusted expected home runs per batted-ball event. | Baseball Savant Home Run Tracker, Adjusted mode, divided by Statcast BBE. Context only; not part of LBI v1.4. |
| `barrelRate` | Hitters | Share of batted balls classified as barrels. | Derived from Statcast batted-ball events. |
| `hrWindowThunderBbe` | Hitters | Count of BBE hit 105+ mph with launch angle between 25 and 40 degrees. | Numerator for HR-Window Thunder Rate. |
| `hrWindowThunderRate` | Hitters | Share of BBE hit 105+ mph with launch angle between 25 and 40 degrees. | Context stat only; not part of LBI v1.4. |
| `hardHitRate` | Hitters | Share of batted balls hit at 95 mph or harder. | Context stat only; not part of LBI v1.4. |
| `avgDistanceOnBarrels` | Hitters | Average projected distance on barreled batted balls. | Reference stat only. It is not part of LBI v1.4. |
| `pulledAirBbe` | Hitters | Count of pulled batted balls with launch angle between 15 and 45 degrees. | Derived from Statcast batted-ball events using batter handedness and hit-coordinate pull-side classification. Context stat only. |
| `crushedPulledAirBbe` | Hitters | Count of pulled-air batted balls hit at 105 mph or harder. | Numerator for Pull-Air Juice. Context stat only. |
| `pullAirJuice` | Hitters | Pulled-air balls hit 105+ mph per plate appearance. | Pull-Air Juice measures how often a hitter yanks loud airborne contact. It is a context stat, not currently part of LBI. |
| `pullAirJuicePer100Pa` | Hitters | Pulled-air balls hit 105+ mph per 100 PA. | Display version of Pull-Air Juice for player detail views. |
| `actualDoubterHr` | Hitters | Count of actual home runs classified as Doubters. | Baseball Savant Home Run Tracker event detail joined to Statcast HR events. Doubters clear only 1-7 parks. |
| `cheapieRate` | Hitters | Actual Doubter HR divided by actual HR total. | Used by the CHEAPIES card when actual HR classification is available. |
| `hotDogIndex` | Pitchers | Legacy cumulative damage field retained for payload compatibility. | Not displayed publicly. Alias of `hotDogDamageAllowed` in v1.2+ payloads. |
| `hotDogDamageAllowed` | Pitchers | Legacy cumulative damage field retained for compatibility. | Not displayed publicly. |
| `xLB` | Pitchers | Expected Long Balls v0.2 total over terminal BBE. | Internal cumulative companion; public displays use `xLBPer9`. |
| `xLBPerBbe` | Pitchers | Expected Long Balls allowed per terminal BBE. | Contact-quality context. |
| `xLBPer9` | Pitchers | Expected Long Balls allowed per nine innings. | `xLB * 27 / pitcherOuts`. |
| `pitcherOuts` | Pitchers | Official MLB pitcher outs recorded. | Denominator for `xLBPer9`. |
| `inningsPitched` | Pitchers | Official MLB innings-pitched display value. | Display/context only; xLB/9 is calculated from outs. |
| `longBallGap` | Pitchers | Actual HR allowed minus xLB. | Positive means actual HR exceed contact-quality expectation. |
| `gettingCookedIndex` | Pitchers | Getting Cooked v1.3 HR-capable contact rate allowed score. 100 is average among qualified pitchers. | `100 * pitcher HR-capable BBE rate allowed / qualified-pitcher average HR-capable BBE rate allowed`. |
| `cookedPlus` | Pitchers | Backward-compatible alias for `gettingCookedIndex`. | Public displays should treat this as Getting Cooked. |
| `premiumDamagePer100Bbe` | Pitchers | Legacy cumulative damage units per 100 batted balls in play. | Retained for compatibility; not displayed publicly. |
| `gettingCookedPer100Bbe` | Pitchers | HR-capable batted balls allowed per 100 BBE. | Raw companion for Getting Cooked in v1.3 payloads. |
| `hrCapableBbePer100` | Pitchers | HR-capable batted balls allowed per 100 BBE. | Explicit v1.3 alias for `gettingCookedPer100Bbe`. |
| `cookedPer100Bbe` | Pitchers | Backward-compatible alias for `premiumDamagePer100Bbe`. | Kept for older consumers. |
| `legacyCooked` | Pitchers | Backward-compatible alias for `premiumDamagePer100Bbe`. | Preserved for comparison only. |
| `hrCapableBbeAllowed` | Pitchers | Count of batted balls allowed with home-run potential in at least one MLB park. | Baseball Savant Home Run Tracker classifications. |
| `hrWindowThunderBbeAllowed` | Pitchers | Count of BBE allowed at 105+ mph with launch angle between 25 and 40 degrees. | Numerator for HR-Window Thunder Allowed. |
| `hrWindowThunderRateAllowed` | Pitchers | Share of BBE allowed at 105+ mph with launch angle between 25 and 40 degrees. | Pitcher-card context. |
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
- `/data/hot-dog-index-YYYY.json`: season-specific Hot Dog Stand data.
- `/data/daily-features-YYYY.json`: archived Daily Dong, Hot Dog Robbery, and Cheapest Dong selections by game date.
- `/data/tale-of-the-tape/YYYY-MM-DD.json`: date-stamped Daily Dong, Hot Dog Robbery, and Cheapest Dong archive for one game date.
- `/data/weekly-movers-latest.json`: generated weekly movement report when prior snapshots exist.

## Stable Concept Links

- Longball Index: `https://thelongball.app/about/longball-index`
- Hot Dog Stand methodology: `https://thelongball.app/about/hot-dog-index`
- Cheapies: `https://thelongball.app/about/cheapies`
- Daily Dong: `https://thelongball.app/about/daily-dong`
- Hot Dog Robbery: `https://thelongball.app/about/hot-dog-robbery`
- Cheapest Dong: `https://thelongball.app/about/cheapest-dong`
