The Long Ball - Storm Watch Notes
=================================

The internal state-of-thinking for Storm Watch. Read this before any Storm
Watch diagnostic, formula, shadow, or display work.

Why this file exists: Storm Watch is a long-running research thread worked
across multiple tools. Codex runs diagnostics, GPT cross-checks, Claude
interprets. The conclusions and open questions have lived in chat, which means
they can evaporate between sessions and get re-litigated from scratch. This
file is the single durable home for what we have decided, what we have ruled
out, and what is still open.

Status as of June 2026: internal / On Deck shadow. Not public. The current
backtest arc has reached diminishing returns; the next priority is live 2026
validation, not another variable search by default.

TL;DR
-----

- Storm Watch is an internal Young Power Radar: an emerging-power radar for
  low-history hitters whose MLB power signal is forming before the track record
  exists.
- Full-league six-week HR prediction is dead. No clean model reached the 0.55 /
  0.58 live threshold.
- B6-Air is the frozen score. Do not keep testing formula cores or new
  ingredients.
- Prime Emergence, the age 24 / turning-25 low-history bucket, is High Trust.
  Leave it alone.
- Early Emergence, the 21-23 low-history bucket, is Candidate. It has real
  signal but year-composition volatility, and it is not validated as a uniform
  <=25 young-player pool.
- Durability / true contact-discipline does not rescue Early's volatility.
  Tested on checkpoint-clean pitch data.
- One usable durability find: Early false-positive busts skew toward contact /
  whiff problems specifically, not chase/K%/BB% broadly. Use that as a bust-risk
  context flag or player-card note, never as a formula input.
- Power Access / Boom-or-Bust is an archetype and counterweight layer, not a
  public formula. Do not multiply power by contact or expose Damage Access as a
  public stat.
- Fantasy ADP is the first market-awareness layer for Storm Watch shadow
  tracking. It is context only, not part of B6-Air.
- MiLB Stats API support is the first pre-MLB production-support layer. It is
  context only, not part of B6-Air.
- FanGraphs The Board / FV is promising as a manual dated consensus snapshot,
  but the public HTML pilot is not reliable enough for automated snapshots yet.
- The major tested axes now point the same way: formula core, full-league
  prediction, age buckets, continuous emergence gap, power-proxy durability,
  and true discipline durability.
- Avoid re-opening Storm Watch with another backtested variable unless new live
  evidence or a genuinely new data source changes the question. The product is
  the cohort plus live validation, not a better backtest number.

1. What Storm Watch Is
----------------------

Storm Watch is LBI's predictive sibling - not LBI, not descriptive, not a
public flagship. Its job is near-term: which young / low-history hitters are
showing power signals before the MLB HR track record fully exists?

It is not a season projection system. It is not trying to beat Steamer / THE
BAT X / Marcel. Comparing it to professional projection systems is a category
error. Those project a full season; Storm Watch is a short-horizon in-season
signal. Honest public framing avoids "projection," "forecast," "expected HR,"
"rest-of-season" and uses "signal," "watchlist," "surge," "radar," and
"power heating up."

Canonical naming:

- Storm Watch: branded feature name.
- Young Power Radar: plain-English descriptor.
- Prime Emergence: the validated age 24 / turning-25 bucket.
- Early Emergence: the Candidate 21-to-23 bucket.
- Late-Arrival Reference: 26-27 low-history internal reference only.
- Durability: contact-risk confidence/context layer, not score.

Canonical public-style framing:

Storm Watch is an emerging-power radar for low-history hitters whose MLB power
signal is forming before the track record exists.

2. The Product Shape
--------------------

Storm Watch is now a bucketed umbrella stat for low-history hitters age <= 25.
That <=25 range is the young-power scope, not a promise that every age state is
equally validated. Players are evaluated inside age/experience context, and
each bucket carries its own confidence rating earned by validation. Trust varies
by bucket.

The core product lesson: age buckets are crude, but age carries real,
irreducible developmental structure. A continuous emergence-gap score can
augment and smooth context, but it does not replace the buckets.

Prime Emergence is the high-confidence state: age 24 / turning-25 hitters with
low MLB exposure. This is the moment where batted-ball power can be mature
enough to trust, but MLB HR history may not yet be priced in by the market.

Early Emergence is a Candidate state: 21-23 low-history hitters. It has real
signal, but year-to-year prospect-class composition creates volatility. Some
years have enough durable young power to score; some do not. That volatility is
in the world, not a missing model variable.

Late-arrival 26-27 low-history names may be tracked internally as references,
but they are not part of the public young-power promise yet.

3. Frozen Score
---------------

The formula axis is retired. Do not test more formula cores.

B6-Air:

- 60% Storm Fuel A2
- 20% Barrel/PA
- 20% HR-Window Thunder/PA

Storm Fuel A2:

- 50% stabilized xHR/BBE
- 25% stabilized HR-Window Thunder Rate
- 25% Air EV90

Air EV90 = 90th percentile EV on lifted damage-zone contact, currently launch
angle 15-45 degrees. Public helper: "top-end EV on lifted contact." Do not call
15-45 degrees "the HR window."

Conceptual split:

- EV90 = raw juice.
- Air EV90 = lifted raw juice.
- HR-Window Thunder = 105+ mph contact between 25 and 40 degrees.
- Thunder/PA = how often HR-window damage appears per PA.
- Storm Fuel = the ingredients.
- B6-Air / Storm Watch = the alert.

June 2026 EV-slot decision: replace all-BBE EV90 with Air EV90. The diagnostic
showed a small but clean improvement in full-pool Pearson (0.504 vs 0.502) and
Prime Emergence Pearson (0.475 vs 0.472), with a much stronger denominator than
directional air splits. Pull Pop was tested as an EV-slot substitute and did not
beat Air EV90; keep Pull Pop as card/context texture, not Storm Fuel's EV
ingredient.

Storm Fuel is kept for robustness / diversification, not measured
outperformance. A core-swap test holding the tail fixed (60% core + 20%
Barrel/PA + 20% Thunder/PA) found Storm Fuel, xHR/BBE, LBI, and Barrel% all
tie around the same quality ceiling. A blend that ties on average but is less
fragile in live tails is the right call.

Pulled airborne is confirmation / tiebreaker only. It improved Pearson in the
Prime slice but did not improve top-decile lift over B6-Air. Public story:
B6-Air is the score; pulled airborne tells us whether the swing shape is
converting that power into HR-friendly contact.

4. Stabilization
----------------

For players with real prior MLB data:

- xHR/BBE: blended toward prior-season power shape, M = 150.
- HR-Window Thunder Rate: blended toward prior, M = 100.
- Air EV90: raw / current only, because it stabilizes quickly and is the
  early-signal ingredient.

For players with no prior MLB data:

- xHR/BBE and Thunder shrink toward league average at M ~= 317.
- Air EV90 stabilizes faster, M ~= 62, using air-BBE as the denominator.

The shrinkage is intentional skepticism, not a bug. A rookie with a few loud
balls should not rocket to the top until the sample supports it. Air EV90 lets
real airborne raw juice show up early; xHR/HR-Window Thunder stay skeptical
until BBE accumulates.

Confirmed not the bottleneck: sweeping no-prior M values (xHR/HR-Window Thunder
at 250 / 317 / 400; Air EV90 at 50 / 62 / 75 / 100) barely moved results. Keep
M=317 and Air EV90 M=62. Do not re-tune these chasing decimals.

5. What Was Tested And Closed
-----------------------------

| Axis | Question | Result |
| --- | --- | --- |
| Formula core | Better 60% core than Storm Fuel? | All four cores tie around the quality ceiling. Keep Storm Fuel for robustness. |
| Full-league | Predict six-week HR for everyone? | Dead, around 0.52 and below live threshold. |
| Age buckets | Which ages hold? | Prime validated/stable; Early real but volatile; 23-25 dilutive and rejected. |
| Continuous emergence gap | Replace age buckets with a continuous unit? | Augments as context and smooths cliffs, but does not replace buckets. Age carries real signal. |
| Durability - power proxies | Hard-hit/repeatability stabilize Early? | No. They are redundant with B6-Air. |
| Durability - true discipline | Contact/whiff/chase rescue Early? | No. Contact/whiff gives a bust-risk flag, not a formula fix. |

The consistent lesson: Prime is trustworthy. Early needs more seasons. The
tested variable changes have not removed Early's year-to-year volatility,
because much of that volatility appears to be prospect-class composition rather
than a missing ingredient.

6. Bucket Evidence And Confidence
---------------------------------

Prime Emergence:

- Bucket: age 24 / turning 25, previous-season MLB PA < 300. In current
  shorthand, this is the broader 24-to-25 low-history approach, not a
  permission to broaden into 23-25.
- Confidence: High Trust.
- Aggregate: n = 135 checkpoints, 59 unique players, Pearson .589, Spearman
  .583, top-decile lift +77.4%.
- Stability was spread across seasons rather than coming from one artifact:
  year-by-year Pearson .545 / .594 / .553 / .659 / .669.
- Decision: this is the trustworthy bucket. Leave it alone; discipline and
  durability do not improve it.

Early Emergence:

- Bucket: 21 <= age < 23, previous-season MLB PA < 300.
- Confidence: Candidate.
- Aggregate signal is real, around .564 Pearson in the canonical bucket test,
  but leave-one-year-out is wide and composition-sensitive.
- The weak years are not just small-sample artifacts. The 2024 slice was the
  largest Early sample and still tested weak, which points to year-composition
  volatility rather than a simple lack of BBE.
- BBE >= 250 is a modest higher-trust context, not a separate formula.
- Contact/whiff risk can flag bust-prone Early names, but it does not upgrade
  the bucket.
- Do not overstate the literal 21-22 slice as validated on its own. The current
  validated read is broader: Early 21-23 is a Candidate state, with trust
  carried by bucket confidence and sample/context notes.

Other buckets:

- <21: too small / caution.
- 22-23 and 23-24: weaker / provisional caution.
- 23-25 combined: rejected as dilutive.
- 26-27 low-history: internal late-arrival reference only.

Do not judge these buckets by a single-year top-decile lift. The per-year
samples are intrinsically small, so top-decile lift can swing on one or two
players. Trust whole-cohort Pearson/Spearman, aggregate lift, and live names.

7. Durability Investigation
---------------------------

Why we did it: prior durability tests only had power-frequency proxies such as
hard-hit air and repeatability. Those are redundant with B6-Air by construction.
The genuinely orthogonal hypothesis - skills around the power determine which
young power survives MLB adjustment - required true checkpoint-safe pitch-level
contact and discipline data.

Data infrastructure built:

- `data/cache/storm-watch-durability/` contains 20 checkpoint-clean pitch caches
  and 20 derived discipline-metric files for 2021-2025 x May 1 / June 1 / July 1
  / August 1.
- It also contains five regular-season raw season caches and a validation
  summary.
- Per-batter checkpoint-to-date metrics: K%, BB%, whiff%, contact%, zone
  contact%, chase%, and swinging-strike%.

Required rebuild guardrails:

- Regular-season filter: `game_type == "R"`. Raw `generate_pitch_cache.py` drops
  `game_type` during normalization and can pull Spring Training if this is not
  handled.
- Exclusive boundary: checkpoint-to-date is strictly `< checkpoint`, not `<=`.
  The old Storm Watch checkpoint rows used inclusive `<=`; align to exclusive
  before joining, or PA/BBE and pitch metrics live on different clocks.

Validation:

- All 20 checkpoints had zero leakage: max pitch date < checkpoint.
- All 20 checkpoints had zero non-regular rows.
- Coverage was 100%.
- League rates were sane and stable: K% around 22-24%, whiff% around
  23-24.5%, chase% around 27-29%.
- PA tie-out was 97.4% exact. The 103 deltas were international-series
  artifacts (2024 Seoul Series Dodgers/Padres, 2025 Tokyo Series Dodgers/Cubs),
  not join bugs.
- A sensitivity pass excluding all PA-delta rows did not flip the conclusion.

Model test: fixed 85% B6-Air + 15% durability overlays, not a weight sweep.

Early Emergence aggregate:

- B6-Air: .569 Pearson.
- B6-Air + contact survival: .578 Pearson.
- B6-Air + swing-decision: .560 Pearson.
- B6-Air + combined durability: .570 Pearson.

This is noise-level. Weak years stayed broken: 2023 Pearson -.046 moved to
-.055 with contact and +.063 with swing-decision, but that hurt 2024. The LOO
range stayed enormous, roughly -.05 to .80. True discipline helps around the
edges and does not rescue the volatility.

Prime Emergence:

- B6-Air: .581 Pearson.
- Discipline overlays did not improve it, around .573 with overlays.
- Decision: leave Prime alone.

Conclusion: keep B6-Air frozen. Durability is not a formula modifier. Early's
volatility was not fixed by the available contact/discipline signals.

8. The Whiff Bust-Risk Flag
---------------------------

The usable durability find is narrow but real. Early B6-Air false positives
showed a bat-to-ball signature:

- Contact: 73.3% for false positives vs 77.5% for the rest.
- Whiff: 26.7% for false positives vs 22.5% for the rest.
- K%, chase%, and BB% did not show the same pattern.

So the bust signal is specifically contact/whiff, not discipline broadly.

Use case:

- High B6-Air power + contact/whiff red flag = higher bust risk / lower
  confidence on that Early name.
- This contextualizes risky names. It does not change the ranking and does not
  upgrade Early's tier.

If surfaced later, store contact% and whiff% on the shadow snapshot alongside
B6-Air so the flag can be shown. Treat it as a confidence/context layer or
player-card note, never a score input.

9. Power Access / Contact Counterweight Findings
------------------------------------------------

The internal Power Access diagnostic used the current 2026 Storm Watch snapshot
and wrote review files to `/tmp/power_access_tags_2026.csv` and
`/tmp/power_access_tags_2026.json`. It did not change public output.

Conclusion: contact/discipline is best as counterweight context and archetype,
not as an integrated public Damage Access stat. Contact access is
anti-correlated with power in this population:

- contact% vs LBI: about -0.534.
- contact% vs B6-Air: about -0.503.
- contact% vs future HR/PA: about -0.303.
- whiff% moves in the opposite direction.

Because contact access and power pull against each other, multiplying power by
contact waters down the hitters most likely to hit home runs. Multiplicative
Damage Access is a clear no for public use. Light Damage Access may be useful as
an internal narrow-context check, but it is not strong enough for public display.

Recommended internal tag vocabulary:

- Boom-or-Bust: elite power plus extreme whiff/contact risk.
- Volatile Access: loud power plus contact/whiff risk.
- Power Trust / Contact-Supported Power: loud enough power plus playable
  contact.
- Contact Foundation: excellent contact foundation with modest or forming
  power.
- Neutral Context: power remains the main read; access context does not change
  the interpretation.

Use cases:

- Player-card context.
- Scouting Report note context.
- Storm Watch confidence context, especially for Early names.
- Future fun Boom-or-Bust leaderboard only after product/UI review.

Explicit non-use cases:

- Do not alter LBI.
- Do not alter B6-Air.
- Do not expose Damage Access as a public stat.
- Do not multiply power by contact as a public formula.

Example reads from the 2026 tag review:

- Munetaka Murakami: Boom-or-Bust / Volatile Access.
- Nick Kurtz: Boom-or-Bust.
- Jordan Walker: Boom-or-Bust.
- Jac Caglianone: Volatile Access.
- Nolan Gorman: Volatile Access.
- Curtis Mead: Power Trust / Contact-Supported Power.
- Kevin McGonigle: Contact Foundation.
- Liam Hicks: Contact Foundation.
- Aaron Judge, Kyle Schwarber, James Wood, Cal Raleigh, and Oneil Cruz:
  Boom-or-Bust archetype examples.

10. Consensus / Market Awareness Context
----------------------------------------

The current/live consensus review added FantasyPros ADP as the first durable
market-awareness layer in the Storm Watch shadow workflow. ADP answers a
different product question than B6-Air: did the fantasy market already know
about this player?

ADP is context only. It is never part of B6-Air, Storm Fuel A2, bucket
confidence, LBI, or any public formula.

Current ADP field vocabulary:

- fantasyAdp.
- fantasyAdpBucket: top 100, 101-200, 201-300, 300+, undrafted / missing, or
  ambiguous.
- fantasyAwarenessScore.
- adpSource.
- adpSourceDate.
- adpJoinStatus.
- adpNameMatched.

Current category vocabulary:

- Storm Confirms: high Storm Watch plus market awareness or current MLB HR
  production. Storm Watch confirms a known power name.
- Consensus Gap: high Storm Watch plus low/missing ADP, low/moderate prospect
  consensus, and low public/current-production obviousness.
- Market Ahead of Signal: strong ADP/prospect/fantasy awareness with a weaker
  current Storm Watch power signal.
- Statcast Flash: high Storm Watch plus low consensus, but weak/no
  track-record support.
- Already Known: high current HR output, top ADP, or strong prospect consensus.

FantasyPros ADP joined well enough for current live shadow use. The June 2026
review joined 199 of 235 Storm Watch rows by normalized name, with two explicit
ambiguous names: Shohei Ohtani and Max Muncy. Ambiguous names must remain
explicit and should not be silently assigned to the wrong ADP row.

High Storm + low ADP is a potential consensus gap. High Storm + high ADP is
Storm Watch confirming market-known power. High ADP + weaker Storm is market
ahead of the current MLB power signal.

MLB Pipeline:

- The current pybaseball / MLB Pipeline `top_prospects` stats table is useful
  for an active Prospect Storm Board and minor-league stats context.
- It is not sufficient for current MLB graduated Storm Watch context by itself.
  The June 2026 review returned 68 batting prospects with useful rank, level,
  PA, HR, HR%, BB%, K%, SLG, and OPS fields, but joined 0 of 235 current Storm
  Watch rows.
- Treat it as active minor-league prospect context, not the main
  graduated/current MLB consensus source.
- A dated Prospect Storm Board snapshot now stores this source as the pre-MLB
  layer: `data/shadow/prospects/prospect_storm_board_YYYY-MM-DD.json`.
- Pipeline stats are descriptive support, not Storm Watch scoring. They should
  help answer what a prospect looked like before MLB arrival, then travel
  forward as context if the player graduates into Storm Watch.

FanGraphs The Board / FV:

- The public HTML pilot fetched useful fields from org pages: FV, risk, ETA,
  level, org, position, Top 100 rank, org rank, age, and scouting-position
  fields such as hit, pitch selection, bat control, game power, raw power, and
  hard-hit%.
- It joined too few current Storm Watch rows for automation: 15 of 235 by
  normalized name + org/age, with 216 unmatched and no MLBAM or FanGraphs id
  exposed in the public table.
- It did join some current MLB/prospect-overlap names, including Sal Stewart,
  Samuel Basallo, and JJ Wetherholt, which is better than Pipeline for this
  purpose but still too partial.
- Do not automate FanGraphs public HTML into future snapshots yet.
- Best future use: a manual/member dated FanGraphs export snapshot with strict
  join logic. Public HTML can remain review-only fallback.
- MLB Pipeline preseason Top 100 / team ranks remains another candidate because
  preseason ranks are a clean market-awareness artifact.

11. Prospect Storm Board
------------------------

Prospect Storm Board is the pre-MLB layer. Storm Watch is the MLB low-history
layer. The purpose is to preserve a dated view of prospect rank, current
minor-league production, and approach before a player reaches or graduates into
the MLB Storm Watch pool.

Source:

- `pybaseball.top_prospects(playerType="batters")`.
- Underlying page: MLB Pipeline prospect stats.
- Current fields: rank, player, age, level, PA, HR, HR%, BB%, K%, SLG, OPS.
- Current limitations: no MLBAM id, no team/org field, no position field, and no
  explicit source date in the returned table.

Prospect Storm Support v0 is descriptive and transparent, not predictive:

- 40% minor-league power support: HR/PA, SLG, OPS.
- 25% prospect rank / consensus: inverse rank percentile.
- 20% approach support: BB%, inverse K%, BB/K.
- 15% age/level context: younger at higher level is more impressive; multi-level
  aggregate rows use a coarse neutral level score.

Categories:

- Top Prospect Power.
- Under-the-Radar Power.
- Power Risk.
- Contact Foundation.
- Balanced / Follow.
- Not Enough Data.

When a prospect later appears in Storm Watch, carry forward:

- pipelineRank.
- pipelineAge.
- pipelineLevel.
- pipelinePA.
- pipelineHR.
- pipelineHRRate.
- pipelineSLG.
- pipelineOPS.
- pipelineBBRate.
- pipelineKRate.
- prospectStormSupport.
- prospectCategory.
- prospectSourceDate.

Future bridge requirement: add MLBAM/player id when possible, or use strict
normalized name + age + org matching with ambiguity reporting. Do not silently
fuzzy-match prospects into MLB Storm Watch rows.

12. Pre-MLB Power Support
-------------------------

MLB Stats API MiLB batting stats by MLBAM is the first pre-MLB power-support
layer for Storm Watch shadow tracking. It joins current Storm Watch MLB rows
well enough to use as live context: the June 2026 pilot attempted 235 rows,
matched 231 with any MiLB data, and matched 231 with AA/AAA data.

Endpoint:

```text
https://statsapi.mlb.com/api/v1/people/{playerId}/stats
```

Parameters:

- stats=yearByYear.
- group=hitting.
- sportId=11 / 12 / 13 / 14.
- sportId=11 = Triple-A.
- sportId=12 = Double-A.
- sportId=13 = High-A.
- sportId=14 = Low-A.

MiLB support is context only. It is never part of B6-Air, Storm Fuel A2, bucket
confidence, LBI, or any public formula.

Field vocabulary for future shadow snapshots:

- milbDataStatus.
- milbHighestLevel.
- milbUpperMinorsPA / HR / HRPerPA / SLG / OPS / BBRate / KRate.
- milbAllLevelsPA / HR / HRPerPA / SLG / OPS / BBRate / KRate.
- milbPowerSupportScore.
- milbApproachSupport.
- milbPowerCategory.
- milbSampleCaution.
- milbSource / milbSourceSeasonRange / milbJoinStatus / milbNote.

Upper-minors AA/AAA support is preferred because it is closest to MLB. All-level
aggregate support is fallback/context only, and the snapshot should say so when
the profile leans on lower-level data. Cam Smith-type cases should be marked
with language like: "MiLB support leans on all-level data; limited upper-minors
PA."

MiLB support categories:

- Strong MiLB power support.
- Solid MiLB power support.
- Contact/approach support, modest power.
- Weak MiLB power support.
- Not enough MiLB data.
- Foreign/pro context missing.
- Source mismatch / manual review.

Foreign/pro players need separate NPB/KBO/manual context. Do not classify
Munetaka Murakami, Kazuma Okamoto, Shohei Ohtani, Jung Hoo Lee, or similar
players as weak MiLB support just because the MiLB source does not cover the
relevant track record.

How to read the layer:

- Strong MiLB support + high Storm + low ADP is the best early consensus-gap
  profile: current MLB batted-ball signal, real pre-MLB power support, and low
  fantasy-market awareness.
- Weak MiLB support + high Storm is a Statcast Flash / caution profile: the MLB
  contact signal is loud, but the pre-MLB power track record does not clearly
  back it yet.
- High Storm + high ADP + strong MiLB support is Storm Confirms: the market
  already knew, and Storm Watch agrees.

ADP remains the fantasy-market awareness layer. FanGraphs The Board / FV remains
the preferred scouting-consensus layer if a dated export can be obtained, but
the public HTML pilot should stay review-only until the join coverage and ID
path are stronger.

13. Product State Summary
-------------------------

Storm Watch is the branded Young Power Radar for low-history hitters. B6-Air is
the frozen score. Players are evaluated with age/experience context and bucket
confidence, with Prime Emergence as the validated high-trust bucket and Early
Emergence as a candidate bucket. ADP, MiLB production, Prospect Storm Board
snapshots, Power Access tags, and eventual scouting consensus are context layers
that answer whether the signal is early, supported, volatile, or already priced
in. Storm Watch remains internal/on-deck until live 2026 names produce.

14. Infrastructure And Snapshot TODO
------------------------------------

- `scripts/shadow_storm_watch_prime_emergence.py`: current shadow snapshot
  writer. It writes retained snapshots under
  `data/shadow/storm_watch_prime_emergence/`.
- `scripts/eval_shadow_storm_watch_prime_emergence.py`: evaluator between two
  snapshot dates; measures forward HR/PA, HR/600, and HR/BBE for the earlier
  watchlist.
- `data/shadow/storm_watch_prime_emergence/snapshot_2026-06-04.json`: live
  tracking baseline. Do not lose it.
- `scripts/shadow_prospect_storm_board.py`: Prospect Storm Board snapshot
  writer. It writes retained pre-MLB snapshots under `data/shadow/prospects/`.
- Broader Storm Watch / Longball Threat diagnostics live in
  `scripts/diagnose_longball_threat.py`.

Future shadow snapshots must store enough context for bucketed live tracking
and the whiff flag:

- B6-Air score.
- Storm Fuel A2.
- Air EV90.
- xHR/BBE.
- Thunder Rate.
- Barrel/PA.
- Thunder/PA.
- hard-hit air / air-threshold rates when available.
- age.
- previous-season PA.
- priorStatus.
- bucket label.
- bucket confidence.
- contact%.
- whiff%.
- zone contact%.
- chase%.
- K%.
- BB%.
- durabilityTag / contactRiskTag.
- powerAccessTag.
- boomOrBustTag.
- scoutingReportAccessNote.
- fantasyAdp.
- fantasyAdpBucket.
- fantasyAwarenessScore.
- adpSource / adpSourceDate / adpJoinStatus / adpNameMatched.
- milbDataStatus.
- milbHighestLevel.
- milbUpperMinorsPA / HR / HRPerPA / SLG / OPS / BBRate / KRate.
- milbAllLevelsPA / HR / HRPerPA / SLG / OPS / BBRate / KRate.
- milbPowerSupportScore.
- milbApproachSupport.
- milbPowerCategory.
- milbSampleCaution.
- milbSource / milbSourceSeasonRange / milbJoinStatus / milbNote.
- mlbProductionObviousness.
- consensusContextCategory / consensusContextTags.
- future prospect consensus fields from a dated manual/member export when
  available: fanGraphsRank / FV / risk / ETA / level / org / position /
  joinStatus, or equivalent Pipeline preseason rank fields.
- future Prospect Storm Board bridge fields when a player graduates:
  pipelineRank / pipelineAge / pipelineLevel / pipelinePA / pipelineHR /
  pipelineHRRate / pipelineSLG / pipelineOPS / pipelineBBRate / pipelineKRate /
  prospectStormSupport / prospectCategory / prospectSourceDate.

The retained baseline snapshot may predate some later context additions, but
future snapshots written by `scripts/shadow_storm_watch.py` should include these
fields. Snapshot upgrade is an enabler, not new research.

Uniqueness vs consensus TODO: future live validation should compare Storm Watch
names against public consensus / projection / prospect context to answer the
product question: did Storm Watch surface useful names before the broader market
did? Do not implement external consensus scraping until the internal live
workflow is stable.

Durability cache scripts status: the cache builder, discipline metric
derivation, validation manifest, and model diagnostic currently exist as local
research artifacts rather than durable repo scripts. Promote them into
`scripts/` before rerunning or automating the test. Do not commit the large
pitch-cache files unless that is explicitly intended.

15. What Happens Next
---------------------

The current backtest arc has likely given what it can. The major orthogonal
axes tested so far point in the same direction: Prime can be trusted, Early is
candidate/context, and durability is not a score modifier. Do not re-open Storm
Watch with another backtested variable unless live data, more seasons, or a
genuinely new data source changes the question.

The next moves:

1. Live 2026 validation: do the surfaced Prime Emergence names actually produce
   over the season? This is the real test.
2. Accruing seasons: Early's volatility is a more-data problem. Its reliability
   will firm up, or not, as 2026/2027/2028 are added.
3. Snapshot upgrade: store the context fields needed for bucketed live tracking
   and the whiff bust-risk flag.

When Storm Watch is next touched, it should be to look at whether live names
produced, or to upgrade the shadow snapshot plumbing. The product is the cohort
plus live validation, not a better backtest number.

Verification command:

```bash
PYTHONPYCACHEPREFIX=data/cache/pycache .venv/bin/python scripts/diagnose_longball_threat.py --seasons 2021 2022 2023 2024 2025
```

This file evolves with the research. When a Storm Watch decision is made or a
live validation check is run, update it here so the thinking stays in the repo,
not scattered across chat history and multiple tools.
