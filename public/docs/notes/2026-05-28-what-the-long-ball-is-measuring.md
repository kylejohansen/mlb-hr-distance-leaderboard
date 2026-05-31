Date: 2026-05-28
Canonical URL: https://thelongball.app/notes/2026-05-28-what-the-long-ball-is-measuring
Description: The first official Longball Notes post: why LBI exists, how v1.3 works, and where The Hot Dog Stand fits.
# What The Long Ball Is Measuring

The Longball Index started as a fun side project. A late-night idea to build a simple home run tracker has turned into a much more interesting experiment: can I track home-run-quality contact in a way that is meaningfully different from anything else out there?

All I wanted at first was a leaderboard of the daily longest home runs. Along the way, a lot of fun stuff showed up. Barrels are huge for home runs, which is not exactly breaking news. Pull AIR% is not quite the magic shortcut it can look like. Sweet Spot% is definitely not a home run stat. Looking at you, Ke'Bryan Hayes. And Baseball Savant's stadium-neutral expected home run work, especially when divided by batted ball events, turned out to be a strong proxy for home-run contact quality.

Put that together and the output is LBI, the Longball Index.

In v1.2, there were 225 qualified hitters. The mean score was 98.9 and the median was 101.3. The 90th percentile score was 141.7, with Munetaka Murakami sitting on top at 185.4.

The site is now on LBI v1.3 as of late May 2026. Aaron Judge is narrowly edging out Murakami, 188.4 to 188.2.

Here is how to interpret the current LBI board:

- Elite: 160+ (9 hitters)
- Plus: 130-159.9 (34 hitters)
- Above Average: 110-129.9 (40 hitters)
- Around Average: 90-109.9 (55 hitters)
- Below Average: 70-89.9 (36 hitters)
- Low: below 70 (51 hitters)

Practically speaking:

- 100 is basically average, as intended.
- 140+ is top-decile-ish.
- 155+ is top 5%.
- 175+ is monster territory.
- 55 is bottom-decile territory.

The Long Ball is not just a home run tracker. It is a Statcast-powered look at home-run quality: who creates it, who benefits from the park, and who keeps serving it up.

The goal is to combine fun with fantasy usefulness. The hitter side is cool, but the pitcher side can be even more instructive. We mostly know who should be near the bottom of a hitter longball-quality stat. The pitchers near the bottom of the Hot Dog Index are more interesting for fantasy, because the top of that board tells us who is getting punished by the kind of contact that can change a matchup fast. Seeing Jameson Taillon show up as one of the top starting pitchers in Hot Dog Index tells me the idea is working.

Right now, the site is trying to measure home-run-quality contact: which hitters are producing the contact most conducive to home runs in a neutral-park context. The next step is to keep tuning a predictive home run stat that can be backtested.

On the pitcher side, identifying who is serving it up at the most repeatable level is a worthy project too. Hot Dog Index v1.1 gives a rough estimate of the pitchers allowing the loudest longball damage.

Hot Dog Index v1.1 methodology:

- Adjusted xHR/BBE allowed: 32.5%
- HR-capable BBE rate allowed: 20%
- No-Doubter rate allowed: 10%
- Average exit velocity allowed: 7.5%
- HR-Window Thunder Allowed: 30%

HR-Window Thunder Allowed measures 105+ mph batted balls allowed between 25° and 40°, per BBE allowed.

Getting Cooked is the raw rate companion to HDI. It measures premium longball damage served per 100 BBE, using adjusted xHR, HR-Window Thunder BBE, no-doubters, and a light actual-HR component. Smaller samples can still get spicy, so it should be read with BBE allowed in mind.

## Version History

### V1.0 Provisional

Initial contact-quality formula using Barrel%, Hard Hit%, Avg Distance on Barrels, and Sweet Spot%.

### V1.1 Stadium-Neutral

Added Baseball Savant Adjusted xHR/BBE.

### V1.2

Made Adjusted xHR/BBE the structural anchor, removed Sweet Spot%, and widened the scale to better reflect the spread of true longball skill.

### V1.3

Rebuilt the formula around Adjusted xHR/BBE, Barrel%, HR-Window Thunder Rate, and Hard Hit%. HR-Window Thunder Rate measures 105+ mph batted balls launched between 25 and 40 degrees, giving LBI a sharper read on contact with true home-run flight.