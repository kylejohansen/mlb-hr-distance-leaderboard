The Long Ball — Assumption Finder
A pre-flight checklist for catching unstated assumptions before they cost a session.

Read this when: kicking off any non-trivial change, reviewing a prompt before sending it to Codex, or interpreting a result before acting on it. It is deliberately this project's failure modes — every item here is a real way an assumption has actually slipped through on The Long Ball, not a generic "measure twice" platitude.

Why this exists: the workflow is assumption-prone by design. Work is split across Codex (builds), GPT (cross-checks), and Claude (strategy) — so any one tool sees only part of the picture. Conclusions live in chat, not the repo, so they evaporate between sessions. And renders have repeatedly lied. That combination means "we both assumed X" is the single most common way time gets lost here. This file is the antidote.

How to use it: you don't run all of it every time. Match the section to the task — building, prompting, interpreting a stat, or planning — and run that section's questions. If a question can't be answered, that's the assumption. Go find the ground truth before proceeding.


0. The One Question
Before anything else, ask:

What am I treating as known that I haven't actually verified this session?

Most assumption failures on this project are a stale belief — true once, assumed still true. "Step A was merged." "cookedPlus doesn't exist." "The border is mustard." Each was held confidently and was wrong or unverified. If a belief is load-bearing for the next action and hasn't been checked today, against ground truth, it's an assumption, not a fact.


1. Ground-Truth Assumptions (the render/data layer)
The lesson learned the hard way, repeatedly: when a report and your eyes disagree, neither the report nor the screenshot is automatically right — go to ground truth.

Is this belief from a fresh check, or a possibly-stale one? Codex's screenshots have shown cached/old state at least three times (Pull Pop N/A, Hot Dog table, the daily-card red borders). Its computed-style / DOM reads are trustworthy; its screenshots are not when a stale server is running.
For a visual/ambiguous change (borders, colors, layout, collisions): don't re-prompt for more screenshots. Kill the server, read getComputedStyle from a fresh cache-busted server, and confirm in your own incognito/hard-refreshed browser. Your own browser on a deployed build is the only fully-trusted signal.
For an unambiguous change (a 2-line removal, a field swap): trust the diff, not the screenshot. +0 -2 removing two named elements needs no render to confirm.
Does the thing I'm about to "fix" actually need fixing? (The daily-card borders were red the whole time — the fix had already worked; the screenshots were stale. We almost "fixed" a non-problem three times.)
Is the data actually there before I build UI for it? cookedPlus already existed — the audit turned a "build a scale" job into a one-field swap. Always check "does this already exist / is this loadable" before building. (Applies to: the HDS season files, any new stat display.)


2. Prompt Assumptions (before sending to Codex)
Codex does exactly what the prompt says and fills gaps with its own assumptions. Catch yours before it inherits them.

Does "the X" mean the same thing to me and to Codex? "The border" cost several rounds because it meant the outer frame to Codex and both borders (frame + under-title rule) to you. Name elements specifically and by position.
Am I assuming a cause without diagnosing it? The mustard borders weren't an override rule — they were the header fill touching the edge, plus stale renders. Several prompts "fixed" a cause that wasn't the real one. For anything non-trivial: diagnose-first, read-only, report before changing.
Have I scoped it to ONE thing? Bundling unrelated changes is the contamination pattern. "Restyle the cards" + "unify the spacing" + "rewrite the copy" should be separate branches. Same page region is OK to pair; different kinds of change are not.
Did I state the stop condition? "No commit until I review," "if the data doesn't exist, STOP and report — don't fabricate it." A prompt without a stop condition assumes Codex will pause where you'd want it to. It won't.
Am I assuming the branch I'm building from is clean? Check what branch you're on and whether the prior step actually merged before branching again. (Step A sat "commit-ready" but unmerged while we nearly branched on top of it.)


3. Result Assumptions (interpreting a stat / diagnostic)
The numbers come back from Codex or GPT; the interpretation is where assumptions hide.

Is this difference real, or inside noise? A 0.006 Pearson gap is a tie, not a win — the same standard that killed full-league Storm Watch and flagged Longball Threat as "rebranded Barrels/PA." Don't let any tool frame a noise-level edge as a winner. Break ties toward simpler and more on-brand, not toward the spreadsheet winner.
Is this metric trustworthy at this sample size? Top-decile lift on an n=18 cohort is ~2 players — mathematically meaningless. Per-year lift swung +8% to +172% on tiny cohorts; that's noise, not signal. Trust whole-pool metrics (Pearson) and aggregate-sample metrics over single-slice tail metrics. Know which metric your sample can actually support.
Does the mechanism back the number, or is it a post-hoc story? The 24-25 no-prior cohort works because of a real reason (tools mature before the HR column is "priced in"). A number with a sound mechanism is more trustworthy than one without. Be suspicious of a great number with only a story attached after the fact.
Is the recommending tool being over-optimistic? Codex called O4 "the winner" over a 0.006 gap; GPT proposed a four-tier taxonomy off one validated tier; both listed guardrails then skipped past them. Treat "ship it / it's strong enough" from any tool as a claim to verify, not a conclusion to adopt. (You catch this well — this item is to keep doing it.)
What would have to be true for this to be wrong, and have I checked that? The stability gate, the leave-one-year-out — these exist to test the failure case, not to gather more support for the hoped-for answer. Always ask what would disconfirm the result, then test that.
Am I judging the product by the right metric? Storm Watch is a watchlist, so name-quality and lift matter more than Pearson. Match the success metric to what the product actually is.


4. State Assumptions (what's true about the project right now)
The multi-tool, across-sessions workflow means project state drifts out of sync with belief.

Where does this conclusion actually live? If a theory/decision exists only in a chat, it will evaporate. Anything you'll need next session belongs in the repo (a notes.md per research thread, the design guide, this file). The Storm Watch viability theories, the design decisions — written down or gone. (The conflation problem, stated plainly: Codex runs it, Claude interprets it, GPT cross-checks it, and none of it persists unless written to the one place that does.)
Is the data pipeline a second author here? It pushes to main on its own — "push rejected, rebase" recurs, and a manual data regen needs the season-file copy (cp public/data/hr-distance-latest.json public/data/longball-index-{year}.json) the automated workflow does for you.
Display change vs. data change? Display = source-only. Data/field = full pipeline (regenerate → build → commit data → push → season-file copy). Assuming a data change is "just frontend" ships a stale board.
Am I assuming a branch's state I haven't checked? "Likely merged-deletable," "almost certainly dead" are assumptions. git branch --merged / git log before deleting. (This file's author made exactly this assumption about the branch list.)
Is this name/string going to match? Accented names break exact-string search ("José Ramírez" / "Ramírez") — it caused a false "missing player" alarm and is a real join-bug suspect. Search accent-insensitive; suspect encoding on any "missing" accented name.


5. Scope & Honesty Assumptions (before it goes public)
Am I assuming this is more proven than it is? Don't tease/claim beyond what a stat has earned. Storm Watch is "in development," not "the most accurate predictor." Longball Threat isn't teased at all yet because it hasn't cleared its stopping rule. The tease must match the evidence.
Is the label still true after the change? Swapping raw → cookedPlus made "per 100 BBE" wrong everywhere it appeared. When a number's scale changes, every label/caption/unit on it is now an assumption to recheck. A right number with a wrong label is worse than the old number.
Am I building a taxonomy/feature off one validated thing? Ship the one validated segment; don't scaffold the unvalidated tiers around it. Validate one thing at a time.
Is the real test a backtest or live production? For predictive stats, the backtest gives what it can; live in-season names are the real proof. Don't grant public prominence on backtest alone.


The shortest version
If you remember nothing else, ask these five:

Stale? Is this belief from a fresh check today, against ground truth — or assumed-still-true?
Same words? Does "the X" mean the same to me and to Codex?
Noise? Is this difference / metric real at this sample size, or am I reading noise?
Written down? Does this conclusion live in the repo, or only in a chat that will vanish?
Earned? Is the claim/label/tease matched to what's actually been proven?

Most lost time on this project traces to a "no" hiding behind an unasked one of these.

