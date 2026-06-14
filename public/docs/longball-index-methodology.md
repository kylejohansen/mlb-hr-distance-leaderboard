# Longball Index Methodology

Stable concept URL: `https://thelongball.app/about/longball-index`

Product tagline: Long-ball contact quality. Stadium-neutral. All fields.

## What LBI Measures

LBI v1.4 is a descriptive, full-season, 100 = league average index of long-ball contact quality. It scores qualifying long balls from observed physics and describes what happened. It is not a predictive stat, and expected home runs are not a scoring input.

## Eligible Long Balls

A batted ball enters LBI v1.4 only if it is airborne contact in the legitimate over-the-fence launch-angle band and passes a physical park-count gate:

- Actual over-the-fence HR with at least 1 standard park cleared.
- Non-HR contact that would have cleared at least 8 of 30 parks.

Weak 1-7 park contact that did not actually clear a fence is excluded. Eligibility uses observed physics and standard park-count geometry, not adjusted xHR or expected-HR model output.

## Two-Axis Formula

LBI v1.4 uses two axes:

- **ThumpIndex**: raw authority from exit velocity and park-neutral estimated distance, accumulated per PA.
- **Artistry**: how rare/difficult the event's batter-relative spray direction x launch-angle route to long-ball contact was, averaged per qualifying long-ball event and shrunk toward league average.

Headline formula:

- LBI = 50% Thump + 50% Artistry

## Spray

Spray is computed from both hit coordinates, `hc_x` and `hc_y`, and converted to batter-relative direction using the hitter's stand for that plate appearance. Positive spray is opposite field, negative spray is pull side. One-coordinate spray approximations are not used.

## Archetypes

Every hitter receives a style label:

| Archetype | Meaning |
|---|---|
| Apex Power | Elite Thump and elite Artistry. The complete long-ball profile: force plus rare-route damage. |
| Thumper | Elite Thump, more ordinary Artistry. Violent, overwhelming long-ball authority. |
| Specialist | Elite Artistry, more ordinary Thump. Long-ball value earned through difficulty rather than force. |
| Balanced Power | Solid on both axes, without one extreme defining the profile. |

## Scaling

LBI, Thump, and Artistry are plus-scaled to 100 = qualified-player average. Scores are not percentile-scaled and are not capped, so the tails remain visible.

## Context Fields

Expected HR, Barrel%, HR-Window Thunder Rate, Hard Hit%, Pull Pop, and OppoPop can still appear on the site as context stats. They are not part of the LBI v1.4 headline formula.
