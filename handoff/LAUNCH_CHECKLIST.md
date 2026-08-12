# Guesstimate — Go-Live Checklist

Where the project actually stands, what blocks launch, and an honest answer to
"is the backend the problem." Companion to USER_EXPERIENCE_REVIEW.md (which lists
defects) — this one lists *decisions and work remaining*.

---

## Where we are

**The game is done.** The mechanic, scoring, daily rotation, challenge links, streaks,
stats, share artifact, dark mode, phone layout, restore codes, analytics events and
the results recap all work, covered by three browser suites (`reference/verify.mjs`
plus the restore and polish suites). Every functional defect found in the playtest
review is fixed.

**What is not done is everything around the game.** There is now a deployable build
(`site/`, see DEPLOY.md) and a content pipeline that generates and independently
verifies questions — but nothing is live, the pool is 22 questions where it wants to be
50-100, and there is still no analytics. None of those are code problems.

---

## Launch blockers

### B1. It isn't deployed — nobody can play it
> **Status: unblocked, not done.** `pipeline/build_site.py` now produces a deployable
> `site/` with root-relative paths, absolute OG URLs, and CSP/caching headers, and the
> full regression suite passes against it served from a web root. What remains is
> buying a domain, rebuilding with it, and pointing a host at the folder — see
> DEPLOY.md.

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
> **Status: 46 questions, first repeat on day 10.** A dataset pipeline generates and
> independently verifies candidates across all three leagues (`pipeline/`), so the
> remaining work to 100 is curation time rather than research time. 46 clears the
> "minimum I'd launch on" bar below; 100 is still the target.

Measured: the pool exhausts on day 2, and every question reappears roughly every other
day — 7 times in 14 days. A daily game whose content repeats before the first week is
out cannot form a habit, and everything else on this list compounds off retention that
won't exist.

| pool size | days before the first repeat |
|---|---|
| 10 (before the pipeline) | 2 |
| **46 (today)** | **9** |
| 25 | 5 |
| 50 | 10 |
| **100** | **20** |
| 150 | 30 |

**50 is the minimum I'd launch on. 100 is the real target.** This is the single largest
piece of work remaining and it is content, not engineering. See "Research pass" below.

### B3. No analytics — you'd launch blind
> **Status: code done, needs an account.** Seven events are instrumented and a
> provider installs via a build flag (`--analytics plausible|cloudflare`), which also
> extends the CSP for just that provider. All that's left is signing up and passing
> the domain or token. See DEPLOY.md.

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
| ~~S1~~ | ~~**Results recap**~~ | **Done.** The results screen now lists each round — tier, player, score — collapsed, expanding to your guess, the actual, and the fact. | — |
| S2 | **How-it-works screen** | Still open, and now the main remaining comprehension gap. The reveal heat map and its key explain the bands, but only after the first guess. | 2h |
| ~~S3~~ | ~~**Keyboard nudge scaling**~~ | **Done.** Nudge is now ~1/100 of the axis (never below one snap step), Shift for a tenth. Worst case fell from 16,000 presses to 100. | — |
| S4 | **Content hygiene** | Abbreviated NFL names and the `.254` batting-average format are both fixed. Still open: Nowitzki's `[60, 92]` domain spends a quarter of the axis on Muggsy Bogues — needs a replacement reference, which is hand-authored NBA career data with no dataset behind it. | 30m |
| S5 | **Content to 100** | 46 today (first repeat day 10). Pipeline covers all three leagues; this is curation time now. | ongoing |

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

**Done.** The stats modal exports and accepts a `GT1-…` restore code — checksummed so
a truncated paste is rejected, merged rather than overwritten on import, and unable to
buy extra streak credit because the one-completion-per-day rule still applies to the
restored `lastPlayed`.

---

## Research pass — status

**Hand research is blocked in this environment. The pipeline routes around it without
breaking the sourcing rule — 12 questions shipped this way, taking the pool from 10 to
22.**

Every stats source is blocked by the network egress proxy: Basketball-Reference,
Pro-Football-Reference, Baseball-Reference, StatMuse, Wikipedia, NBA.com, ESPN, MLB.com,
CBS Sports, RealGM, landofbasketball, and the BallDontLie API all fail outright. Web
*search* works, but returns rounded prose — a search for Pippen's career line came back
"2 steals and 1 block per game" when the question needs 2.0 and 0.8. That is not a
verification channel.

Per the project's own rule — *no fabricated or estimated data, ever; every number has a
named source* — writing questions from recall and attaching a citation I never opened
would be exactly the failure mode that rule exists to prevent. So none of the content
below came from recall.

**There is one channel that works: `raw.githubusercontent.com` is reachable** (confirmed
against arbitrary public repos). Open, citable sports datasets are published there and
in GitHub releases — the Chadwick Bureau / Lahman baseball databank, `nflverse` play-by-play
and player-stats releases, and various NBA career-stat CSVs. That is a legitimate,
license-clean, *verifiable* source: the data is a file I can actually read, check for
internal consistency, and cite by repo, commit, and column.

**This is what was built.** `pipeline/build_questions.py` generates candidates and
`pipeline/verify_questions.py` re-derives every shipped number from the raw CSVs on a
separate code path. Both are validated against the eight hand-verified values that were
already in `questions.json`, and they reproduce them exactly. The original proposal
follows, and still describes the approach:

**Build the content pipeline on open datasets rather than hand-research.** Pull the canonical per-league datasets, derive candidate stat pairs
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

1. **B1 deploy** — buy the domain, rebuild with it, point a host at `site/` (DEPLOY.md)
2. **B3 analytics** — an hour, do it in the same pass
3. **Restore code** — an hour, the only unrecoverable player data
4. **B2 content to 50+** — the long pole; the pipeline makes this curation time now,
   not research time. Run it in parallel with 1-3
5. **S1-S4 polish** — while content builds
6. *Launch*
7. Percentile backend, once there's traffic to aggregate
8. Server time, in the same pass as percentile
