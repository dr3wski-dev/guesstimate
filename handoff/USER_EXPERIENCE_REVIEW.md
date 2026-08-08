# Guesstimate — User-Perspective Review

Written by playing the game, not by reading it. Every claim below was reproduced against
`reference/guesstimate-scatter.html` + `data/questions.json` at commit `0f143dc`, driven
through a headless browser on an iPhone 13 viewport and a 1280×900 desktop viewport.
Measured numbers are quoted as measured.

Companion to `COMPETITIVE_ANALYSIS.md` — that doc asked "where does this sit in the
genre." This one asks "what happens to a real person who opens the link." Most of the
COMPETITIVE_ANALYSIS backlog shipped in `0f143dc` and is *not* re-litigated here.

---

## The one-paragraph version

The game itself is good. The 2D estimation mechanic works, the drag interaction is
smooth, the reveal animation lands, the legend turned guessing into reasoning, and the
`fact` payload is genuinely the best thing in the daily-game genre. The problems are all
*around* the mechanic: a new player can't reach today's puzzle if they arrived from a
friend's link, the content runs out in two days, the score doesn't tell them whether
they did well, and on a phone the payoff for playing is rendered below the fold. Five of
the findings below are functional defects with reproductions, not opinions.

---

## Tier 0 — Nobody can play it yet

### 0.1 There is no playable URL, and the file doesn't work standalone
The game lives at `handoff/reference/guesstimate-scatter.html` and fetches
`../data/questions.json` at runtime. Opened directly from disk:

```
panel shows: Couldn't load today's questions (Failed to fetch). Try refreshing the page.
console:     Fetch API cannot load file:///…/data/questions.json.
             URL scheme "file" is not supported.
```

So the file cannot be emailed, AirDropped, or double-clicked — it only runs behind a web
server. Combined with `og:image`/`og:url` still being relative paths (flagged in a
`NOTE FOR DEPLOY` comment at line 17 and still unresolved), the two things standing
between this and its first real player are both deploy tasks, not code tasks.

**Do:** deploy to a static host, make the OG URLs absolute, regenerate the card. This is
the last unticked item on ACTION_PLAN §5 — *"played end-to-end by people who aren't you
or me"* — and everything else in this document is downstream of it.

---

## Tier 1 — Defects that break the core loop

### 1.1 A challenge link is a one-way door — the acquisition funnel terminates at the entrance
**This is the most serious finding in the document.** The stated distribution model is
"someone pastes a link into a group chat." Here is what happens to the person who clicks it.

Reproduced with `?challenge=1&from=Drew&score=380&d=2026-08-05` on 2026-08-07:

```
MODE = challenge   today = 2026-08-07   challenge date = 2026-08-05
serving : williams, nowitzki, green, jordan, winston
today is: pippen, jordan, nowitzki, green, taylor          same? false

[play 5 rounds] -> "Challenge round — doesn't affect your streak"
[click "Back to today"]

after: MODE = challenge
  now serving: williams, nowitzki, green, jordan, winston   <- the challenge puzzle again
  today is   : pippen, jordan, nowitzki, green, taylor
  topline: GUESSTIMATE #217 · CHALLENGE
  banner : 🎯 Drew scored 380 on puzzle #217 …
```

The cause is at `init()`: `DAILY_ROUNDS = roundsForDate(MODE === 'challenge' ? CHALLENGE.date : TODAY)`.
In challenge mode `DAILY_ROUNDS` *is* the challenge day, so `backToToday()` — which sets
`ROUNDS = DAILY_ROUNDS` and recomputes `MODE` from the still-present `CHALLENGE` object —
returns you to exactly where you were.

There is no path to today's puzzle from a challenge link short of hand-editing the query
string. So the flow for every user acquired through the game's only growth channel is:
play a stale puzzle → be told it doesn't count → press the button that promises today's
→ get the stale puzzle again. They never start a streak. They never see today's content.

**Do:** `backToToday()` should clear the challenge state and the query string
(`history.replaceState`), recompute `DAILY_ROUNDS` for `TODAY`, and drop the banner.
Also worth offering "Play today's puzzle →" on the challenge *start* screen, before they
commit to five rounds of someone else's day.

### 1.2 The streak clock and the puzzle clock are different clocks
The puzzle day comes from `todayDateString()` → `America/New_York`. The streak day comes
from `registerCompletion()` → `todayISO()` → `new Date().toISOString()` → **UTC**. They
disagree for four hours every single day, 8pm–midnight ET, which is prime time for a
casual daily game.

```
2026-08-10T14:00:00Z  puzzle = 2026-08-10   streak records = 2026-08-10
2026-08-10T23:30:00Z  puzzle = 2026-08-10   streak records = 2026-08-10
2026-08-11T01:00:00Z  puzzle = 2026-08-10   streak records = 2026-08-11   <-- MISMATCH
2026-08-11T03:59:00Z  puzzle = 2026-08-10   streak records = 2026-08-11   <-- MISMATCH
```

Simulated consequence for a player with a mixed schedule:

```
Mon 9pm ET  (plays Mon's puzzle):  recorded as 2026-08-11 -> streak 1, daysPlayed 1
Tue 10am ET (plays Tue's puzzle):  SILENTLY IGNORED (already recorded 2026-08-11)
                                   -> streak stays 1, day not counted, points not counted
Wed 10am ET (plays Wed's puzzle):  recorded as 2026-08-12 -> streak 2, daysPlayed 2
```

The player finished a full puzzle and the app recorded nothing — no streak credit, no
`daysPlayed`, no points toward their average — and said nothing about it. Streaks are
*the* retention mechanic in this genre; a streak that silently eats days is worse than no
streak, because the player blames the app and is right to.

**Do:** use `todayDateString()` everywhere in the stats layer, and derive "yesterday" in
the same timezone rather than by subtracting 86,400,000 from `Date.now()`.

### 1.3 The content runs out in two days
10 questions, 5 a day. Measured rotation over the first 14 days:

```
#1: jordan, taylor, abreu, winston, boldin
#2: williams, randolph, green, pippen, nowitzki     <- pool exhausted
#3: taylor, randolph, abreu, green, pippen          <- everything is a repeat from here
…
repeat gaps: every question is served 7 times in 14 days
```

`selectDailyBag` does its job — no repeat *within* a cycle — but a cycle is two days long.
By day three every question a player sees is one they have already answered, with the
answer already revealed and the fact already read. The daily habit cannot form.

This is the single biggest gap between Guesstimate and everything in the competitive
table, and it is a content problem, not an engineering one. ACTION_PLAN §5 sets the v1
bar at 15–20 questions; that is 3–4 days of non-repeating play. `CONTENT_BACKLOG.md`
already has the archetypes — the pipeline just needs to run.

**Do:** treat pool size as the top-line launch metric. **100 questions = 20 days**
before the first repeat, which is roughly the point where a daily habit is established.
150+ gets a full month. Nothing else on this list matters if a player has no reason to
come back on Wednesday.

### 1.4 Practice mode is a perfect spoiler for tomorrow
`startPractice()` draws from "everything that isn't in today's set" — and the code comment
says *"so it can't be used to preview the daily puzzle."* With a 10-question pool and 5 a
day, "everything that isn't in today's set" is **exactly tomorrow's set**:

```
practice draws from: williams, winston, randolph, boldin, abreu
tomorrow serves    : randolph, winston, boldin, williams, abreu
-> overlap 5/5
```

Partly a symptom of 1.3, but the exclusion rule is wrong independently: it should exclude
the *next* day's bag as well as today's, and hide the Practice button entirely when the
remaining pool is too small to be meaningfully separate.

---

## Tier 2 — The score doesn't tell you how you did

### 2.1 Two of the five tiers are unreachable and one absorbs everything
`scoreGuess2D` feeds a normalized 2D distance into `0.5^(err/25)`. Working the curve
backwards against `scoreTier`'s thresholds:

| miss (% of chart) | points | tier |
|---|---|---|
| 0% | 100 | 🟢 Perfect |
| 3% | 92 | 🟢 Great |
| 5% | 87 | 🟡 Ballpark |
| 25% | 50 | 🟡 Ballpark |
| 30% | 44 | 🔴 Off |
| 100% | 6 | 🔴 Off |
| 141% (max possible) | **2** | 🔴 Off |

- **⚫ "Way off" is mathematically unreachable.** It needs 0 points; the largest possible
  normalized distance is √2 ≈ 141%, which still scores 2. The tier can never fire — it
  appears in the stats modal permanently reading 0.
- **🟢 "Perfect" needs a sub-pixel hit** on most questions. One arrow-key/snap step is
  worth 0.02px on `nfl-pb-recyds-boldin`'s Y axis and ~2px on `nba-mpg-ppg-williams`, but
  30px on `nba-as-ppg-randolph`'s X. It's unreachable on fine questions and routine on
  coarse ones.
- **🔴 "Off" spans 1–49**, which is where 80% of uniformly-random clicks land.

Net: a nominal 5-tier system is really 2.5 tiers, and the two extremes that would make
the shareable strip *expressive* are the ones that never fire.

### 2.2 …which makes the growth artifact look like a failure report
A full honest playthrough (clicking the middle of the reference cloud each round —
roughly what a casual player who doesn't know the answer does) produced:

```
Guesstimate #219
🔴🔴🔴🔴🟡  214/500
```

That is not an artifact anyone forwards to a group chat. Wordle's grid works because a
normal result *looks* like a result. This looks like a bad day. The emoji strip is the
growth engine — it needs to be tuned so that a competent-but-imperfect round reads green
and yellow with the occasional red, not the reverse.

**Do:** rebase the tier cutoffs on the actual score distribution rather than round
numbers. Something like Perfect ≥95 / Great ≥80 / Ballpark ≥55 / Off ≥30 / Way off <30
puts every tier in reach and makes the strip informative. Also give Perfect and Great
different emoji — they're both 🟢 today, so the strip carries less information than the
tiers do.

### 2.3 The denominator lies about the floor
A uniformly random click averages **37.5 points**, so a monkey scores **~188/500**.
Displaying `214/500` implies the scale starts at zero and that the player got 43%. In
reality 188 is chance and 500 is perfection, so the meaningful range is 188–500 and the
player scored about 8% of it. Every score looks better than it is, and the gap between a
good and a bad player looks smaller than it is.

**Do:** either shift the curve so chance ≈ 0, or report a normalized figure alongside the
raw one. This matters most for challenge links — "beat their 380" is only a real
challenge if the numbers are calibrated.

### 2.4 Difficulty isn't comparable across questions or across days
Guess granularity ranges over three orders of magnitude between questions (0.02px/step to
30px/step), so identical skill produces very different scores depending on which questions
the bag deals. That undercuts the daily score, the streak, the challenge comparison, and
the average in the stats modal — all four assume days are comparable.

---

## Tier 3 — The phone experience, where this game will actually be played

Measured on iPhone 13, 390×664 CSS px.

### 3.1 After you submit, the payoff is off-screen
```
reveal block after submit:  top 670, bottom 1162     viewport height 664
```

The reveal starts **six pixels past the bottom of the screen** and the page does not
scroll to it. The player taps "Submit guess", the button relabels to "Next question →",
a green dot appears on the chart — and the points, the tier, the miss narration, and the
`fact` are all invisible. The `fact` is, per COMPETITIVE_ANALYSIS, the actual product.
On a phone, the default experience is that you never see it.

**Do:** `revealArea.scrollIntoView({ block: 'nearest', behavior: 'smooth' })` on submit,
or move the reveal above the button so the score lands where the eye already is.

### 3.2 Submit is below the fold before you submit, too
```
submit button: top 649, bottom 700     viewport 664
```
You place a guess and the button to commit it is off-screen.

### 3.3 The stats and theme buttons sit on top of the round counter
```
#topRight ("1 / 5"):  x 327-371, y 33-49
.controls:            x 290-374, y 16-54     -> OVERLAP
```
`.controls` is `position:fixed; top:16px; right:16px` and the topline is inside the
620px app column; on a narrow viewport they occupy the same space. "1 / 5" — the only
progress-in-words indicator — renders underneath two opaque circular buttons.

### 3.4 You can't scroll by swiping on the chart
`.chart-frame { touch-action: none }` is correct for drag-to-plot but means the largest
element on the screen (225px tall, roughly a third of the viewport) eats vertical swipes.
Combined with 3.1 and 3.2, a player who wants to reach the score has to find the narrow
margins beside the chart to scroll. Consider `touch-action: pan-y` plus
`preventDefault()` only once a horizontal-ish drag is detected, or an explicit
scroll-affordance after submit.

### 3.5 The header eats the vertical budget
The Fraunces prompt wraps to three lines and the mono instruction to another three,
pushing the chart down to y=296 — 45% of the viewport spent before the game begins.
Shortening the instruction to a single line after the first round (the coach ring already
does the teaching) buys back roughly 60px.

---

## Tier 4 — Trust and comprehension

### 4.1 A dead streak is displayed as a live one
With `lastPlayed` set seven months in the past:

```
start screen: 🔥 7-day streak · best: 12
stats modal : DAYS PLAYED 20 | AVG 300 | STREAK 7 | BEST STREAK 12
```

The streak is only recomputed inside `registerCompletion()`, so a lapsed player is shown
a streak they no longer have, right up until they finish a round and watch it silently
snap to 1. Players notice this and read it as the app being broken — worse, it removes the
loss-aversion pressure that makes streaks work at all.

**Do:** compute the displayed streak from `lastPlayed` at read time — if it isn't today
or yesterday, show 0 (and consider "your 7-day streak ended — start a new one" as the
copy, which is the emotionally correct prompt).

### 4.2 Nothing anywhere explains how scoring works
Searched the rendered DOM: no "how to play", no rules text, no statement that each
question is out of 100. A first-time player sees `+38` with no scale, no idea whether
"Ballpark" is good, and no idea that 500 is the ceiling until the results screen.
Given every player arrives cold from a text message, a one-screen "how it works" behind
an `?` button (the two icon buttons are already there) is cheap and standard for the genre.

### 4.3 "Play again" replays the round you just finished, answers known
Flagged in COMPETITIVE_ANALYSIS §4.6 and still present. It promises new content and
delivers a replay with every answer revealed. Either point it at Practice or remove it
until the pool supports it.

### 4.4 The results screen throws away everything you learned
Five pills — `+38 +41 +30 +46 +59` — with no question names, no answers, no facts. The
one thing that differentiates this game from Immaculate Grid is discarded the moment you
press Next. A compact recap (question → your guess → actual → one-line fact) would make
the results screen worth reading, and give the "huh, I didn't know that" reaction
somewhere to land.

---

## Tier 5 — Accessibility

### 5.1 The reveal is never announced
`#readout` is `aria-live="polite"`, so a screen-reader user hears their guess update
while placing it. `#revealArea` has **no** live region, so on submit they hear nothing:
no score, no tier, no actual value, no fact. Live guessing is accessible; the payoff is not.

### 5.2 Keyboard play is impossible on several questions
Arrow keys nudge exactly one guess-step. Presses required to cross the chart:

```
nfl-pb-recyds-boldin   X:    16   Y: 16000
mlb-as-hr-abreu        X:    16   Y:   600
nfl-ypg-tds-taylor     X:   600   Y:    16
nba-mpg-ppg-williams   X:   240   Y:   200
```

The keyboard path is advertised in the instruction text on every round and is unusable on
the majority of the pool.

**Do:** scale the nudge to the domain — roughly 1/100 of the range per press, snapped to
the step — with Shift for a coarse jump and/or a modifier for single-step precision.

---

## Tier 6 — Content and code hygiene

### 6.1 `fact` and `source` are the only unescaped innerHTML sinks
Lines 936–937 interpolate `${r.fact}` and `${r.source}` raw; every other interpolation in
the file goes through `escapeHtml()`. `questions.json` is first-party so this is not
currently exploitable — but SECURITY_NOTES' entire thesis is *"sanitize at the boundary,
not case-by-case at each usage site, because that's what let the bug exist."* This is the
usage site that got missed, in a file that is fetched over the network at runtime.

### 6.2 Reference-player naming is inconsistent with its own rule
`shortLabel()`'s comment argues for full names because surnames collide (the pool has both
Michael Jordan and DeAndre Jordan). But `nfl-ypg-tds-taylor` uses `McCaffrey ’23`,
`Henry ’20`, `Peterson ’12` while every other question uses full names, and the season
suffix is the exact pattern `shortLabel()` strips from target players.

### 6.3 Outlier references compress the interesting region
`nba-height-3p-nowitzki` spans `[60, 92]` inches to accommodate Muggsy Bogues at 63".
The band where the question is actually decided (78–86") is a quarter of the axis. A
reference set with a tighter spread makes the guess more discriminating.

---

## Recommended order

1. **Deploy it** (0.1) — everything is theoretical until someone can open a URL.
2. **Fix the challenge one-way door** (1.1) — it breaks the only acquisition path, and
   it's a handful of lines.
3. **Fix the streak clock** (1.2) — silent data loss in the retention mechanic.
4. **Fix the mobile reveal** (3.1–3.3) — the payoff is currently invisible on the
   dominant device.
5. **Recalibrate scoring and tiers** (2.1–2.3) — makes the shareable artifact worth
   sharing.
6. **Grow the pool to 100+** (1.3) — the largest amount of work and the thing that
   determines whether any of the above compounds. Start now, in parallel.
7. Streak honesty (4.1), how-it-works screen (4.2), results recap (4.4), keyboard
   scaling (5.2), reveal live region (5.1).
8. Content hygiene (6.1–6.3) as the pipeline runs.

Items 2–5 are, collectively, about a day of work and remove every functional defect
found. Item 6 is the actual product roadmap.
