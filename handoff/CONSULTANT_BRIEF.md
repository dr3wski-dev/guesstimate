# StatMap — Consultant Brief

Written 2026-09-02. Everything you need to be useful on this project, and the things
that will bite you if nobody tells you.

The other eight documents in this folder are still accurate on *architecture and
reasoning*, but several were written before features shipped and describe defects that
are now fixed. This file is the current state. Where it disagrees with an older doc,
this one is right; where it is silent, the older docs are the detail.

---

## 1. What it is

A daily sports-stats guessing game, live at **https://statmap.app**.

Five questions a day, the same five for everybody, resetting at midnight Eastern. Each
question shows a 2D scatter chart with three or four real players plotted on two
related stats — say career strikeouts against career batting average. You are named a
fourth player and you click where you think they fall on **both** axes at once. Score
is proximity.

Owner: Drew Tanous. One-person project.

**Scope is deliberately narrow.** No anonymized chart guessing, no multi-category
content, no other game modes. That direction was considered and scrapped. See
`ACTION_PLAN.md` §0.

---

## 2. The numbers, right now

| | |
|---|---|
| Questions in the pool | **565** |
| Distinct chart types | **57** |
| League split | NBA 216 · MLB 198 · NFL 151 |
| Calendar pinned through | **2026-12-14** (120 days from launch) |
| Days of content left | ~104 |
| Launch day (puzzle #1) | 2026-08-17 |
| Runtime dependencies | **zero** |
| Total pipeline + worker code | ~6,300 lines |
| The game itself | one 2,464-line HTML file |

---

## 3. Architecture, in one page

Three pieces. That is the whole system.

**The game** — `handoff/reference/statmap.html`. A single file. Vanilla JS, hand-built
SVG, no framework, no build step for the JS itself, no runtime dependencies at all. This
is the source of truth for anything the player sees.

**The site** — `site/`. Static files on Cloudflare Pages. **Generated** from the
reference file by `pipeline/build_site.py`. Never hand-edit `site/` — it is rebuilt
wholesale and your edit will vanish silently. CI fails if the committed `site/` does not
match a fresh build, which is how that rule is enforced rather than remembered.

**The API** — `handoff/worker/`. A Cloudflare Worker at `/api/*` serving today's five
questions. Stateless: no KV, no D1, no Durable Objects, no secrets, no bindings. It is a
pure function of (date, bundled pool). That property is what makes it free and
un-abusable; if you find yourself adding a binding, read `ACTION_PLAN.md` §3 first.

Two things about the Worker that are easy to get wrong:

- **The question pool is bundled INTO the Worker at build time.** New questions reach
  players when the *Worker* deploys, not when Pages rebuilds. A green Pages deploy with
  a stale Worker is the failure this project is most exposed to, because nothing about
  it looks broken.
- **It must be routed on the same domain as the page.** The page's CSP is
  `connect-src 'self'`, so an API on a `*.workers.dev` host would be blocked by the
  browser. Both `statmap.app` and `www.statmap.app` are routed — see §7.

---

## 4. The rules that are not negotiable

These are each here because breaking one caused a real incident.

**No fabricated or estimated data, ever.** Every number in `questions.json` has a named
source. Anything new needs the same. If you need a stat you do not have, that is a
research task, not a gap to fill in.

**Never hand-edit `site/`.** See above.

**A question that has ever been SERVED can never be deleted.** Challenge links point at
a specific past day and must keep reproducing what the sender played. `schedule_days.mjs
--check` fails with an explicit message if you remove one, because "not in the pool"
alone reads like a typo rather than like history being rewritten.

**Played days are immutable; future days are plans.** Today and everything before it is
frozen. Everything after is re-dealt on each content run. The write step refuses outright
if a played day would change.

**`pipeline/build_demo.py` output must never be published.** It carries the entire pool.
So does `content/schedule-master.csv`. Both are fine locally, and both are every answer
for the whole calendar.

---

## 5. Working on it

```bash
cd handoff
npm install
node pipeline/devserver.mjs 8903        # serves the game + a local /api/daily
BASE=http://localhost:8903/ npm test    # all four browser suites
```

The gates, in the order CI runs them:

```bash
python3 pipeline/import_questions.py --check   # JSON schema / shape
node pipeline/schedule_days.mjs --check        # calendar soundness + variety warnings
node pipeline/audit_fairness.mjs               # does each question reward knowing?
python3 pipeline/build_site.py --url https://statmap.app \
  --analytics umami --analytics-domain <id>    # then: git diff --quiet -- site/
BASE=http://localhost:8903/ npm test           # verify, polish, restore, security, orientation
```

Those analytics flags are **not optional** — build without them and the committed
`site/` no longer matches what CI builds, and the "committed build is up to date" gate
fails. `DEPLOY.md` has the canonical command.

**The one gate CI cannot run** is `pipeline/verify_questions.py`. It re-derives every
shipped number from the raw datasets, which are ~43 MB and gitignored. It is the most
important check in the project and it only runs locally. Run it whenever content
changes.

### Two separate gates, and why

`import_questions.py` checks **shape** — is this well-formed JSON with the right fields.
`verify_questions.py` checks **truth** — recomputing each value from the source data.
They are deliberately independent, and the reason is a real failure: an NFL "targets"
column echoed receptions in 99-100% of rows for 2003-2008. Four wrong values shipped,
and the verifier passed them, because it read the same broken column. **Two readings of
one broken source agreeing is not verification.** `verify_questions.py` now has a
season-gating table that fails a question plotting a value from a window where the
column carries no measurement.

---

## 6. Deploying

`main` is the deploy branch. Merging to it runs `.github/workflows/checks.yml`, which
runs every gate and then — only if they pass — deploys the Worker.

That ordering is the point. Cloudflare's own Workers Builds triggers on push and never
consults the workflow, so deploying from CI is what makes the gates load-bearing rather
than advisory.

The deploy job's last step asks the live API for its `x-build` header and compares it to
a fingerprint of this checkout. That step is the one that catches a deploy which
reported success and released nothing.

`wrangler` needs `-c handoff/worker/wrangler.toml`. Without it, wrangler resolves config
from the repo root, finds nothing, and reports a missing entry point. The dashboard's
"Root directory" field looks like the fix and does nothing for this step.

---

## 7. Failures worth knowing about

The pattern across every serious incident here is the same: **something reported success
while doing nothing.** Weight your suspicion accordingly.

- **www served the page and 404'd the API for days.** The Worker was routed on the apex
  only. Every check asked `https://statmap.app`, so every check was honestly green while
  the hostname carrying most of the traffic gave nobody a question. The canary now
  iterates both hostnames. *A monitor that knows one of your hostnames is monitoring one
  of your hostnames.*
- **Umami collected nothing.** The CSP allowed the script host but not the send host.
  The tag loaded fine; the dashboard was empty; indistinguishable from having no
  visitors. Note the page has **two** CSPs — `_headers` and a `<meta>` tag — and
  browsers enforce the intersection. Widen both or neither.
- **Adding questions re-dealt every past day.** The bag was a pure function of (date,
  pool), so growing the pool changed history — measured 0/5 overlap on days 1-3. Fixed
  by pinning every day explicitly in `data/schedule.json`.
- **The chart shapes clumped.** The league rotation was constraining leagues and nothing
  was watching the chart types, so the same chart went out four days in five and pitching
  went 16 days with two questions. Fixed with a 5-day cooldown keyed on axis labels.
- **A laptop layout gap.** The two-column layout required `min-height:620px` and the
  compressed landscape layout stopped at `max-height:560px`; 561-619 belonged to neither
  and fell back to phone stacking. That band is 1920x1080 at 150% Windows scaling, which
  reads to the user as "100% zoom" because their browser zoom *is* 100%.

---

## 8. Where the bodies are

Things that are true, that nobody has fixed, and that you should know before proposing
work.

**The pool is deep but narrow.** 565 questions across only 57 chart types. Repetition is
governed by the *chart* count, not the question count — a daily player meets each chart
about 2.9 times a month, and 19 charts appear 4+ times in any 30-day window. Adding more
players to the same charts changes the names and not the experience. The fix is new
archetypes (new pairings of columns already downloaded — no new data acquisition), and
it is deferred by the owner's decision, not oversight.

**147 MLB players in `athlete_pool.csv` have an empty `Tier`.** They were admitted on
objective bars — 8 All-Star selections, 400 home runs, 250 wins — which measure a career
honestly and say nothing about whether anyone has heard of the man. 64% of MLB answers
are untiered against 6% of NBA. The scheduler currently caps unvetted names at 2 per
puzzle, which fixes *concentration* but barely moves the overall share (34% → 30%).
Tiering them properly is open content work. Note that untiered does **not** mean obscure
— Ichiro, Cal Ripken and Rich Gossage are in that bucket too, which is why it is a cap
and not a cut-list.

**`<span id="topRight">` ships with a hardcoded `···`.** It is a status slot showing
placeholder text until the first render replaces it with `1 / 5`. It is inert, it sits
inside a cluster of round buttons where it reads as a "more options" affordance, and it
is visible on every cold load. A reviewer did in fact mistake it for a menu. Not fixed.

**Icon nav is unlabelled on touch.** `?` and `▤` carry `aria-label` and `title`, so
screen readers and desktop hover are fine, but there is no hover on a phone and `▤` for
"your stats" is not guessable. A one-time coach-mark was designed and deferred.

**Analytics have never been read.** Umami is installed and collecting. Nobody has looked.
Several open product decisions — percentiles in particular — are waiting on data that is
sitting there.

**There is no production smoke test.** CI checks the build; the canary checks the live
API hourly. Nothing drives a real browser against the live site on both hostnames, which
is the exact class of bug www represented.

---

## 9. Reading order for the rest

1. `ACTION_PLAN.md` — the real source of truth for product and technical decisions.
   Scope, data strategy, rotation architecture, security posture, costs, roadmap.
2. `SECURITY_NOTES.md` — a reflected XSS found and fixed in challenge links, and the fix
   pattern. Read before touching anything URL-driven.
3. `DEPLOY.md` — the runbook. Canonical build command lives here.
4. `USER_EXPERIENCE_REVIEW.md` — a playtest review. **Dated**: several defects it lists
   are fixed. Useful for the method and the reasoning, not as a current bug list.
5. `COMPETITIVE_ANALYSIS.md` — positioning, and the axis-leak bug in §2 is worth reading
   as a class of mistake.
6. `CONTENT_BACKLOG.md`, `LAUNCH_CHECKLIST.md` — both partly historical now.

---

## 10. Scoring and fairness, briefly

`points = 100 * exp(-(d/0.30)^1.6)`, where distance is normalised **per axis in chart
space**. Because it is per-axis and in chart space, the pixel aspect ratio is free to
change — which is why the phone can use a taller viewBox without altering anybody's
score.

Every question must pass two gates: a blind middle-click must score **≤35** (`centre`),
and knowing the answer must be worth **≥30** more than that (`lift`). This caught two
shipped questions that paid better for a blind guess than for knowledge, and neither
looked wrong in review. Do not add a question type without running
`audit_fairness.mjs`; near-collinear axis pairs (attempts vs. makes) fail it, correctly.
