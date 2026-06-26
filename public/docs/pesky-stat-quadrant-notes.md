# Pesky Stat / Quadrant Notes

Status: internal product notes. Do not treat this as public copy until the UI
language is reviewed.

## Canonical Decisions

- Pesky = contact%, plus-scaled, where 100 equals average among the LBI
  qualified hitter pool.
- The Power x Pesky quadrant uses LBI on the power axis and Pesky/contact% on
  the access axis.
- Pesky is the clean counterweight to LBI because it is simple, stable, and
  directionally intuitive: higher means harder to miss.
- No blend replaces Pesky/contact% as the quadrant axis.
- Two-strike battler traits are real but qualitative. Two-strike foul rate is
  distinct from contact%, but too noisy to carry a scored axis by itself.
- Pesky's Pole Tax stays branding/copy around Cheapies, short-porch context, and Park
  Portability context. It is not a new stat unless a distinct future use case is
  proven.

## Pest Traits / Pest Factor Distinctness Check

The final Pest Factor check tested whether a composite "true at-bat pest" score
should become its own stat, separate from Pesky/contact%.

Candidate tested:

True Pest v1 =

- 35% contact%
- 25% two-strike foul rate
- 20% two-strike non-K rate
- 15% pitches/PA
- 5% BB/HBP rate

Decision: do not ship Pest Factor as a leaderboard stat or public score right
now.

True Pest v1 failed the distinctness bar:

- corr(True Pest v1, contact%) = .828
- corr(True Pest v1, Pesky) = .828

The cutoff was .80. This means the score is too much like Pesky/contact% with
extra seasoning. True Pest v1 produced some top-10 texture changes, but the
underlying score was still contact-driven.

Deep PA rate alone is not a pest stat. It often captures dangerous hitters whom
pitchers work carefully, not necessarily hitters who are true pests. Deep PA
non-K rate and deep PA BB/HBP rate are useful context and validation fields, but
not current formula inputs. Reached-base-after-deep-PA remains validation and
context only. HBP is flavorful, but noisy.

Sam Antonacci is best described as Basepath Pest with Contact Pest support, not
as a pure spoiler/grinder profile. His MLB pitch-sample read was more about
contact, non-K survival, and getting aboard by annoying means than elite
two-strike foul pressure.

## Pest Trait Tags

Use a tag suite instead of one composite Pest Factor score. The tags are context
for player cards, scouting notes, or internal reports; they are not replacements
for Pesky and should not alter LBI.

### Spoiler

High two-strike foul rate with enough two-strike foul volume.

Captures the hitter who keeps an at-bat alive by fouling off pitches. This is
useful texture because two-strike foul rate is distinct from contact%, but the
metric is noisy enough that it should stay a tag, not a scored stat.

### Grinder

High pitches/PA plus high 5+ pitch PA rate.

Captures hitters who make pitchers work and frequently reach deeper counts.
This can overlap with dangerous hitters being pitched carefully, so it is
context rather than proof of pest skill.

### Deep Count Survivor

High 5+ pitch PA non-K rate with enough deep-PA volume.

Captures hitters who survive after the plate appearance gets long. It is more
useful as context or validation than as a formula component because it is still
contact-adjacent and can be sample-sensitive.

### Basepath Pest

High BB/HBP rate or high 5+ pitch PA BB/HBP rate.

Captures hitters who make the plate appearance hurt by reaching through walks or
getting hit. HBP should be capped or handled as tag-only flavor because it is
noisy and can dominate small samples.

### Contact Pest

High contact% and low whiff%.

Captures the clean "hard to miss" hitter. This is mostly the public Pesky
archetype, so it should reinforce Pesky rather than become a separate score.

### Volatile Access

High power with high whiff/contact risk.

Captures the contrast profile: loud power, but unstable access. This belongs
beside the Power x Pesky quadrant and Boom-or-Bust language as context, not as a
Pest Factor input.

## Product Use

Near-term use should be internal context only:

- Player-card notes.
- Internal note language.
- Internal review tags.
- Possible future fun leaderboard only after UI review.

Do not expose Damage Access or Pest Factor as public stats. Do not multiply
power by contact. Do not change LBI, Pesky, or the Power x Pesky quadrant.
