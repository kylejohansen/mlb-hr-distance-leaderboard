# The Long Ball

Digging the data behind the distance.

The Long Ball is a small static Vite site for a daily Statcast-powered look at
baseball's biggest bombs, no-doubters, wall-scrapers, and almost-homers. The v1
core feature is the Longball Index: pure home run quality, stadium-neutral.

The browser reads a generated JSON file from `public/data/hr-distance-latest.json`;
all Statcast/Baseball Savant access belongs in the Python data script.

## Features

- MLB Longball Index leaderboard
- Three front-page story modules: Jacked Up, Longball Index Leaders, and Wall-Scraper Watch
- Player/team search
- Minimum home-run filter
- Sortable columns
- Sample badges for reliable samples, small-sample monsters, no-doubter candidates, and wall-scraper watch
- The Hot Dog Stand pitcher-accountability backend and homepage cards
- Longball Notes markdown posts rendered into a static notes page
- Incremental Statcast data refresh through GitHub Actions

## Longball Index v1.3

The Longball Index measures pure home-run quality, stadium-neutral. LBI v1.3 is
anchored by Adjusted xHR/BBE from Baseball Savant's Home Run Tracker, along with
Barrel%, HR-Window Thunder Rate, and Hard Hit%. 100 is league average, and
elite longball hitters can score well above 150.

The v1.3 formula:

- 50% Adjusted xHR/BBE
- 20% Barrel%
- 25% HR-Window Thunder Rate
- 5% Hard Hit%

HR-Window Thunder Rate is the share of batted balls hit 105+ mph with launch
angle between 25 and 40 degrees.

Sweet Spot% is no longer part of LBI because it measures launch angle without
velocity and could inflate weak line-drive/contact hitters.

LBI is a rate stat scaled like wRC+:

- 100 is league average among qualified hitters
- Scores are not capped at 100
- Component percentiles are converted to a normal-score style metric before weighting
- Average Distance on Barrels remains available as a reference stat, but it is not part of LBI v1.3

Qualification:

```text
BBE >= max(50, estimated_team_games * 1.5)
```

Do not use actual HR/BBE as a substitute for stadium-neutral xHR/BBE; that would
reintroduce park bias.

LBI uses Baseball Savant's Adjusted Home Run Tracker view when available.
Adjusted trajectories account for ballpark dimensions and environmental context
such as temperature, elevation, roof, and other venue effects through Savant's
park-factor model. This should be documented as a Savant-modeled environmental
adjustment, not a fully independent Long Ball model.

The legacy `--min-hr` option is preserved for compatibility and frontend filter
defaults, but LBI qualification is BBE-based.

Stadium-neutrality should eventually be baked directly into LBI. A ball that
would leave 28 of 30 parks should help the score, while a homer that would only
leave 1 to 3 parks should be labeled as a wall-scraper and gently penalized.

## Methodology Backlog

### PA-level Longball Threat metric

LBI is currently batted-ball based. It measures the quality of a hitter's
home-run contact when he puts the ball in play. It does not directly answer
"how likely is this hitter to homer per plate appearance?" because it does not
include PA-level frequency, strikeouts, walks, swing decisions, or how often a
hitter gets to damaging contact.

Future companion metric:

- LBI = home-run contact quality per BBE
- Longball Threat = home-run damage likelihood per PA

Potential future inputs:

- Adjusted xHR / PA
- Adjusted xHR / BBE
- BBE / PA
- Barrel / PA

This is especially useful for comparing low-power/contact-heavy hitters where
batted-ball quality and HR likelihood per plate appearance may diverge.

Diagnostic note: Longball Threat v0.2 is a diagnostic predictive stat using
75% adjusted xHR/PA and 25% Barrels/PA. Backtesting from 2021-2025 showed this
simple two-factor version had the best pooled correlation with second-half
HR/PA among tested variants. It is not published in the live frontend yet.

## Local Development

Install dependencies:

```bash
npm install
python3 -m pip install -r requirements.txt
```

Start the dev server:

```bash
npm run dev
```

Then open the local URL printed by Vite.

Build production files:

```bash
npm run build
```

The build runs `scripts/build_posts.js` first, which turns markdown files in
`posts/` into `public/data/posts.json`. The production files are written to
`dist/`.

## Longball Notes

Weekly editorial posts live in `posts/` as markdown files:

```text
posts/2026-05-24-longball-notes.md
```

Each post can include simple frontmatter:

```md
---
title: Longball Notes
date: 2026-05-24
description: What this week's Longball Index is telling us.
---
```

Run `npm run build` after adding or editing a post. The prebuild step writes
`public/data/posts.json`, and the static frontend renders it on the Notes page.
It also writes a crawler-friendly markdown archive at `public/docs/notes.md`
and per-post markdown files in `public/docs/notes/`. Notes posts include
Schema.org Article metadata in `posts.json`, and static HTML versions are
generated in `public/static/notes/`.

## Public Routes

The app supports clean URLs for the main sections:

```text
/
/hot-dog-stand
/notes
/about
```

Concept anchors use clean paths such as `/about/longball-index` and
`/about/daily-dong`. The older hash routes still work for compatibility.
Vercel rewrites those clean app routes to `index.html` via `vercel.json`.
Crawler-friendly static HTML companions are also generated under
`public/static/` for About, Notes, and methodology docs.

## Data Files

The frontend reads only generated static JSON from `public/data`:

```text
public/data/hr-distance-latest.json
public/data/longball-index-2026.json
public/data/longball-index-2025.json
public/data/longball-index-2024.json
public/data/longball-index-2023.json
public/data/longball-index-2022.json
public/data/longball-index-2021.json
public/data/hot-dog-stand-latest.json
public/data/hot-dog-index-2026.json
public/data/daily-features-2026.json
public/data/tale-of-the-tape/YYYY-MM-DD.json
public/data/weekly-movers-latest.json
public/data/longball-scouting-report-latest.json
public/data/posts.json
```

The Python data jobs store the canonical raw pitch cache here:

```text
data/raw/statcast-pitches.csv
```

Manual historical LBI runs use season-specific local caches named
`data/raw/statcast-bbe-events-YYYY.csv`. Those files are intentionally ignored
by git because each full-season cache is large; commit the generated
`public/data/longball-index-YYYY.json` files instead.

On the first run, the pitch-cache script backfills the season to date. On later
runs, it fetches the last few days, merges those pitches into the raw cache, and
dedupes them. The LBI job derives batted-ball events from that canonical pitch
cache, fetches Baseball Savant's Adjusted Home Run Tracker aggregate CSV,
calculates LBI, and rebuilds the frontend-ready JSON. The Hot Dog Stand job
uses the same pitch cache and Baseball Savant Home Run Tracker data to calculate
pitcher-level accountability output.

The refresh script uses `pybaseball.statcast` and pandas. It refuses to publish
an empty leaderboard on a first run unless `--allow-empty` is passed, which helps
catch upstream data-fetch problems in GitHub Actions.

HDI v1.1 measures pitcher-side longball damage allowed, anchored by Adjusted
xHR/BBE allowed and sharpened by HR-capable contact, no-doubters, Avg EV
allowed, and HR-Window Thunder Allowed. The output includes Hot Dog Index,
HR-capable BBE allowed, no-doubters allowed, mostly-gone allowed, doubters
allowed, HR-Window Thunder Allowed, meatball context fields, exit velocity
allowed, distance reference stats, and the worst served event for each pitcher.

A meatball is a Heart-zone pitch thrown below the pitcher's 25th-percentile
velocity for that pitch type, with a 15+ pitch sample for that pitch type. The
Hot Dog Stand identifies pitchers who have served up the most damage on these
mistakes.

## Manual Data Refresh

Fetch recent Statcast data and regenerate the JSON:

```bash
python3 scripts/generate_pitch_cache.py --season 2026
python3 scripts/generate_hr_distance.py --season 2026 --min-hr 1
python3 scripts/generate_hot_dog_stand.py --season 2026
```

Use a wider recent fetch window:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --lookback-days 14
```

Force a specific date range:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --start-date 2026-03-01 --end-date 2026-05-19
```

Generate historical LBI seasons manually:

```bash
python3 scripts/generate_historical_lbi.py --seasons 2021 2022 2023 2024 2025 --force
```

Historical leaderboards are generated retroactively with the current LBI v1.3
methodology. The daily GitHub Actions workflow does not regenerate historical
seasons.

Merge from a local Statcast CSV instead of fetching:

```bash
python3 scripts/generate_hr_distance.py --input-csv statcast.csv --min-hr 5
```

`--min-pa` is available for optional analysis, but the MVP frontend defines
qualified hitters by minimum home-run count only.

## Weekly Longball Movers

Weekly LBI snapshots live in:

```text
public/data/snapshots/lbi-{season}-{YYYY-MM-DD}.json
```

The Monday Morning Movement Report compares the current snapshot to the most
recent prior Monday snapshot and writes:

```text
public/data/weekly-movers-latest.json
content/reports/YYYY-MM-DD-weekly-longball-movers.md
```

Generate a snapshot and movers report manually:

```bash
python3 scripts/generate_weekly_movers.py --season 2026 --create-snapshot
```

If there is no previous Monday snapshot yet, the script prints
`No previous snapshot found; create first weekly snapshot and rerun next week.`
and exits without writing a movers report.

## The Longball Scouting Report

The Longball Scouting Report is a rule-based weekly content draft built on top
of the weekly movers output. It is intentionally descriptive: "Power Gap" is a
signed expected-HR gap. Positive values flag hitters whose expected HR is
running ahead of actual HR with Longball Index support, while the opposite tail
can feed "Power Mirage" when HR output or Cheapies context is running ahead of
the underlying longball profile.

When `public/data/weekly-movers-latest.json` exists, generate the report with:

```bash
python3 scripts/generate_longball_scouting_report.py
```

The script writes:

```text
public/data/longball-scouting-report-latest.json
content/reports/YYYY-MM-DD-longball-scouting-report.md
```

During `npm run build`, markdown drafts in `content/reports/` are rendered to
crawlable static pages at `/reports/YYYY-MM-DD-longball-scouting-report` and
listed in the generated sitemap. The Markdown remains the editable source for
weekly publishing. The report archive lives at `/reports`, and the newest
published draft is also available at `/reports/latest-longball-scouting-report`.

If the weekly movers JSON does not exist yet, the script prints
`No weekly movers data found; create a weekly movers report and rerun.` and
exits without writing a report.

## GitHub Actions Refresh

The workflow at `.github/workflows/update-hr-data.yml` runs daily during the
broad MLB season window and can also be started manually with
`workflow_dispatch`.

The workflow:

1. Checks out `main`
2. Sets up Python
3. Installs `requirements.txt`
4. Runs `scripts/generate_pitch_cache.py`
5. Runs `scripts/generate_hr_distance.py`
6. Runs `scripts/generate_hot_dog_stand.py`
7. Commits generated data and the pitch cache back to `main` when anything changes

The weekly workflow at `.github/workflows/weekly-movers.yml` runs on Mondays
during the same broad season window. It refreshes the current LBI data, saves a
snapshot in `public/data/snapshots/`, generates the weekly movers JSON and
markdown draft when a prior Monday snapshot exists, generates The Longball
Scouting Report from that movers output, and commits any changed artifacts back
to `main`. It also supports `workflow_dispatch`.

## Daily Feature Video Overrides

The daily feature strip may include upstream `playUrl` values, but Baseball Savant
sometimes returns private `research.mlb.com` links. To add a public video manually,
edit `public/data/daily-dong-overrides.json` and add either a feature key
(`dailyDong`, `hotDogRobbery`, or `cheapestDong`) or a specific `eventKey` from
`public/data/hr-distance-latest.json`:

```json
{
  "dailyDong": {
    "videoUrl": "https://...",
    "videoLabel": "Watch the Daily Dong"
  },
  "2026-05-21|Kyle Schwarber|Pitcher Name|462|112.6": {
    "videoUrl": "https://...",
    "videoLabel": "Watch / View play"
  }
}
```

Commit the JSON change to `main`; Vercel will redeploy the static file.

Daily Dong, Hot Dog Robbery, and Cheapest Dong selections are also archived as
date-stamped Tale of the Tape files under `public/data/tale-of-the-tape/`. The
aggregate season file remains at `public/data/daily-features-YYYY.json`, while
the per-day files make individual dates easy to cite from notes, docs, and
future agents. The static build also creates crawlable pages at
`/tale-of-the-tape/YYYY-MM-DD` from those archive files and adds them to the
sitemap.

## Future Ideas

These are placeholders only, not full implementations yet:

- Adjusted vs Standard Home Run Tracker toggle
- Daily Dong video links and richer archive pages
- CSS launch-angle visualizer

## Vercel Deployment

Connect the GitHub repo to Vercel and use the default Vite settings:

- Build command: `npm run build`
- Output directory: `dist`

When GitHub Actions commits refreshed data to `main`, Vercel sees the new commit
and deploys the updated static site automatically. The target production domain
is `thelongball.app`.
