# StatMap — Handoff Package
Start here. This is the complete, current context for the project — everything else in
this folder is referenced from this file in the order it should be read.

## What this is, in one sentence
A daily sports-stats guessing game: real reference players are plotted on a 2D chart
(two related stats at once), and the player clicks where they think a named player
falls, scored by proximity.

## One pool, several games
There is one question pool and several games served from it. A game is a named slice
of that pool with its own daily rotation, its own epoch, its own pinned calendar, its
own URL and its own streak — so "StatMap NBA #1" can be somebody's first ever puzzle
on a day hard mode is on #50.

| game | URL | what it asks | state |
|------|-----|--------------|-------|
| `main` | `/` | every league, every kind of stat — one season, career totals, height, All-Star counts | live, 600 questions |
| `nba` | `/nba/` | career per-game averages | live, 192 questions |
| `mlb` | `/mlb/` | career rate lines, hitters and pitchers | live, 336 questions |
| `nfl` | `/nfl/` | career per-touch rates | **not open** — see the note in `data/games.json` |
| `nhl`, `cfb`, `psu` | — | career rates | **not open** — no source that can be re-derived |

`data/games.json` is the manifest, and the `note` on a game that is not open says
exactly what is blocking it rather than "coming soon". Those notes are the honest part:
there is no open NHL career dataset we can check our arithmetic against, the reachable
college data starts at 2014 and is play-by-play, and the NFL data's three coverage
faults stack up on a career in a way they do not on a single season.

**A question belongs to a game by a `game` field**, and the 600 that predate the split
carry no field at all, meaning hard mode. That is not laziness: adding one would have
changed the pool, and the pool is what the shuffled bag is a function of, so every day
in the calendar would have been re-dealt. For the same reason hard mode's bag seed is
still the bare `bag-cycle-N` string with no game id in it. Played days are immutable.

**To add a game:** add it to `data/games.json` with `status: "soon"`, add its archetypes
and a loader to `pipeline/build_questions.py`, add its label table and an independent
re-derivation to `pipeline/verify_questions.py`, generate and screen and merge
candidates, create `data/schedule-<id>.json` and import it in `worker/src/index.js`,
deal its calendar with `schedule_days.mjs --game <id> --days N`, then flip it to
`"live"`. `pipeline/check_games.mjs` fails the build if any of those are missing, which
is the point — every one of them can be forgotten on its own and the result is a page
that loads, answers, and serves nothing.

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
7. **data/questions.json** — 1,128 verified, sourced questions across all the games
   in the exact schema new content should follow.
   Every number re-derives from the raw datasets on a separate code path; see
   **pipeline/** below. `data/quarantine.json` holds questions withdrawn for being bad
   *questions* rather than wrong ones, each with the measurement that condemned it.
8. **reference/statmap.html** — the working, tested reference
   implementation, and the single source of truth for the game. Click-to-plot 2D
   mechanic, heat-map proximity scoring, multi-round loop. The production build is
   generated from it; never hand-edit `site/`. Six browser suites sit beside it —
   `verify.mjs` (behaviour), `polish.mjs`, `restore.mjs`, `security.mjs` (31 checks),
   `orientation.mjs` and `games.mjs` (each game is its own game). `cd handoff && npm
   run serve` then `npm test` runs all six against the real Worker under the real CSP.
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
   `audit_fairness.mjs` gates question quality, `merge_candidates.py` is the
   append-only door into the pool, `check_games.mjs` holds the games manifest to the
   pool and the schedules, and `build_site.py` assembles one page per live game and
   refuses to build if the fairness or games gate fails. `devserver.mjs` serves the built
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
