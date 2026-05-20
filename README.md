# The Long Ball

Digging the data behind the distance.

The Long Ball is a small static Vite site for a daily Statcast-powered look at
baseball's biggest bombs, no-doubters, wall-scrapers, and almost-homers. The v1
core feature is the Longball Index: pure home run quality, stadium-neutral.

The browser reads a generated JSON file from `public/data/hr-distance-latest.json`;
all Statcast/Baseball Savant access belongs in the Python data script.

## Features

- MLB Longball Index leaderboard
- Daily Bomb Board with a season-to-date fallback
- Player/team search
- Minimum home-run filter
- Sortable columns
- Sample badges for reliable samples, small-sample monsters, no-doubter candidates, and wall-scraper watch
- Incremental Statcast data refresh through GitHub Actions

## Longball Index v1.0 Provisional

LBI v1.0 is provisional because the current `pybaseball.statcast` pull does not
include parks-out-of-30, `hr_stadiums`, `expected_hr`, or no-doubter park-count
fields. Stadium-neutral xHR/BBE will be added in v1.1 once that source is
integrated.

The v1.0 formula:

- 40% Barrel%
- 20% Hard Hit%
- 20% Average Distance on Barrels
- 20% Sweet Spot%

LBI is a rate stat scaled like wRC+:

- 100 is league average among qualified hitters
- Scores are not capped at 100
- Component percentiles are converted to a normal-score style metric before weighting
- If a player has fewer than 10 barrels, Average Distance on Barrels is excluded and its weight is redistributed

Qualification:

```text
BBE >= max(50, estimated_team_games * 1.5)
```

Do not use actual HR/BBE as a substitute for stadium-neutral xHR/BBE; that would
reintroduce park bias.

The legacy `--min-hr` option is preserved for compatibility and frontend filter
defaults, but LBI qualification is BBE-based.

Stadium-neutrality should eventually be baked directly into LBI. A ball that
would leave 28 of 30 parks should help the score, while a homer that would only
leave 1 to 3 parks should be labeled as a wall-scraper and gently penalized.

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

The production files are written to `dist/`.

## Data Files

The frontend reads only:

```text
public/data/hr-distance-latest.json
```

The Python script stores cached raw batted-ball events here:

```text
data/raw/statcast-bbe-events.csv
```

On the first run, the script backfills the season to date. On later runs, it
fetches the last few days, merges those batted-ball events into the raw cache,
dedupes them, calculates LBI, and rebuilds the frontend-ready JSON.

The refresh script uses `pybaseball.statcast` and pandas. It refuses to publish
an empty leaderboard on a first run unless `--allow-empty` is passed, which helps
catch upstream data-fetch problems in GitHub Actions.

## Manual Data Refresh

Fetch recent Statcast data and regenerate the JSON:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --min-hr 1
```

Use a wider recent fetch window:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --lookback-days 14
```

Force a specific date range:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --start-date 2026-03-01 --end-date 2026-05-19
```

Merge from a local Statcast CSV instead of fetching:

```bash
python3 scripts/generate_hr_distance.py --input-csv statcast.csv --min-hr 5
```

`--min-pa` is available for optional analysis, but the MVP frontend defines
qualified hitters by minimum home-run count only.

## GitHub Actions Refresh

The workflow at `.github/workflows/update-hr-data.yml` runs daily during the
broad MLB season window and can also be started manually with
`workflow_dispatch`.

The workflow:

1. Checks out `main`
2. Sets up Python
3. Installs `requirements.txt`
4. Runs `scripts/generate_hr_distance.py`
5. Commits `public/data/hr-distance-latest.json` and
   `data/raw/statcast-hr-events.csv` back to `main` when either file changes

## Future Ideas

These are placeholders only, not full implementations yet:

- Stadium-neutral LBI / All Stadiums Neutral toggle
- No-Doubter Meter
- Wall-Scraper Wall
- Meatball Tracker / Meatball Hall of Fame
- CSS launch-angle visualizer

## Vercel Deployment

Connect the GitHub repo to Vercel and use the default Vite settings:

- Build command: `npm run build`
- Output directory: `dist`

When GitHub Actions commits refreshed data to `main`, Vercel sees the new commit
and deploys the updated static site automatically. The target production domain
is `thelongball.app`.
