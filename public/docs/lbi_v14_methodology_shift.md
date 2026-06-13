LBI v1.4 — Methodology Shift

Working draft · the what, the why, and the technical language


TL;DR

LBI v1.4 is a fundamental redefinition, not a tuning pass. We moved LBI from a weighted blend
of expected-power components (anchored heavily on expected home runs) to a descriptive,
two-axis "long-ball quality contact" stat scored directly from the physics of each batted ball.

The old version answered, in effect, "how much expected-home-run production did this hitter
generate?" — which made it correlate ~0.94 with expected HR and read like a dressed-up version of
a stat that already exists. The new version answers a different and previously unmeasured question:
"How much authoritative, all-fields long-ball contact did this hitter actually make — and how
did he do it?" It is descriptive (it describes what happened, with a point of view), not
predictive (it makes no forecast). Correlation with expected HR dropped to ~0.87, while the elite
hitters stayed on top — distinct enough to be its own stat, anchored enough to be credible.


1. The core philosophical change: descriptive, not predictive

The old framing implicitly chased predictiveness — "does this number forecast future home runs."
We concluded that goal was both unwinnable (established expected-stats have years of trust a new
metric can't match) and unnecessary (a leaderboard's job is to describe the season, not forecast
it). So v1.4 is openly descriptive: it ranks the long-ball contact a hitter actually produced.

This reframing is also what makes the stat defensible. A predictive stat can be proven wrong by a
backtest. A descriptive stat that says "here are the season's long-ball artists, and here's how
they did it" is reporting what happened — it cannot be falsified the same way, and it owns a lane
no expected-stat competes in.


2. What was removed and why

Expected HR is no longer the anchor (and is not an input to scoring at all).
The prior formula leaned ~50% on adjusted expected HR per batted ball. That made LBI a near-proxy
for expected HR. v1.4 scores from raw observed physics instead, so the stat measures the contact
itself rather than a model's estimate of it. (Expected-HR-style information still exists elsewhere
on the site; it just no longer defines LBI.)

Hard-Hit% is gone — it was cosmetic.
Diagnostics showed Hard-Hit% added essentially nothing: dropping it left rankings ~0.999 identical.
It was redundant with the barrel/quality signals already present. Removed.

Per-batted-ball-event (BBE) rate denominators are gone.
Rate-vs-BBE penalizes hitters for making contact: a grinder who puts more balls in play has a
larger denominator and a diluted power rate, even with identical raw power. We moved to per-PA and
per-event denominators (see §4) so contact-oriented hitters aren't taxed for the act of making
contact.


3. What was added: a two-axis model with archetypes

LBI v1.4 scores every qualifying long ball on two independent axes, then blends them and reads
the gap between them as a player archetype.


THUMP — raw authority. How hard and how far the ball was struck. Built from exit velocity and
park-neutral estimated distance. This is the "force" dimension — awe, no-doubters, the loud
contact. It is the dimension that tends to persist year to year.
IMPROBABILITY — how hard the long ball was to produce. Built from the rarity of the
ball's spray direction × launch angle combination among home runs. Opposite-field contact,
and low-line-drive contact, are rare ways to produce a home run, so they score as more improbable.
This is the "craft / authority off the bat" dimension — the thing that makes a long ball special
rather than merely loud. It is, deliberately, the dimension expected-HR stats cannot see.


A hitter's position on these two axes defines his archetype:

ArchetypeProfileApex PowerHigh Thump AND high Improbability — the complete long-ball profile: force plus rare-route damagePure MasherHigh Thump, ordinary Improbability — elite force, the expected way (high-launch pull power)ArtistHigh Improbability, ordinary Thump — produces long balls the hard way (all-fields / line-drive damage) without elite raw powerBalanced PowerSolid on both, no extreme

The archetype is the product. A single rank tells you how much; the archetype tells you how —
"these were the season's long-ball artists, and here's the style of each."


4. The key technical insight: asymmetric denominators

This is the discovery that made the two-axis model actually work, and it is the most important
technical point to retain.

The two axes must be denominated differently:


Thump is measured per plate appearance (per-PA) — it is a rate of production. More loud
long balls per trip to the plate = more of a masher. Volume-aware on purpose.
Improbability is measured per-event (averaged across a hitter's long balls) — it is a
trait, not a rate. A hitter who produces a few genuinely improbable long balls is an artist
whether or not he does it often. Frequency-independent on purpose.


Why it matters: if both axes used the same per-PA denominator, both would simply track home-run
rate, the two axes would correlate ~0.9, and every hitter would collapse into the same archetype.
Splitting the denominator dropped the axis correlation to ~0.3, which is what lets the two
dimensions mean genuinely different things and produces a real spread of archetypes. Thump is a
rate; artistry is a trait; they are different kinds of quantity and are measured as such.

(Because the Artist axis is frequency-independent, it is sample-fragile by nature — a hitter with
few long balls and a couple of rare ones can spike. v1.4 applies shrinkage toward the league mean
and a minimum-event gate so the Artist tag reads as a style on a real long-ball hitter, not a
standalone claim that a low-power hitter is a top threat.)


5. Eligibility: what counts as a long ball

A batted ball is scored only if it is genuinely a long ball, judged on physics, not on the
outcome label:


Launch angle within the over-the-fence band (lower bound set at ~14°, the empirical Statcast
floor for legitimate over-the-fence home runs; this also excludes grounders and inside-the-park
events). Upper bound excludes pop-ups.
It either cleared a fence for real (an actual over-the-fence home run) or its trajectory
would have cleared 8+ of 30 parks (a "robbed" home run — caught or held in only because of
where it was hit). We score the contact, not the outcome, so a 440-foot blast that a center
fielder happened to run down still counts.
Weak, park-dependent contact (would leave only 1–7 parks and wasn't an over-the-fence HR) is
excluded as not a true long ball.


Critically, eligibility reads only observed physics — exit velocity, launch angle, true spray
angle, and standard (park-geometry-neutral) park count. It never uses an expected-HR model, an
environment-adjusted model, or the outcome label as a quality shortcut. This keeps the stat
model-free at its foundation and keeps the "stadium-neutral" promise honest (park geometry only,
not an environmental adjustment model).


6. A note on spray accuracy

True spray direction is central to the Improbability axis, so it had to be computed correctly.
Spray angle requires both hit coordinates; an approximation using only one coordinate
systematically over-counted opposite-field contact (it disagreed with true spray on ~12% of
events). v1.4 uses the full two-coordinate, batter-relative spray angle (handled per plate
appearance, so switch-hitters are correct). This matters because a 12% directional error would have
corrupted exactly the all-fields signal the stat is built around.


7. Scale and consistency

LBI v1.4 is reported on the site's standard 100 = league average scale (consistent with the
other power columns), with the tails left uncompressed so a historic season reads as a high number
rather than being flattened to a percentile. Each axis is normalized to 100 = average independently
and then blended, so the final number sits on the same footing as the rest of the leaderboard.

The blend is weighted 50 / 50 between Thump and Improbability — a deliberate choice to favor
neither force nor craft, letting each hitter's profile place him honestly. (Testing showed the
blend barely moves the top of the board, since elite hitters score on both axes; the weighting
mostly affects the middle, where it trades one-dimensional pull power down for all-fields profiles
up.)


8. The result, in numbers


Distinct from expected HR, but credible: v1.4's correlation with adjusted expected HR is
~0.87, down from ~0.94 for the prior version — measurably its own stat, while the genuine elite
long-ball hitters (Murakami, Schwarber, Wood, Judge, Cruz) remain near the top of both.
It rewards the thing the old stat missed: among the hitters who rose most from v1.3 to v1.4,
average opposite-field rate was ~22%; among those who fell most, ~11%. The new stat is materially
friendlier to all-fields and rarer-contact profiles — which is the entire point.
It tells stories: every hitter now carries an archetype (Apex Power / Pure Masher / Artist /
Balanced Power) describing not just how good his long-ball season was, but what kind of long-ball
hitter he is.
