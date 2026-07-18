# Hot Dog Stand Methodology

Stable concept URL: `https://thelongball.app/about/hot-dog-index`

Getting Cooked is the pitcher-facing companion to the Longball Index. LBI asks who creates longball contact. Getting Cooked asks who is serving up HR-capable contact most often.

## What Getting Cooked Measures

Getting Cooked v1.3 measures HR-capable batted balls allowed per BBE. It is plus-style, with 100 equal to average among qualified pitchers.

The idea is intentionally plain: how often does this pitcher allow contact with home-run potential in at least one MLB park?

## Getting Cooked v1.3 Formula

`100 * pitcher HR-capable BBE rate allowed / qualified-pitcher average HR-capable BBE rate allowed`

Raw companion: HR-capable BBE allowed per 100 BBE.

## Expected Long Balls

xLB v0.2 estimates how many home runs a pitcher's terminal batted balls would normally produce from their exit velocity, launch angle, and batter-relative spray.

Only terminal batted-ball events are scored. Foul balls and other non-terminal contact are excluded because they cannot become home runs.

The public rate is:

`xLB/9 = xLB * 27 / official pitcher outs`

xLB/9 is displayed as a natural rate, not a plus score. It combines contact quality with contact suppression in the familiar unit used by HR/9.

Together, Getting Cooked and xLB/9 separate danger per ball in play from the full expected longball burden per nine innings.

## Home Run Tracker Classifications

- No-Doubter Allowed: a batted ball that would clear all 30 MLB parks.
- Mostly Gone Allowed: a batted ball that would clear many parks, but not all.
- Doubter Allowed: a batted ball that would clear only a small number of parks.
- HR-Capable BBE: a batted ball classified as having home-run potential in at least one MLB park.

No-doubters, mostly-gone balls, and doubters all count as HR-capable contact for Getting Cooked. Their severity remains available in supporting context.

## Meatball Context

A meatball is a Heart-zone pitch thrown below the pitcher's 25th-percentile velocity for that pitch type, with a 15+ pitch sample for that pitch type. The Hot Dog Stand identifies pitchers who have served up the most damage on these mistakes.

## Known Limitations

- Getting Cooked and xLB/9 may evolve as pitcher-side methodology is tested.
- It relies on Baseball Savant Home Run Tracker classifications and Statcast batted-ball data.
- Team attribution and pitcher role can be derived from available Statcast context and may not perfectly describe opener or bulk-relief usage.
- Getting Cooked is a rate score and should be read with sample size in mind.
- xLB/9 uses official MLB pitcher outs; innings are never parsed as ordinary decimal numbers.
- xLB v0.2 is stadium-agnostic rather than fully park-neutral.
