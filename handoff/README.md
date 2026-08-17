# StatMap — Handoff Package
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
7. **data/questions.json** — 104 verified, sourced questions (44 NBA, 37 NFL, 23 MLB)
   in the exact schema new content should follow. That is twenty days before a repeat.
   Every number re-derives from the raw datasets on a separate code path; see
   **pipeline/** below. `data/quarantine.json` holds questions withdrawn for being bad
   *questions* rather than wrong ones, each with the measurement that condemned it.
8. **reference/statmap.html** — the working, tested reference
   implementation, and the single source of truth for the game. Click-to-plot 2D
   mechanic, heat-map proximity scoring, multi-round loop. The production build is
   generated from it; never hand-edit `site/`. Four browser suites sit beside it —
   `verify.mjs` (behaviour), `polish.mjs`, `restore.mjs` and `security.mjs` (31
   checks). `cd handoff && npm run serve` then `npm test` runs all four against the
   real Worker under the real CSP.
9. **worker/** — the questions API, a single stateless Cloudflare Worker.
   `src/selection.js` holds the daily-rotation logic and `src/index.js` serves one
   day's questions and refuses any other. It exists because a client that holds the
   whole pool leaks every future day's answers to anyone who opens dev tools, and
   because "today" from the device clock is spoofable. It stores nothing and knows
   nothing about who is playing.
10. **pipeline/** — everything that turns raw open datasets into shipped questions.
   `build_questions.py` generates candidates, `screen_candidates.mjs` drops the ones
   that would not reward knowing the answer, `verify_questions.py` re-derives every
   shipped number from the raw CSVs on a deliberately separate code path,
   `audit_fairness.mjs` gates question quality, and `build_site.py` assembles `site/`
   and refuses to build if the fairness gate fails. `devserver.mjs` serves the built
   site plus the real Worker locally. See **content/README.md** for the workflow.


## What's explicitly NOT in scope
Stated plainly because this project went through several pivots to reach its current
form, and it would be easy for old context to leak back in:
- No anonymized/caption-guessing chart mechanic
- No survey, geography, or "random fun facts" categories — sports stats only
- No fabricated or estimated data, ever — every number in questions.json has a named
  source; every future addition needs the same
- No live sports data API for v1 — see ACTION_PLAN.md section 1 for the reasoning
- No accounts or database for v1 — localStorage only, no PII. There is one stateless
  Worker (`worker/`) that decides the date and serves a single day's questions; it
  stores nothing. See DEPLOY.md

## The one instruction to give Claude Code before anything else
*"Read README.md, then ACTION_PLAN.md in full, before writing any code. Treat
statmap.html as the reference implementation to extend, not a prototype to
throw away. Do not fabricate or estimate stats — if data is needed beyond what's in
questions.json, flag it as a research task rather than filling it in."*
