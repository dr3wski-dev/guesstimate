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
   Challenge links now exist in the reference implementation and were built with this
   pattern; read this before touching them or adding any other URL-driven feature.
3. **USER_EXPERIENCE_REVIEW.md** — a playtest-driven review of the current reference
   implementation, written by actually driving it in a browser on phone and desktop
   rather than reading it. Contains five reproducible functional defects (the challenge
   link has no path back to today's puzzle, the streak clock and puzzle clock disagree
   for four hours a day, the mobile reveal renders below the fold, practice mode serves
   tomorrow's exact puzzle, two of the five score tiers are unreachable) plus a
   prioritized fix order. Read this before starting new feature work.
4. **DEPLOY.md** — the runbook for getting this on a real URL: what the build step
   produces and why, the pre-flight checklist (the OG tags bake the domain in, so
   rebuilding with the final URL is not optional), and how to ship new content.
5. **LAUNCH_CHECKLIST.md** — where the project stands against going live: the three
   launch blockers (not deployed, thin content, no analytics), the polish
   worth doing first, and a straight answer on whether this needs a backend. Also
   records the current sourcing constraint for new content.
6. **CONTENT_BACKLOG.md** — comp archetypes for the next research pass (efficiency vs.
   volume, defensive identity, stat-stuffer, and others across NBA/NFL/MLB), all
   unresearched, with a process for turning an archetype into a verified question.
7. **data/questions.json** — 46 verified, sourced questions (19 NBA, 15 NFL, 12 MLB) in
   the exact schema new content should follow. That is nine days before a repeat; see
   USER_EXPERIENCE_REVIEW.md §1.3 for why growing this is the top-line launch metric,
   and **pipeline/** for the generator and the independent verifier that produce and
   check new ones.
8. **reference/guesstimate-scatter.html** — the working, tested reference
   implementation. Click-to-plot 2D mechanic, heat-map proximity scoring, multi-round
   loop. This is what the production build should extend, not replace. `verify.mjs`
   beside it is a 24-check browser regression suite — run it after any change.
9. **reference/guesstimate-slider-legacy.html** — an earlier, now-superseded 1D version
   of the mechanic. Kept only because it contains two pieces of tested logic not yet
   ported into the scatter version: the daily-selection pure function
   (`selectDailyQuestions`) and the streak/localStorage system. Port these, don't
   rebuild them — they're already correct.

## What's explicitly NOT in scope
Stated plainly because this project went through several pivots to reach its current
form, and it would be easy for old context to leak back in:
- No anonymized/caption-guessing chart mechanic
- No survey, geography, or "random fun facts" categories — sports stats only
- No fabricated or estimated data, ever — every number in questions.json has a named
  source; every future addition needs the same
- No live sports data API for v1 — see ACTION_PLAN.md section 1 for the reasoning
- No accounts or backend for v1 — localStorage only, no PII

## The one instruction to give Claude Code before anything else
*"Read README.md, then ACTION_PLAN.md in full, before writing any code. Treat
guesstimate-scatter.html as the reference implementation to extend, not a prototype to
throw away. Do not fabricate or estimate stats — if data is needed beyond what's in
questions.json, flag it as a research task rather than filling it in."*
