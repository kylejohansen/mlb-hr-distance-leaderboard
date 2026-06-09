Market-Awareness Gap & "Surprise Pop Done Right" — Concept Notes (June 2026)
Preserves the idea behind the pulled "Surprise Pop" public tag, the corrected design (in-season
market expectation = DFS pricing, NOT ADP), and the broader "market-awareness gap" theme that threads
through several parts of the project. This is a CONCEPT/DIRECTION note, not a build spec.

Why the original Surprise Pop tag was pulled
The public hitter-card "Surprise Pop" tag (src/main.js, getHitterContext) was removed June 2026. It
fired when LBI ≥ 110, HR ≥ 5, HR/600 pace < 40, and sourceRank > 20.
The fatal flaw: sourceRank is just the player's position in the sorted public LBI JSON — it has no
relationship to whether the player is actually "surprising." It used "not top-20 by current LBI
ordering" as a proxy for surprise, which is meaningless. It fired on 35 players including Ohtani,
Acuña, Julio, Devers, Witt, Freeman, Riley — the most famous, LEAST surprising stars in baseball.
Design principle learned (durable): a public characterization tag that ASSERTS something
interpretive ("surprising," "ahead of market") must be derived from a real, verifiable baseline.
A proxy like list-position will fire wrongly on marquee names and erode trust. Public interpretive
claims must either be transparently derived from quantities the user can see (like the Power × Pesky
quadrant's visible axes, or Power Gap's xHR-vs-HR), OR stay internal until they have a real baseline.
Don't patch a broken-baseline tag with threshold tweaks — if the underlying variable measures nothing,
no threshold makes it correct.
The CONCEPT, though, is good and worth building right: a hitter producing home-run power beyond what
the market expected of them. On-brand, fun, and directly serves the fantasy audience. It just needs
a real "expected" to be surprising relative to.

The key insight: market expectation has TWO regimes
The original idea reached for "market expectation" but had no real source. The correct source depends
on WHEN you're asking — and this is the central insight to preserve:
Preseason → ADP (Average Draft Position).

A frozen snapshot of what the market thought in March. Good for "was this draftable value missed?"
BUT: ADP goes stale the moment the season starts. Post-draft, nobody re-runs drafts, so ADP stops
being "what the market currently thinks" and becomes "what the market thought before any games."
AND: ADP only carries surprise-signal in the SPARSE TAIL. Serious fantasy players have ~the top 250
memorized, so inside the top 250 ADP is just "obvious players in roughly obvious order" — no surprise
info. A guy drafted 350 instead of 500 is notable precisely because it's off the beaten path where
the market is thin/inefficient. Narrow, fragile place to build a stat.
Verdict: ADP is an OK historical/lookback reference, a poor in-season expectation.

In-season → DFS pricing (DraftKings / FanDuel salary).

The market REPRICES every player every single day based on everything — recent form, matchup, park,
who's hot. It's the closest thing to a live, liquid, continuously-updated market consensus valuation
of a player that exists in baseball.
Prices the WHOLE pool daily (not just the tail), so it has live signal across all players.
"This hitter is producing power well above what his DFS salary implies the market expects" = a REAL,
live, defensible surprise — surprising relative to TODAY's market price, not March's draft position.
This is the correct foundation for an in-season "Surprise Pop"-style stat.

Shape (if built): ideally a WEEKLY MEDIAN DFS salary (a single day is matchup-noisy; a week's
median smooths to "how the market values this player's baseline right now"). Likely needs normalizing
for matchup/park/lineup-slot context, since raw salary is contaminated by the day's situation, not just
talent/expectation. Collection is ongoing (capture daily, store, roll the median) — a small pipeline of
its own, not a one-time join.

The bigger theme: the "market-awareness gap"
"Production the market didn't expect" is one face of a recurring theme — the gap between a hitter's
real power and the market's awareness of it. This theme keeps reappearing across the project, and
naming it is more valuable than any single stat:

Storm Watch (predictive): young hitters whose power is forming before EITHER market prices them
in. The "emergence gap." Power ahead of the track record.
Surprise Pop / DFS-based (descriptive, in-season): hitters ALREADY outproducing the market's
current (DFS) price. Power ahead of the live price.
ADP-based (descriptive, preseason/lookback): draftable value the preseason market missed.

A coherent framework: three lenses on the same gap, each with its proper data source and time horizon.
This tells you WHICH baseline to reach for depending on the question — predictive (Storm Watch),
in-season market (DFS), or preseason market (ADP).

Status / open gate

Original public Surprise Pop tag: PULLED (broken baseline). Concept preserved here.
The corrected in-season concept depends on DFS pricing data accessibility — the open gate.
Whether DraftKings/FanDuel salary data is obtainable, on acceptable terms, at reasonable cost, with
useful historical depth, is the gating question. (Feasibility check pending/attached.)
This is a BACK-POCKET direction, not a now-build. If DFS data is inaccessible or terms are bad, the
concept stays documented and we don't sink design time into it. If it's accessible, it's worth
designing as the in-season market-awareness layer.


DFS data feasibility (checked June 2026)
The gating question — is DFS salary data obtainable, on acceptable terms, at reasonable cost?
There is NO official DraftKings/FanDuel public API. Official access is B2B-only via business
development. Everything else is unofficial. Three real routes exist, in rough order of cleanliness:

Official daily contest CSV (cleanest legit route). DraftKings publishes a downloadable
contest CSV from each contest page containing player IDs, salaries, positions. This is what
virtually every public DFS optimizer actually uses (e.g. pydfs-lineup-optimizer reads it directly).
No API key, no account-scraping. Pro: legitimate, free, structured. Con: it's a per-contest
manual download — daily collection would need a habit/automation, and historical depth means you'd
have had to be collecting it all along (no clean backfill of past salaries this way).
Reverse-engineered DK endpoint (api.draftkings.com/draftgroups/v1/...draftables). Returns
current players + salaries as JSON, no auth. Pro: programmatic, free, current-day. Con:
unofficial, breaks when DK changes it, and using it violates DK's ToS. Fragile — same class of
problem as the FanGraphs board pilot. Only gives CURRENT slates (no history).
Third-party aggregators / scrapers (Apify actors, RotoGrinders-style feeds, FTN Data's DFS
Salary Feed). Pro: some offer historical depth and multi-site (DK/FD/Yahoo). Con: mostly
PAID, variable reliability, and the scraper-based ones inherit the same ToS/fragility issues.
FTN Data appears to be a legitimate paid REST API with a DFS salary feed — the most "real" paid
option if budget is acceptable.

The hard truths for THIS project:

No clean historical backfill. Past DFS salaries aren't freely/cleanly available — the legit CSV
route only gives you what you collect going forward. So an in-season DFS-based stat would start
accumulating from whenever collection begins; it can't retroactively price 2026's earlier weeks.
It's an ongoing collection pipeline, not a one-time fetch. "Weekly median salary" means capturing
daily, storing, rolling — a new small data habit the project would own (like a daily Statcast pull,
but for a flakier, ToS-encumbered source).
ToS/fragility risk on the free programmatic routes — the same lesson as FanGraphs: scraped/
reverse-engineered sources are fine for a pilot but a liability to build a public stat on.

The reframe — these aren't costs, they're the setup for a CLEAN PROSPECTIVE EXPERIMENT:

"No backfill" = leakage-proof by construction. Forward-collected DFS prices capture the market's
expectation AS IT ACTUALLY WAS, in real time, before the outcome is known. That's a prospective
dataset — the gold standard, and exactly what this project has fought for everywhere else
(checkpoint-clean caches, point-in-time PA, the whole data-integrity arc). You literally cannot peek
at the future when you're recording the present. A backfilled DFS history would always be suspect
(revised? point-in-time accurate?); a forward-collected one is trustworthy because we built it
leakage-free ourselves. No-backfill is a FEATURE here.
"Ongoing collection" = a compounding asset, not a recurring cost. It's the same shape as the
daily Statcast pull this project already runs. Every day it runs, the prospective dataset gets
richer at zero marginal effort. The waiting IS the experiment: record the price now, let the games
happen, measure what the player did against what the market charged for him. Same structure as Storm
Watch live validation (record the signal, evaluate the forward window).
Time asymmetry → start NOW. The dataset's value is a function of how long you've been collecting.
Collection and stat-building are SEPARABLE. Start the cheap, compounding, leakage-free collection
immediately; build the stat whenever the data is deep enough. Waiting to "be ready to build" just
restarts the clock later. We have to start somewhere — start now.

Revised posture: START THE COLLECTION NOW. Build the stat later.
Do NOT build the Surprise Pop stat yet. DO start capturing daily DFS prices now, because the data is
the long pole and it's cheap to collect. Preconditions for CLEAN capture (a prospective dataset is only
as good as the rigor of its capture — get these right from day one or you accumulate a subtly-flawed
record you'd wrongly trust):

Player identity join. DK CSVs use their own names/IDs. Need a stable, reliable join from DK
identifiers to OUR player IDs (the same join-discipline that's bitten this project before — accents,
name variants). #1 thing to nail; a flaky join makes price-vs-production garbage.
Consistent snapshot rule. Define which slate (main slate?), captured at the same point each day
(pre-lock?), every day. Don't mix slate types across days or the weekly median compares apples to
oranges. Define once, stick to it.
Point-in-time, append-only storage. Store each day's price WITH its date, immutably, never
overwritten — so the prospective integrity (what the price WAS on that date) is preserved. This is
the leakage-proofing made literal.
Pilot first. Start collecting, but validate the collection on a small window before trusting it
— confirm the join works, prices look sane, capture is consistent. Same pilot-first discipline as
the durability cache. Prove a week clean before relying on it.

When the prospective data is deep enough: build the stat INTERNAL/shadow first, validate the "surprise"
signal against marquee sanity checks (the Ohtani test), and only THEN consider a public surface —
NEVER repeating the Surprise Pop mistake of a public market-claim before it's proven.
Source for collection: the free official DraftKings daily contest CSV (legit, no account/key) is the
right collection source — not the reverse-engineered endpoint or scrapers (ToS/fragility). Build the
collection habit around the legit CSV.

Concept preserved June 2026: "Surprise Pop done right" = live power production (LBI / HR pace) vs.
in-season market expectation = DFS pricing (NOT ADP). Part of the broader market-awareness-gap theme
(Storm Watch = predictive, DFS = in-season, ADP = preseason). DFS feasibility: no official API; cleanest
route is DK's free daily contest CSV. Key reframe: no-backfill = leakage-proof prospective data, a
FEATURE. START COLLECTION NOW (cheap, compounding, leakage-free) with pilot-first capture rigor (player
join, consistent snapshot, append-only point-in-time storage); build + validate the stat internally
later, public only once proven.