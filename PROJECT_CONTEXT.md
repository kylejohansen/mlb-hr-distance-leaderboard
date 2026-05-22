# thelongball.app — Project Context for Codex

This document captures the full design philosophy, technical architecture,
and current state of thelongball.app. Read this before making changes so
your work stays consistent with established patterns.

## Project Overview

**Domain:** thelongball.app
**Tagline (site-level):** "Digging the data behind the distance."
**Tagline (stat-level):** "Pure home-run quality, stadium-neutral."

The site is a baseball analytics destination built around a proprietary
metric (the Longball Index, LBI) and editorial framing of home run data.
Built originally as a hobby project, potentially monetizable later.

**The moat:** Editorial voice. Baseball Savant already has free, comprehensive
leaderboards. FanGraphs has custom metrics. What thelongball.app does
differently is treat the same data with personality — celebration on one
side (Jacked Up, top LBI scores) and mockery on the other (Cheapies,
The Hot Dog Stand). The fun is the differentiator. Do not try to out-Savant
Savant. Out-personality them.

## Audience

Primary audience: the stat-nerd analytics crowd. People who use FanGraphs
and Baseball Savant regularly, who care about xwOBA, who argue about
wRC+. The site should feel like one of them. Methodology pages should
be rigorous. The fun shouldn't undermine the math.

Secondary audience: casual fans who follow baseball Twitter and would
share a "Walker Buehler got cooked at The Hot Dog Stand" graphic. The
editorial voice serves them too.

## The Longball Index (LBI) — Methodology

**Current version: v1.2 — Stadium-Neutral, Anchored on xHR/BBE**

LBI measures pure home-run quality, stadium-neutral. It is a per-contact
measure (rate-based, not counting). 100 = league average, scaled like wRC+.
Elite scores reach 180-190. Below average is below 100. Distribution
roughly matches wRC+ in shape.

**Components (v1.2):**

For players with 10+ barrels:
- Adjusted xHR/BBE — 60% (anchor)
- Barrel% — 20%
- Avg Distance on Barrels — 12.5%
- Hard Hit% — 7.5%

For players with 5-9 barrels (Distance becomes less reliable):
- Adjusted xHR/BBE — 67.5%
- Barrel% — 17.5%
- Avg Distance on Barrels — 7.5%
- Hard Hit% — 7.5%

For players with fewer than 5 barrels (Distance dropped entirely):
- Adjusted xHR/BBE — 75%
- Barrel% — 17.5%
- Hard Hit% — 7.5%

**Scoring math:**
- Normal-score percentile mapping (z-score based)
- 50th percentile → 100, 90th percentile → ~150
- Percentiles clipped to [0.01, 0.99] to handle extremes
- Scores uncapped (elite seasons can exceed 200)

**Qualifier:** BBE ≥ max(50, team_games × 1.5)

**Data source:** Adjusted xHR/BBE comes from Baseball Savant's Home Run
Tracker (cat=adj_xhr). Adjusted mode accounts for park dimensions and
environmental context through Savant's park-factor model.

**Sweet Spot% is explicitly excluded.** It was in v1.0 and v1.1 but
caused inflation of weak line-drive hitters. It measures launch angle
without regard for velocity, so a 78mph line drive at 22° counted
the same as a 108mph line drive at 22°. Removed in v1.2. Sweet Spot%
remains visible as a reference stat in the leaderboard table but is
NOT part of LBI calculation.

**LA Sweet Spot% is also explicitly excluded.** The user investigated
this separately and confirmed the top-13 by LA SwSp% (Troy Johnston,
Hyeseong Kim, Brandon Marsh, etc.) is dominated by weak-contact line-drive
hitters. Including it would re-introduce the exact bias we removed.

**Stress-test players (use these for regression tests):**
- Kyle Schwarber: ~181 (elite power)
- Munetaka Murakami: ~187 (top of leaderboard)
- Aaron Judge: ~179 (elite, even in HR-friendly park)
- James Wood: ~173 (elite in neutral park, validates xHR isn't over-correcting)
- Alex Bregman: ~90 (Fenway-aided, correctly below average for power)
- Nico Hoerner: ~57 (contact-first, correctly low)
- Ke'Bryan Hayes: ~55 (mediocre contact + brutal xHR, correctly low)

## The Hot Dog Stand — Methodology

The Hot Dog Stand is the pitcher-accountability side of the site. The
Hot Dog Index measures loud, home-run-quality contact allowed by pitchers
using Baseball Savant Home Run Tracker and Statcast event data.

**Candidate output fields:**
- hotDogIndex
- hrCapableBbeAllowed
- noDoubtersAllowed
- mostlyGoneAllowed
- doubtersAllowed
- avgExitVelocityAllowed
- avgDistanceAllowed
- maxExitVelocityAllowed
- maxDistanceAllowed
- worstServedEvent

**Four leaderboards:**

1. **Top Dogs** — sorted by Hot Dog Index. This is the primary pitcher
   accountability card.

2. **Footlongs** — sorted by HR-capable BBE allowed. This rewards volume:
   the pitchers serving up the most batted balls with home-run potential.

3. **Extra Mustard** — sorted by no-doubters allowed. These are the
   loudest, least park-dependent blasts allowed.

4. **Cooked** — sorted by maximum exit velocity allowed on home runs.
   This is the "who got hit the hardest" view.

**Data source:** Baseball Savant Home Run Tracker adjusted pitcher view
for HR-capable classifications, joined to Statcast event data from the
canonical pitch cache for exit velocity, distance, and worst-served-event
context.

## Data Pipeline Architecture

**Canonical cache:** data/raw/statcast-pitches.csv

This is the source of truth for BOTH LBI and The Hot Dog Stand. The
cache holds pitch-level Statcast data (not just BBE), which keeps the
pitcher-accountability feature additive without changing the hitter
leaderboard architecture.

**LBI pipeline:** Derives BBE rows from the canonical cache, computes
percentiles, outputs to public/data/hr-distance-latest.json.

**Hot Dog pipeline:** Joins Baseball Savant Home Run Tracker pitcher
aggregates to HR events allowed from the canonical cache, computes Hot Dog
Index and supporting leaderboards, and outputs to
public/data/hot-dog-stand-latest.json.

**Important invariant:** LBI output must remain numerically identical
across pipeline refactors. If you touch the cache or LBI script, run
scripts/diagnose_lbi_refactor.py against a saved pre-refactor JSON to
confirm output is unchanged.

**Refresh schedule:** GitHub Actions runs daily to refresh the pitch
cache, regenerate LBI JSON, and regenerate Hot Dog Stand JSON.

## Frontend Architecture

**Tech stack:** Vanilla HTML/CSS/JavaScript with Vite for the build.
No React, no framework. Single-page app, hash-free routing not needed.

**Files:**
- index.html (minimal entry, loads main.js)
- src/main.js (all rendering, state, data fetching)
- src/style.css (all styles)
- public/data/ (JSON outputs)
- public/favicon.svg (red square + white "L")

**Design system:**

Colors (CSS variables in style.css):
- --color-cream: #faf4e6 (background)
- --color-cream-soft: #f0e9d4 (cheapies card bg)
- --color-red: #b03524 (brand red)
- --color-red-deep: #8a4520 (cheapies value text)
- --color-ink: #1a1a1a (black backgrounds, ink)
- --color-text: #3d3a30 (body on cream)
- --color-muted: #6a6555 (secondary text)
- --color-gold: #f5c542 (LBI value text on black cards)
- --color-mustard: #d4a418 (Hot Dog Stand accents)
- --color-mustard-deep: #8a6f10 (mustard text)
- --color-mustard-soft: #f5e4a8 (Cooked card bg)
- --color-tan: #b8a878 (cheapies borders)
- --color-tan-soft: #d4c8a8 (light borders)
- --color-tan-deep: #8a7530 (cheapies meta text)

Typography:
- Inter (body, 400/700/900 weights)
- Archivo Black (display, ALL CAPS headlines)
- Georgia italic (taglines, subtitles in serif)
- Courier New monospace (stat values on dark cards, team codes)

Fonts are loaded via Google Fonts @import at the top of style.css.

**Layout:**

Hero section: Title + tagline left, methodology meta right. Flexbox.

Top three-card grid (hitters): Jacked Up (red), LBI Leaders (black),
Cheapies (cream/dashed). 1fr 1.1fr 1fr (middle is slightly wider).

Hot Dog Stand section: Own header + tagline + explainer. Then 2x2
grid (1fr 1fr) of four cards: Top Dogs (red), Footlongs (black),
Extra Mustard (cream/dashed), Cooked (mustard).

Leaderboard table: Below all cards, sortable, searchable, filterable.

Future section: "On deck" preview of upcoming features.

**Card row template:**

All feature card rows use the same skeleton:
```
[rank] [player name + meta] [headline value]
```

The rank is bold Archivo Black. The player name is bold Inter. The meta
line is small and dimmed (team + context). The headline value is
prominent — either Archivo Black for distance/percentage/count values,
or Courier New monospace for "stat number" displays (LBI score, Cookie
Reliance ratio).

## Visual Hierarchy of Cards

Three visual treatments are established and reused intentionally:

**Red cards** = celebration or volume. The "loud" treatment. Used for
Jacked Up (top distances) and Top Dogs (top pitcher accountability scores). The
visual irony works: red is celebration for hitters, shame for pitchers,
but in both cases it's the "most prominent" treatment.

**Black cards** = the authoritative stat. The "Bloomberg terminal" feel.
Used for LBI Leaders and Footlongs. Headlines in Courier New
monospace, accent color (gold for LBI, mustard for Reliance). These
are the cards where the proprietary number lives.

**Cream/dashed cards** = the niche or "specific weirdness" view. Used
for Cheapies (hitters benefiting from short porches) and Extra Mustard
(pitchers giving up the hardest contact). Cream background, dashed
border, muted typography.

**Mustard cards** = the fourth variant, used for Cooked. The literal
mustard reference ties to the ballpark-food framing. Distinct from the
other three but still in the warm palette.

## Editorial Voice

**Site-level:** "Digging the data behind the distance." Playful but
substantive. References the 1999 Nike "Chicks dig the longball" ad
without being on the nose.

**LBI:** Serious, methodologically rigorous. Avoid jokes in the LBI
explanation. This is the credibility center of the site.

**Cheapies card:** Mocking but specific. "Park Effects Abused." Targets
hitters whose HRs lean on short porches. The Yankees, Phillies, Reds
fans will be annoyed; this is fine.

**The Hot Dog Stand:** Meanest section of the site. Pitcher accountability
with ballpark-food language. Preferred labels include Hot Dog Index, Top
Dogs, Footlongs, Extra Mustard, Cooked, The Daily Dog, and Worst Served.

The tone test: would your worst critic on Pitcher Twitter retweet a
Top Dogs screenshot and say "this is actually fair"? If yes, the
voice is right. If they're mad, you went too far.

## What's Shipped

- LBI v1.2 leaderboard, sortable/filterable/searchable
- Hero with new "LONGBALL index." typography
- Three-card hitter section (Jacked Up, LBI Leaders, Cheapies)
- Methodology copy
- Daily auto-refresh via GitHub Actions
- Favicon (red square + white L)

## What's Next (Roadmap)

Immediate:
- Hot Dog Stand frontend and data polish
- "Updated X hours ago" timestamp display

Medium-term:
- About page with methodology details
- Stat-level changelog (v1.0 → v1.1 → v1.2 history)
- Stadium-neutral toggle for the entire leaderboard
- Launch blog post

Longer-term:
- "Build Your Own LBI" weight slider (user-configurable)
- Matchup Cards (click a HR to see "Schwarber hit a 460ft no-doubter
  off Pitcher X, +1.4 LBI, +1 Hot Dog Index context")
- Companion stat: Longball Threat Index (LTI) = LBI × contact rate.
  Answers "actual HR threat per PA" vs LBI's "quality per contact".
- v2.0 review of LBI at end of season

## Critical Constraints

1. **LBI output stability.** Never accidentally change LBI scores when
   refactoring infrastructure. Always run scripts/diagnose_lbi_refactor.py.

2. **Use Savant as source of truth.** For Heart-zone classification,
   use Savant's hfNewZones filter, not a local coordinate approximation.
   For xHR, use Savant's adj_xhr (Home Run Tracker), not a homemade
   prediction.

3. **Version transparency.** Methodology changes get documented in a
   changelog. v1.0 → v1.1 → v1.2 progression is a credibility asset,
   not something to hide.

4. **Per-contact framing.** LBI is rate-based per BBE. It doesn't
   factor in strikeouts. When this question comes up in user feedback,
   the answer is: LBI measures quality, LTI (future) will measure
   PA-level threat.

5. **Editorial restraint.** The fun is in the framing, not in the
   methodology pages. Methodology should sound serious so the math
   gets trusted.
