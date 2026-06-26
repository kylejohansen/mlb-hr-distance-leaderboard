The Long Ball — Design Guide
This is the design language for thelongball.app. Read it before any design or display work. It is the single source of truth for how the site looks and how stats are presented. When a prompt says "follow the design guide," this is the file.

It is intentionally our language — not generic frontend best-practices. Every rule here came from a real decision on this project, and the reasoning is included so the rule can be applied to new cases, not just copied.


1. The North Star
Take the scary stat, make it fun and approachable. Lead with homers. Let the pitcher rabbit holes be optional.

Approachability and fun are not in tension — they are the same move. A jargon-heavy stat is unapproachable because it isn't fun; a fun name with a clear caption is approachable because the name invites you in and the caption lets you stay. FanGraphs is intimidating; Savant is visual; The Long Ball is visual and fun. That's the lane.

The test for anything new: Could a person scrolling Twitter get it in three seconds, and is it fun? If a stat can't be made approachable-and-fun, it doesn't belong on a public surface — it belongs internal (like the shadow/diagnostic stats). "Scary internal, fun public."

Homers are the front door. Pitcher content (Hot Dog Stand, Getting Cooked, Footlongs) is a room you can choose to wander into — never forced on the casual fan. Approachability as architecture.


2. The Three Presentation Principles
These govern how every stat and element is presented. They are all the same underlying instinct: trust the user, and trust the data.
a. Take the scary stat, make it fun and approachable
Rename intimidating concepts into memorable, often snack-like names (Daily Dong, Footlongs, Getting Cooked, Thunder, Pull Pop, Park Portability). The name carries personality; a short caption carries the spec. A good name can sound a little goofy — "Pull Pop sounds like a failed nineties snack" is a feature, not a bug. Memorable beats descriptive, as long as a caption pins down what it measures.
b. State what it is — don't negate what it isn't
Confident framing, not defensive framing. Say "HR-capable contact across all 30 parks." NOT "...not actual home runs." The moment you say "not X," you put X in the reader's head. State the thing positively and let the visual/number carry the rest. Confident framing is approachable framing.
c. Position honest numbers so the insight is the easy conclusion — don't narrate it
Show, don't tell. Put true numbers next to each other so the reader draws the conclusion themselves — a conclusion you reach yourself lands harder than one you're told. Example: showing "23 HR-capable" near "17 HR" silently tells the user "he could have had more" without a single word of narration. Do NOT add auto-generated editorial takes to cards ("Why He's Here" was removed for exactly this reason — see §6).


3. Captions & Naming Grammar
Every stat follows the same grammar:

Fun name → self-explaining number → short, concrete caption.

Name: evocative, memorable, snack-friendly. (Thunder, Pull Pop, Park Portability.)
Number: self-explaining where possible. Prefer "100 = average" plus-scales over raw, unbounded, or abstract-unit rates (a reader can't read "10.0 weighted damage points"; they can read "118, where 100 is average").
Caption: Thunder-length. Concrete spec, no editorializing, no over-explaining. State what it measures, not why it's impressive.
Thunder: BBE 105+ mph at 25-40°
Pull Pop: Pulled air, 100+ mph · 100 = average
Park Portability: HR-capable contact across all 30 parks.

Captions must match the actual formula. If the code uses a 105 mph threshold, the caption says 105, not 98. A caption that lies about the math is worse than no caption.

Abbreviations: use the term the casual viewer understands, but stay consistent across a surface. "BBE" is fine where the card already uses "BBE 142"; spell out "batted balls" where it would otherwise be the user's first encounter with the jargon. The card's own vocabulary sets the bar.

Scale anchors travel with the number. A "100 = average" stat needs the "100 = avg" cue attached to it (in the caption on a card, in the column header on a table) — never floating in a corner, never hover-only (hover fails on mobile). A bare "386" with no anchor is unreadable.


4. Surface-Token System (colors)
Every surface color flows through a named token. Never hardcode a cream/off-white hex — use the token. This is a real hierarchy, not drift; do not collapse it.

Token
Value
Role
--lb-surface-page
#faf4e6
warm page background / base
--lb-surface-paper
#fff9ea
card / modal / feature surface (the '52 card cream)
--lb-surface-soft
#f0e9d4
recessed / deeper cream (portrait base, portability track)
--lb-surface-control
#fffdf8
UI/control white (form inputs, table shell, close buttons)
--lb-surface-badge
#fff6df
small badge surface
--lb-surface-error
#fff8f7
semantic error blush (NOT cream — keep as error state)


Mustard (--mustard-soft #f5e4a8) is its own family — not cream.

Accent colors (also tokenized): accent red #b03524 (nameplate, Park Portability red), frame red #8a2d20 (darker, structural). Park Portability scale: red #b03524 (no-doubter, all 30 parks) / mustard #d4a418 (mostly gone, 8-29) / green #315f3f (doubter, 1-7). Badge navy #0c2340.

When adding a surface, ask "which role is this?" and use that token — don't invent a new cream.


5. The 1952 Topps Card Aesthetic
The hitter card is a vintage scouting-card artifact, inspired (structurally, not literally) by the 1952 Topps design. Users won't consciously recognize the '52 reference, but the intentionality should be clear.

Core concept: the stats ARE the portrait. A '52 Topps is built around a painted player portrait; we have no player photo (and won't — see §7). So the LBI hero number and the Park Portability bar take the visual role the portrait plays: the bold, framed, defining centerpiece. This makes the card distinctly ours, not a photo-card knockoff.

Structure: "front-as-hero, back-as-data." The top of the card wears the full '52 treatment (bordered frame, block-caps nameplate in accent red, corner team badge, the LBI hero number, the Park Portability bar) — this is the screenshot-worthy "front." The lower sections (Key Stats, Contact Shape) are the stat-grid "back" of the card.

Elements:

Bordered card frame (the collectible-artifact edge, not a flat modal). Outer 3px frame, inner hairline.
Block-caps player nameplate in a defined box, accent red.
Script accent: Georgia italic (the facsimile-signature gesture).
Corner team badge: a square/circle badge in the team's colors (navy for NYY), with the team abbreviation — never a trademarked logo (§7). The badge overlaps the frame edge (applied-on-top, sticker/foil feel).
Display face: Archivo Black for names/headers; Georgia italic for script accents.

Stay classic, not costume. The '52 is the reference because its design language is structural and timeless. Don't drift into era-pastiche (e.g. the swooping '82 Topps stripes).


6. What NOT to Do
No auto-generated editorial takes on cards. "Why He's Here" was removed because a templated "why" is a take with no human behind it — fine for Judge, but for a marginal player it manufactures conviction we don't hold. The cards SHOW; they do not manufacture editorial conviction.
No over-explaining. If the number/visual already says it, don't narrate it. (See §2c.)
No defensive framing. (See §2b.)
No raw unreadable rates on display. Plus-scale them. (See §3.)
No floating/hover-only scale anchors. (See §3.)
No new cream hexes. Use a surface token. (See §4.)
No over-systematizing. Don't collapse legitimate distinct roles into one (the six surfaces are distinct; the Park Portability buckets are distinct). But also don't multiply tokens for things that are genuinely one role.


7. Hard Constraints (legal)
No MLB team logos or trademarked marks. MLB enforces against small sites. Use team colors (not trademarkable) and our own badge designs. A future "design our own 30-team emblem set" is the distinctive, ownable version of team identity.
No player photos. Rights/IP. (This is why "the stats are the portrait" — the constraint produced a better, more distinctive concept than a photo would have.)

The logo/photo constraints are doorways, not walls: they push toward an ownable visual identity (our own badges, stats-as-portrait) instead of a borrowed, takedown-prone, generic-looking one.


8. Surface-Appropriate Execution
The '52 back is the default. The front/hero treatment is reserved for showcase moments (the card hero — one per card). Everything else — data tables, stat grids, supporting sections, any surface where the right treatment isn't obvious — defaults to the '52 back: bordered grid, vintage header band (accent red, block caps), flat two-tone cream/red/ink via surface tokens, readable-first. When in doubt, style it like the back of the card.

The same principle can be expressed differently on different surfaces — consistent intent, surface-appropriate execution.

Cards (showcase, casual audience, room to breathe): full treatment. Near-floor sample flag shown as text. Captions present.
Leaderboard table (dense, analytical audience, scanning): restraint. Same near-floor flag shown as muted styling + a legend, not column-widening text. Scale anchors in column headers.
Restraint scales; chrome doesn't. A dense table can't wear heavy card-chrome and stay readable. Apply the language with a light hand on dense surfaces.

When a stat appears on multiple surfaces, it should read as the same stat (same name, same scale grammar) even if the execution differs.


9. The Working Method (how design changes get made)
One surface / one change per branch. Never bundle unrelated changes. Side-fixes get their own scoped branch — a "quick fix while in the middle of other things" is how branches get contaminated.
Eyeball-review is the gate. Design is judged by eye, not by the build passing. Render the surface (desktop AND mobile) and look at it before committing. Mobile especially — a lot of scanning/screenshot traffic is mobile.
Tokens/definitions first, then apply. Define the language once (this guide, the surface tokens), then reference it — don't recompute design decisions per surface.
Display changes are source-only (no data regeneration). Data/field changes need the data pipeline (regenerate → build → commit data → push). Don't confuse the two.



This guide evolves with the site. When a new design decision is made and it's the kind of thing that should govern future work, add it here — so the language stays explicit and shared, not scattered across chat history and memory.
