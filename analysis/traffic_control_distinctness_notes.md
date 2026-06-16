# Traffic Control Distinctness Closure Notes

## TL;DR

The Traffic Control / TC+ distinctness arc is closed.

The old quotient TC+ should not become a public headline stat. It failed the distinctness test because it was effectively K-BB% in a traffic wrapper. The Command+ x Traffic+ quadrant also should not be built as a product because the axes were too collinear and the Traffic Dodger corner did not meaningfully exist. Men-on K-BB% and RISP K-BB% showed useful descriptive texture against LOB%, but split-half stability was too weak for a precise scored leaderboard. Escape Split is dead.

The only survivor is a possible future internal, coarse, extremes-only men-on K-BB texture badge. Nothing public should ship from this right now.

## What Was Tested

- Baseline TC+ quotient:
  `plus-scaled [100 * (K% - BB%) / xWHIP_lgBABIP]`
- Command+ x Traffic+ decomposition:
  - Command+ = plus-scaled K-BB%
  - Traffic+ = plus-scaled inverse xWHIP_lgBABIP
- Base-state command splits:
  - Bases empty K%, BB%, K-BB%
  - Men on K%, BB%, K-BB%
  - RISP K%, BB%, K-BB%
- Escape Split:
  `men-on K-BB% - bases-empty K-BB%`
- LOB%/strand-rate context via an ER-based LOB proxy, used only as a context comparison.

Base states were taken from the first pitch of each PA, with outcomes from the terminal pitch. The diagnostic was scoped to regular-season dates using `scripts/data_integrity.py`.

## Pre-Registered Rules

- If `r(TC+, K-BB%) >= ~0.90`, TC+ is a K-BB clone and should not be a headline stat.
- If `|r(Command+, Traffic+)| < ~0.60`, the two-axis quadrant has enough independence to be considered.
- If men-on/RISP split-half stability is `>= ~0.55`, it can be considered as a scored leaderboard number.
- If men-on/RISP split-half stability is closer to noisy split territory, it should be a qualitative badge/context read only.
- Future WHIP prediction was not an optimization target and should not reopen this branch.

## Verdict Table

| Candidate | Evidence | Verdict |
|---|---|---|
| Quotient TC+ | `r(TC+, K-BB%)`: all `0.982`, starters `0.986`, relievers `0.980` | Dead as a public stat |
| Gamma TC+ variants | Prior testing found the gamma variant won future-WHIP RMSE but was a K-BB clone (`Spearman ~0.997` vs K-BB) | Dead |
| Command+ x Traffic+ quadrant | `r(Command+, Traffic+)`: all `0.851`, starters `0.880`, relievers `0.828`; Traffic Dodger corner did not meaningfully exist | Dead |
| Men-on K-BB% | Descriptive gap versus LOB proxy survived: `r(LOB proxy, Men-On K-BB%) = 0.211`; split-half stability only `0.335` overall | Internal texture candidate only |
| RISP K-BB% | Descriptive gap versus LOB proxy survived: `r(LOB proxy, RISP K-BB%) = 0.189`; split-half stability only `0.168` overall | Context only |
| Escape Split | Split-half stability `0.024` overall | Dead entirely |

## Old Quotient TC+ Verdict

The quotient is too close to K-BB% to justify a new public stat. Its traffic denominator changes some texture, but not enough to create a distinct product. Keeping it would repeat the same failure mode as the predictive gamma version: a command stat disguised as something broader.

Closed conclusion: TC+ quotient is dead as a public stat.

## Command+ x Traffic+ Quadrant Verdict

The quadrant construction does not have enough axis independence. Command+ and Traffic+ were highly correlated, and the expected low-command/high-traffic-prevention corner did not meaningfully populate. That means the archetype board would mostly re-label command strength rather than reveal genuinely separate pitcher shapes.

Closed conclusion: the Command+ x Traffic+ quadrant is dead.

## Men-On K-BB / RISP K-BB Verdict

Men-on K-BB% and RISP K-BB% do show a real descriptive contrast with LOB%/strand rate. That matters because fans often read LOB% as strand skill, but the diagnostic suggests LOB% is mostly an outcome/mirage layer while men-on command is the cleaner skill read.

However, the stability is not strong enough for a precise leaderboard:

- Men-on K-BB% odd/even split-half Pearson: `0.335`
- RISP K-BB% odd/even split-half Pearson: `0.168`
- Escape Split odd/even split-half Pearson: `0.024`

Closed conclusion: men-on and RISP K-BB are useful texture, not a scored public stat.

## Escape Split Verdict

Escape Split is killed entirely. There was no stable individual "bears down with runners on" skill in K-BB terms from this diagnostic.

Closed conclusion: do not preserve Escape Split as a badge input, leaderboard, or future stat candidate except as a negative result.

## What Survives

Only a narrow future possibility survives:

- a coarse qualitative men-on K-BB badge
- internal/experimental only
- top-tail or extremes-only
- paired beside LOB% as strand-support texture
- never blended with LOB%
- not a precise scored leaderboard

## What Is Explicitly Closed

Do not revive:

- quotient TC+
- gamma TC+
- Command+ x Traffic+ quadrant
- Escape Split
- "bears down with runners on" as a stable scored skill

## What Would Be Required To Reopen

Future work may revisit only:

- multi-season pooled men-on K-BB badge testing
- top-tail/extremes-only strand support texture
- LOB% mirage contrast shown beside men-on K-BB, not blended into it

To reopen the badge idea, a future diagnostic should pool multiple seasons, separate starters and relievers, require larger traffic-split samples, and test whether only the most extreme men-on K-BB performers retain enough split-half or year-to-year stability to justify a qualitative label.

No public leaderboard, public stat, product quadrant, or production workflow should be built from this diagnostic right now.
