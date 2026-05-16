# MLB Home-Run Distance Leaderboard

A small static Vite site that ranks MLB hitters by average home-run distance.
The browser reads a generated JSON file from `public/data/hr-distance-latest.json`;
all Statcast/Baseball Savant access belongs in the Python data script.

## Features

- Leaderboard ranked by average home-run distance
- Player/team search
- Minimum home-run filter
- Sortable columns
- Friendly error states for missing or malformed JSON
- Incremental Statcast data refresh through GitHub Actions

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

The Python script stores cached raw home-run events here:

```text
data/raw/statcast-hr-events.csv
```

On the first run, the script backfills the season to date. On later runs, it
fetches the last few days, merges those events into the raw cache, dedupes them,
and rebuilds the JSON leaderboard from the cached events.

## Manual Data Refresh

Fetch from Baseball Savant and regenerate the JSON:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --min-hr 1
```

Use a wider recent fetch window:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --lookback-days 14
```

Force a specific date range:

```bash
python3 scripts/generate_hr_distance.py --season 2026 --start-date 2026-03-01 --end-date 2026-05-15
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

## Vercel Deployment

Connect the GitHub repo to Vercel and use the default Vite settings:

- Build command: `npm run build`
- Output directory: `dist`

When GitHub Actions commits refreshed data to `main`, Vercel sees the new commit
and deploys the updated static site automatically.
