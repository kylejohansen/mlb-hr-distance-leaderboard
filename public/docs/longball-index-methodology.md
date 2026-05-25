# Longball Index Methodology

Stable concept URL: `https://thelongball.app/about/longball-index`

The Longball Index (LBI) measures pure home-run-quality contact for hitters. It is a per-contact metric: it evaluates what happens when a hitter puts the ball in play, not how often the hitter makes contact.

## What LBI Measures

LBI is designed to describe the quality of a hitter's batted balls for home-run production. It separates longball contact quality from raw results such as HR totals, ISO, or slugging percentage.

## LBI v1.2 Formula

For players with 10 or more barrels:

- Adjusted xHR/BBE: 60%
- Barrel%: 20%
- Avg Distance on Barrels: 12.5%
- Hard Hit%: 7.5%

For players with 5-9 barrels:

- Adjusted xHR/BBE: 67.5%
- Barrel%: 17.5%
- Avg Distance on Barrels: 7.5%
- Hard Hit%: 7.5%

For players with fewer than 5 barrels:

- Adjusted xHR/BBE: 75%
- Barrel%: 17.5%
- Hard Hit%: 7.5%

Sweet Spot% is not part of LBI v1.2 because it measures launch angle without velocity and can over-credit weak line-drive contact.

## Stadium-Neutral Adjusted xHR/BBE

LBI uses Baseball Savant's Adjusted Home Run Tracker view when available. Adjusted xHR accounts for park dimensions and environmental context through Savant's model, including factors such as temperature, elevation, roof, and other venue effects.

Adjusted xHR/BBE is the structural anchor because it is the most direct available measure of stadium-neutral home-run-quality contact.

## Scaling

LBI is scaled like a plus stat:

- 100 is league average among qualified hitters.
- Scores are not capped.
- Elite longball hitters can score well above 150.
- Component percentiles are converted to a normal-score style metric before weighting.

## Known Limitations

- LBI is batted-ball based and does not measure home-run likelihood per plate appearance.
- Strikeouts, walks, swing decisions, and BBE/PA are not included.
- Adjusted xHR depends on Baseball Savant's park and environmental modeling assumptions.
- Small barrel samples use adjusted weights to reduce noise.
