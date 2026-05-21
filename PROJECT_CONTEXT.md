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
Meatball Tracker). The fun is the differentiator. Do not try to out-Savant
Savant. Out-personality them.

## Audience

Primary audience: the stat-nerd analytics crowd. People who use FanGraphs
and Baseball Savant regularly, who care about xwOBA, who argue about
wRC+. The site should feel like one of them. Methodology pages should
be rigorous. The fun shouldn't undermine the math.

Secondary audience: casual fans who follow baseball Twitter and would
share a "Walker Buehler has a Meatball Tracker problem" graphic. The
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

## The Meatball Tracker — Methodology

**Definition of a meatball:**
A pitch that meets ALL of the following:
1. Located in the Heart zone (Savant's official attack_zone classification,
   obtained via hfNewZones=1|2|3|4|5|6|7|8|9| filter)
2. Thrown below the pitcher's 25th-percentile velocity for that pitch type
3. Resulted in a home run (events = 'home_run')

The velocity-percentile gate requires the pitcher to have thrown ≥15 of
that pitch type in the cached window. Pitch types below that threshold
are not eligible for meatball classification.

**Four leaderboards:**

1. **Hall of Shame** — sorted by raw meatballs_allowed count. Qualifier:
   5+ HRs allowed. Volume Cooks.

2. **Cookie Reliance** — sorted by meatball_reliance (meatballs_allowed
   / total_hrs_allowed). Qualifier: 8+ HRs allowed (higher to reduce
   small-sample noise on a rate stat).

3. **Batting Practice** — sorted by avg_ev_on_hrs_allowed. Qualifier:
   5+ HRs allowed.

4. **Over the Plate** — sorted by heart_zone_hr_rate (NOT requiring
   below-25th-percentile velocity, just Heart-zone HRs). Qualifier:
   8+ HRs allowed.

**Why Heart-zone HR rate differs from Cookie Reliance:**
Cookie Reliance requires the velocity gate. Heart-zone HR rate doesn't.
A pitcher who throws a 99mph fastball down the middle and gives up
a HR didn't throw a "cookie" (their velocity was elite), but it WAS
in the Heart zone. The two stats together let users see "where" vs
"how badly" a pitcher missed.

**Data source:** Baseball Savant Statcast via pybaseball, filtered through
Savant's official hfNewZones attack_zone classification. We validated
that the local coordinate approximation (abs(plate_x) <= 0.558 with
vertical margins) has only 87.58% agreement with Savant. Even the better
Savant-fit version (vertical margin 0.185) hits 99.45% agreement, which
is not as defensible as using Savant's classification directly. Always
use the official Savant filter.

## Data Pipeline Architecture

**Canonical cache:** data/raw/statcast-pitches.csv

This is the source of truth for BOTH LBI and Meatball Tracker. The
cache holds pitch-level Statcast data (not just BBE) because the
Meatball Tracker needs pitch-type velocity distributions, which require
all pitches not just batted balls.

**LBI pipeline:** Derives BBE rows from the canonical cache, computes
percentiles, outputs to public/data/hr-distance-latest.json.

**Meatball pipeline:** Filters the canonical cache for HRs allowed,
joins with pitcher arsenal velocity distributions, computes aggregations,
outputs to public/data/meatball-tracker-latest.json.

**Important invariant:** LBI output must remain numerically identical
across pipeline refactors. If you touch the cache or LBI script, run
scripts/diagnose_lbi_refactor.py against a saved pre-refactor JSON to
confirm output is unchanged.

**Refresh schedule:** GitHub Actions runs daily to refresh the pitch
cache, regenerate LBI JSON, and regenerate Meatball Tracker JSON.

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
- --color-mustard: #d4a418 (meatball tracker accents)
- --color-mustard-deep: #8a6f10 (mustard text)
- --color-mustard-soft: #f5e4a8 (Over the Plate card bg)
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

Meatball Tracker section: Own header + tagline + explainer. Then 2x2
grid (1fr 1fr) of four cards: Hall of Shame (red), Reliance (black),
Batting Practice (cream/dashed), Over the Plate (mustard).

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
Jacked Up (top distances) and Hall of Shame (top meatball counts). The
visual irony works: red is celebration for hitters, shame for pitchers,
but in both cases it's the "most prominent" treatment.

**Black cards** = the authoritative stat. The "Bloomberg terminal" feel.
Used for LBI Leaders and Cookie Reliance. Headlines in Courier New
monospace, accent color (gold for LBI, mustard for Reliance). These
are the cards where the proprietary number lives.

**Cream/dashed cards** = the niche or "specific weirdness" view. Used
for Cheapies (hitters benefiting from short porches) and Batting Practice
(pitchers giving up the hardest contact). Cream background, dashed
border, muted typography.

**Mustard cards** = the fourth variant, added for the Meatball Tracker
section. Only used for Over the Plate. The literal mustard reference
ties to "served with mustard" tagline. Distinct from the other three
but still in the warm palette.

## Editorial Voice

**Site-level:** "Digging the data behind the distance." Playful but
substantive. References the 1999 Nike "Chicks dig the longball" ad
without being on the nose.

**LBI:** Serious, methodologically rigorous. Avoid jokes in the LBI
explanation. This is the credibility center of the site.

**Cheapies card:** Mocking but specific. "Park Effects Abused." Targets
hitters whose HRs lean on short porches. The Yankees, Phillies, Reds
fans will be annoyed; this is fine.

**Meatball Tracker:** Meanest section of the site. Pitcher accountability.
Eyebrow copy in the four cards: VOLUME COOKS, THE COOKIE RATIO, WHEN
THEY HIT THEY HIT, RIGHT DOWN BROADWAY. Tagline: "Served with mustard."

The tone test: would your worst critic on Pitcher Twitter retweet a
Hall of Shame screenshot and say "this is actually fair"? If yes, the
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
- Meatball Tracker frontend (this implementation)
- "Updated X hours ago" timestamp display

Medium-term:
- About page with methodology details
- Stat-level changelog (v1.0 → v1.1 → v1.2 history)
- Stadium-neutral toggle for the entire leaderboard
- Launch blog post

Longer-term:
- "Build Your Own LBI" weight slider (user-configurable)
- Matchup Cards (click a HR to see "Schwarber hit a 460ft no-doubter
  off Pitcher X, +1.4 LBI, +1 Meatball")
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
