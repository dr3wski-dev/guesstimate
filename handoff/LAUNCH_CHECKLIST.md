# Guesstimate — Go-Live Checklist

Where the project actually stands, what blocks launch, and an honest answer to
"is the backend the problem." Companion to USER_EXPERIENCE_REVIEW.md (which lists
defects) — this one lists *decisions and work remaining*.

---

## Where we are

**The game is done.** The mechanic, scoring, daily rotation, challenge links, streaks,
stats, share artifact, dark mode, and phone layout all work and are covered by a
24-check browser suite (`reference/verify.mjs`). Every functional defect found in the
playtest review is fixed except the ones listed below.

**What is not done is everything around the game:** it isn't deployed, there are ten
questions, and there is no content pipeline. None of those are code problems.

---

## Launch blockers

### B1. It isn't deployed — nobody can play it
The game is a file in `handoff/reference/`. It fetches `../data/questions.json`, so it
doesn't even run from disk (`file://` → "Couldn't load today's questions"). Until this
is on a URL, every other item here is theoretical.

- Static host (Vercel / Netlify / Cloudflare Pages — all free at this scale)
- Domain (~$10-15/yr, the only unavoidable cost)
- `og:image` and `og:url` must become **absolute** URLs on the real domain. They're
  relative today and there's a `NOTE FOR DEPLOY` comment in the file saying so.
  Most crawlers — including iMessage's — will not resolve a relative `og:image`, and
  for a game distributed by pasted links **that card is the landing page**.
- Move `guesstimate-scatter.html` → `index.html` at the site root and fix the
  `../data/` path.

**Effort: an afternoon. Do this first.**

### B2. Ten questions is two days of content
Measured: the pool exhausts on day 2, and every question reappears roughly every other
day — 7 times in 14 days. A daily game whose content repeats before the first week is
out cannot form a habit, and everything else on this list compounds off retention that
won't exist.

| pool size | days before the first repeat |
|---|---|
| 10 (today) | 2 |
| 25 | 5 |
| 50 | 10 |
| **100** | **20** |
| 150 | 30 |

**50 is the minimum I'd launch on. 100 is the real target.** This is the single largest
piece of work remaining and it is content, not engineering. See "Research pass" below.

### B3. No analytics — you'd launch blind
There is no instrumentation of any kind. On day one you would not be able to answer:
did anyone play, did they finish all five, where did they drop off, did anyone share,
did any share link get opened. Those are exactly the questions that decide what to
build next.

This is not a backend — it's a script tag (Plausible/Fathom ~$9/mo, or Cloudflare Web
Analytics free) plus a handful of custom events: `round_start`, `question_submit`,
`round_complete`, `share_click`, `challenge_open`. **Effort: an hour.** I'd treat it as
launch-blocking.

---

## Worth doing before launch (cheap, high value)

| | item | why | effort |
|---|---|---|---|
| S1 | **Results recap** | Five pills, no question names, no answers, no facts. The `fact` is the only thing in this genre that teaches you anything, and it's discarded the second you hit Next. | half day |
| S2 | **How-it-works screen** | Nothing anywhere explains scoring. New players see "+38" with no scale. The reveal heat map helps, but only after they've already guessed. | 2h |
| S3 | **Keyboard nudge scaling** | Arrow keys move one guess-step, so crossing the Boldin chart takes 16,000 presses. The instruction text advertises the keyboard on every round. | 1h |
| S4 | **Content hygiene** | NFL question uses `McCaffrey '23` while everything else uses full names — and `shortLabel()`'s own comment argues for full names to disambiguate surnames. Nowitzki's `[60, 92]` domain spends a quarter of the axis on Muggsy Bogues. | 1h |

---

## "Is the backend the problem?"

**Short answer: there is no backend, that's deliberate, and it is still the right call
for v1.** ACTION_PLAN §1 and §6 argue this and the argument holds — the daily puzzle is
a pure function of the date, the stats are historical and don't change, and there are no
accounts. Nothing about the current design is waiting on a server.

What actually feels bad isn't the backend. It's B1 and B2: it isn't live, and there
isn't enough content. Building a backend now would not move either.

That said, three things a server would buy, ranked by value:

### 1. Percentile / rarity — the one genuinely great reason to build one
"You beat 68% of players today" is the Immaculate Grid killer feature, and it fixes a
real weakness this game has: estimation results are hard to talk about. "I clicked
slightly above Draymond" is not a story; "I was in the top 10% on question 3" is.

**And it's small.** No accounts, no auth, no PII: one endpoint that accepts
`{puzzleNo, questionId, score}`, one counter store, one endpoint that returns today's
distribution. A Cloudflare Worker + KV or Durable Object, comfortably inside the free
tier. Needs rate limiting (ACTION_PLAN §3 flags this correctly — the moment a real
endpoint exists, it becomes relevant) and the scores are unauthenticated so the
distribution is only as honest as the internet, which for a percentile display is fine.

**Verdict: highest-value server work, but it needs players first. Build it once B1/B2
are done and there's real traffic to aggregate.**

### 2. Server-authoritative time
Today's date comes from the player's device clock, which is spoofable — someone can set
their clock back to replay a puzzle or pad a streak. Right now the only victim is
themselves, since nobody else can see it. **The moment percentile or a leaderboard
ships, this stops being theoretical.** A few lines in an edge function. Defer until #1
exists, then do it in the same pass.

### 3. Accounts and cross-device streaks
This is where the cost actually lives (database + auth + a real security posture), and
it's correctly gated to v2 behind real usage.

### The genuinely fragile thing nobody's flagged
Streaks live in `localStorage` and nowhere else. **Clear your browser, switch phones, or
open the game in a different browser and your streak is gone with no recovery.** For a
game whose entire retention mechanic is a streak, that's a real fragility — and it's the
thing that will actually generate complaints, well before anyone cares about a
leaderboard.

Cheap mitigations that don't need a backend:
- An export/import "restore code" (base64 of the stats blob) in the stats modal
- Say so plainly in the UI, so losing it isn't a surprise
- Accept it for v1 and let #3 solve it properly later

**Recommendation: ship the restore code with launch. It's an hour and it's the only
data the player can't get back.**

---

## Research pass — status

**Blocked in this environment, and I won't fabricate around it.**

Every stats source is blocked by the network egress proxy: Basketball-Reference,
Pro-Football-Reference, Baseball-Reference, StatMuse, Wikipedia, NBA.com, ESPN, MLB.com,
CBS Sports, RealGM, landofbasketball, and the BallDontLie API all fail outright. Web
*search* works, but returns rounded prose — a search for Pippen's career line came back
"2 steals and 1 block per game" when the question needs 2.0 and 0.8. That is not a
verification channel.

Per the project's own rule — *no fabricated or estimated data, ever; every number has a
named source* — writing questions from recall and attaching a citation I never opened
would be exactly the failure mode that rule exists to prevent. So the pool is still 10.

**There is one channel that works: `raw.githubusercontent.com` is reachable** (confirmed
against arbitrary public repos). Open, citable sports datasets are published there and
in GitHub releases — the Chadwick Bureau / Lahman baseball databank, `nflverse` play-by-play
and player-stats releases, and various NBA career-stat CSVs. That is a legitimate,
license-clean, *verifiable* source: the data is a file I can actually read, check for
internal consistency, and cite by repo, commit, and column.

**Proposed next step: build the content pipeline on open datasets rather than
hand-research.** Pull the canonical per-league datasets, derive candidate stat pairs
against the archetypes in CONTENT_BACKLOG.md and the 527 names in `athlete_pool.csv`,
auto-filter for questions where the target is genuinely counterintuitive relative to its
reference set, and hand-write only the `fact` copy. That turns B2 from "a hundred manual
research sessions" into a repeatable job, and it's the only path I can see from 10
questions to 100 that doesn't break the sourcing rule.

Worth knowing before I start: this changes the sourcing story from "StatMuse, checked by
hand" to "open dataset, cited by commit." Stathead (ACTION_PLAN §1) stays the better
tool for a human doing hand-curation — its terms forbid wiring it into the app, but not
this. If you'd rather keep hand-verified StatMuse sourcing, that research has to happen
somewhere with network access to it, not here.

---

## Suggested order

1. **B1 deploy** — an afternoon, unblocks everything
2. **B3 analytics** — an hour, do it in the same pass
3. **Restore code** — an hour, the only unrecoverable player data
4. **B2 content to 50+** — the long pole; start the pipeline now, in parallel with 1-3
5. **S1-S4 polish** — while content builds
6. *Launch*
7. Percentile backend, once there's traffic to aggregate
8. Server time, in the same pass as percentile
