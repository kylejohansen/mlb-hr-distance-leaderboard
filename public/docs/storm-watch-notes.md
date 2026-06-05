The Long Ball - Storm Watch Notes
=================================

The internal state-of-thinking for Storm Watch. Read this before any Storm
Watch diagnostic, formula, or display work.

Why this file exists: Storm Watch is a long-running research thread worked
across three tools - Codex runs the diagnostics, GPT cross-checks, Claude
interprets. The conclusions and open questions have lived only in chat, which
means they evaporate between sessions and get re-litigated from scratch. This
file is the single durable home for what we've decided, what we've ruled out,
and what's still open. The code (the shadow/eval scripts) describes what Storm
Watch does; this file describes why, and what we believe about whether it works.

Status as of June 2026: internal / On Deck shadow. Not public.

1. What Storm Watch Is
----------------------

Storm Watch is LBI's predictive sibling - not LBI, not descriptive, not a
public flagship. Its job is near-term: which hitters are about to produce home
runs they haven't produced yet?

It is not a season projection system. It is not trying to beat Steamer / THE
BAT X / Marcel. Comparing it to professional projection systems is a category
error - those project a full season; Storm Watch is a short-horizon in-season
signal. The honest public framing avoids "projection," "forecast," "expected
HR," "rest-of-season" and uses "signal," "watchlist," "surge," "radar,"
"power heating up."

2. The Big Pivot: full-league is dead, the niche is alive
---------------------------------------------------------

Full-league six-week HR prediction is dead. No clean model reached the 0.55 /
0.58 live threshold (best hybrid around 0.526, Ridge ceiling around 0.535, B6
around 0.519). The stopping rule worked - we did not talk ourselves into
shipping a mediocre full-pool predictor. Do not revisit full-league prediction
expecting a different answer; the ceiling is real.

The viable product is a narrow cohort: Prime Emergence.

Prime Emergence = age 24-25 hitters with no-prior / low-history MLB power
records, whose B6 profile is flashing before their HR track record has caught
up.

The baseball mechanism: at 21-23, players have loud tools but unstable approach
/ playing time / MLB adjustment. At 24-25 they often have physical maturity,
better pitch recognition, stable swing decisions, and enough MLB batted-ball
data to score - but not enough MLB HR history to be priced in by the market /
projection ecosystem. At 26+, the market usually already knows. Storm Watch
finds the moment tools become usable MLB power before the HR column reflects it.

This niche is more "The Long Ball" than a full-league predictor ever would have
been: an emerging-power radar is distinctive and fun; a HR-rate table competing
with Steamer is neither.

3. The Score: B6 (do not formula-chase)
---------------------------------------

B6 is the Storm Watch score. Keep it clean.

B6 = 60% Storm Fuel + 20% Barrel/PA + 20% HR-Window Thunder/PA

Storm Fuel:

- 50% stabilized xHR/BBE
- 25% stabilized HR-Window Thunder Rate
- 25% EV90

Conceptual split worth preserving: Storm Fuel = the ingredients (how much raw
longball energy is in the profile); B6 / Storm Watch = the alert (is that energy
likely to convert to near-term HR, accounting for how often it's showing up per
PA). EV90 is the early raw-power signal (stabilizes fast, shows up before
results); Thunder is the year-round HR-window-contact spine; xHR/BBE is the full
EV/LA portfolio.

The key framing: the state got clearer, not the formula. Prime Emergence works
because of which players B6 predicts well, not because B6 got better. Do not
bake age into B6. Use the cohort (24-25 + no-prior/low-history) as a confidence
state on top of the clean score, never as a formula input. B6 finds the signal;
the 24-25 no-prior state tells us when that signal is most predictive.

Pulled-airborne is confirmation / tiebreaker only - not part of the score. B6 +
pulled-airborne improves correlation (0.589 -> 0.611 Pearson on the cohort) but
does not improve top-decile lift over B6. So it is a confirmation signal beside
the score, not folded in. Public story: B6 is the score; pulled airborne tells
us whether the swing shape is converting that power into HR-friendly contact.

4. No-prior / low-history stabilization
---------------------------------------

These constants originated in the old internal Storm Watch v1 branch
(`codex/storm-watch-v1`) and still apply to the current B6 / Prime Emergence
work. Recording them here preserves the reasoning so the superseded branch can
be deleted without losing the rationale.

For players with real prior MLB data:

- xHR/BBE: blended toward prior-season power shape, M = 150
- HR-Window Thunder: blended toward prior, M = 100
- EV90: raw / current only (stabilizes quickly; it is the early-signal
  ingredient)

For players with no prior MLB data:

- xHR/BBE and Thunder shrink toward league average at M ~= 317
- EV90 stabilizes faster, M ~= 62

The shrinkage is intentional skepticism, not a bug (the Murakami lesson): a
rookie with a few loud balls should not rocket to the top until the sample
supports it. EV90 lets real raw juice show up early; xHR/Thunder stay skeptical
until BBE accumulates.

Confirmed not the bottleneck: sweeping the no-prior M values (xHR/Thunder at
250 / 317 / 400; EV90 at 50 / 62 / 75 / 100) barely moved results - all around
0.560. Keep M=317 and EV90 M=62. Do not re-tune these chasing decimals.

5. The evidence (and how to read it honestly)
---------------------------------------------

Prime Emergence aggregate:

| Pool | n checkpoints | unique players | Pearson | Spearman | Top-decile lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| Age 24-25 + no-prior/low-history | 135 | 59 | 0.589 | 0.583 | +77.4% |

Stability gate - passed. Year-by-year B6 Pearson: 2021 .545 / 2022 .594 / 2023
.553 / 2024 .659 / 2025 .669. The relationship is spread across all five
seasons (every year >= .545), not a one-year artifact. This is the green light
for the cohort framing.

Critical methodological insight: the cohort is intrinsically small (around
12-50 players/year). That makes per-year top-decile lift mathematically
unreliable - a 10% decile of n=18 is about 2 players. The per-year lift
volatility (2025 +8%, 2023 +172%) is 1-2-player noise, not a signal about year
quality. The +8% in 2025 is not evidence of decay, and the +172% in 2023 is not
evidence of triumph.

Trust: Pearson (uses the whole cohort, stable across years) and the aggregate
lift (+77.4%, n=135 - the aggregate decile is around 13-14 players, big enough
to mean something).

Do not trust: any single-year top-decile lift on this cohort. Never judge the
product by a single-slice tail metric.

Note: this is about the cohort being intrinsically small, not about 2026 being
partway through - the backtest years use complete-season data.

6. Open checks before public prominence
---------------------------------------

Priority order:

1. Leave-one-year-out aggregate test - does the aggregate stay strong when any
   single season is removed? This is the key remaining stability check, and it
   matters precisely because the per-year samples are individually too small to
   trust.
2. 2026 live board smell test - do the current surfaced names pass baseball
   intuition?
3. Live 2026 production - do the higher-ranked Prime Emergence names actually
   out-produce over the season? This is the real test. The backtest has given
   what it can; live in-season names are the proof. The baseline snapshot
   (`data/shadow/storm_watch_prime_emergence/snapshot_2026-06-04.json`) is the
   start of that clock - do not lose it.

Do not grant public prominence on backtest alone. Keep On Deck / internal until
live 2026 names produce.

7. Product shape & guardrails
-----------------------------

Ship one validated thing. Only Prime Emergence (24-25 + no-prior/low-history)
is validated. Do not build the four-tier taxonomy (Prime / Early / Late /
Import). Early (21-23) already performs worse; Late (26-28) is untested.
Scaffolding unvalidated tiers around the one validated thing is over-building.
Validate one thing at a time.

It is a focused watchlist by nature (the cohort is small - the 2026-06-04
snapshot had 10 Prime Emergence players out of 240 scored). For a watchlist that
is a feature, not a bug: focused and scannable.

Judge it by the right metric. It is a watchlist, so name-quality and
multi-year/full-cohort lift matter more than Pearson. Never judge it by
single-slice top-decile lift.

Honesty bar for any tease: "in development" / "shadow," describe what it does
(early surge / emerging-power detection), never a precision claim ("most
accurate predictor" - it does not clear the pro-projection bar, by design). The
competitive-edge angle ("before your league does") is fine because it is about
the experience, not a precision claim.

Identity sentence:

Storm Watch is not a universal HR predictor. It is an emerging-power radar. Its
highest-confidence state is Prime Emergence: age 24-25 hitters with limited MLB
power history. B6 is the score; pulled airborne is the confirmation signal.

8. Infrastructure
-----------------

- `scripts/shadow_storm_watch_prime_emergence.py` - shadow snapshot writer. B6
  primary score, cohort 24 <= age < 26 + no-prior/low-history, records
  pulled-airborne/PA as confirmation. Writes retained snapshots under
  `data/shadow/storm_watch_prime_emergence/`.
- `scripts/eval_shadow_storm_watch_prime_emergence.py` - evaluator between two
  snapshot dates; measures forward HR/PA, HR/600, HR/BBE for the earlier
  watchlist; compares B6, B6+pulled-airborne-confirmation, and all-pool B6
  reference.
- `data/shadow/storm_watch_prime_emergence/snapshot_YYYY-MM-DD.json` - retained
  snapshots. The 2026-06-04 snapshot is the live-tracking baseline.
- Broader Storm Watch / Longball Threat diagnostics live in
  `scripts/diagnose_longball_threat.py`.

Verification command:

```bash
PYTHONPYCACHEPREFIX=data/cache/pycache .venv/bin/python scripts/diagnose_longball_threat.py --seasons 2021 2022 2023 2024 2025
```

This file evolves with the research. When a Storm Watch decision is made or a
check is run, update it here so the thinking stays in the repo, not scattered
across chat history and multiple tools.
