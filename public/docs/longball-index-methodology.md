# Longball Index Methodology

Stable concept URL: `https://thelongball.app/about/longball-index`

The Longball Index (LBI) measures pure home-run-quality contact for hitters. It is a per-contact metric: it evaluates what happens when a hitter puts the ball in play, not how often the hitter makes contact.

## What LBI Measures

LBI is designed to describe the quality of a hitter's batted balls for home-run production. It separates longball contact quality from raw results such as HR totals, ISO, or slugging percentage.

## LBI v1.3 Formula

LBI v1.3 uses one formula for qualified hitters:

- Adjusted xHR/BBE: 50%
- Barrel%: 20%
- HR-Window Thunder Rate: 25%
- Hard Hit%: 5%

HR-Window Thunder Rate measures batted balls hit 105 mph or harder with launch angle between 25 and 40 degrees, divided by total BBE.

Avg Distance on Barrels remains a useful reference stat, but it is no longer part of LBI. Sweet Spot% is also not part of LBI because it measures launch angle without velocity and can over-credit weak line-drive contact.

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
- HR-Window Thunder Rate can be sparse early in the season, so early leaderboards should still be read with sample size in mind.
