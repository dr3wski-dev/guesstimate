# Guesstimate — Handoff Package
Start here. This is the complete, current context for the project — everything else in
this folder is referenced from this file in the order it should be read.

## What this is, in one sentence
A daily sports-stats guessing game: real reference players are plotted on a 2D chart
(two related stats at once), and the player clicks where they think a named player
falls, scored by proximity.

## Read in this order
1. **ACTION_PLAN.md** — scope, data-source strategy, the daily-rotation architecture,
   security posture, real costs, and a phased roadmap with trigger conditions. This is
   the actual current source of truth for every product and technical decision made so
   far. Section 0 is explicit about scope: this is the *only* game — no anonymized
   chart guessing, no multi-category content, that entire direction was scrapped.
2. **SECURITY_NOTES.md** — a real vulnerability that was found and fixed (reflected XSS
   in a challenge-link feature), the fix pattern, and the general security posture.
   Read this before adding challenge links to the current reference implementation —
   they don't exist there yet, and need to be built with this pattern from day one.
3. **CONTENT_BACKLOG.md** — comp archetypes for the next research pass (efficiency vs.
   volume, defensive identity, stat-stuffer, and others across NBA/NFL/MLB), all
   unresearched, with a process for turning an archetype into a verified question.
4. **data/questions.json** — 16 fully verified, sourced questions (7 NBA, 5 NFL,
   4 MLB) in the exact schema new content should follow. This is the canonical
   content source and the only one; the Worker bundles it at build time, which
   means adding questions requires redeploying the Worker, not just pushing.
5. **DEPLOY.md** — how the two deployed pieces (Pages site + questions Worker)
   fit together, what still needs a human with a browser, and precisely which
   part of the "client sees everything" problem the Worker does and does not
   solve. Read before deploying or before touching the CSP.
6. **site/** — the deployed site, and the *only* directory Cloudflare Pages
   publishes. `site/index.html` is the game: click-to-plot 2D mechanic,
   exponential-decay scoring, the daily loop, streaks, challenge links, stats.
   Nothing else belongs in here — see DEPLOY.md for why that boundary matters.
7. **reference/guesstimate-slider-legacy.html** — an earlier, now-superseded 1D
   version of the mechanic. Historical only now: the two pieces of tested logic it
   was being kept for have both been ported. The streak/localStorage system is in
   the scatter build, and the daily-selection function has moved past it entirely —
   it lives in `worker/src/selection.js` and runs server-side.
8. **worker/** — the questions API. `src/selection.js` is the daily-rotation logic
   (the only copy that exists); `src/index.js` is the Worker that serves a single
   day's questions and refuses to serve any other.

## What's explicitly NOT in scope
Stated plainly because this project went through several pivots to reach its current
form, and it would be easy for old context to leak back in:
- No anonymized/caption-guessing chart mechanic
- No survey, geography, or "random fun facts" categories — sports stats only
- No fabricated or estimated data, ever — every number in questions.json has a named
  source; every future addition needs the same
- No live sports data API for v1 — see ACTION_PLAN.md section 1 for the reasoning
- No accounts or database for v1 — localStorage only, no PII. There is now one
  stateless Cloudflare Worker (`worker/`) that picks today's questions server-side;
  it stores nothing and knows nothing about who is playing. See DEPLOY.md.

## The one instruction to give Claude Code before anything else
*"Read README.md, then ACTION_PLAN.md in full, before writing any code. Treat
site/index.html as the reference implementation to extend, not a prototype to
throw away. Do not fabricate or estimate stats — if data is needed beyond what's in
questions.json, flag it as a research task rather than filling it in."*
