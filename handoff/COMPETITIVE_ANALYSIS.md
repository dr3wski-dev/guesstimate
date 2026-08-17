# StatMap — Competitive Analysis & Enhancement Backlog

Written against the actual state of the game (now `site/index.html`) and
`data/questions.json` (10 questions), not against the plan. Companion to
ACTION_PLAN.md — that doc covers scope/architecture/cost; this one covers
*where this game sits against the daily-game genre* and what to build to
close the gaps.

---

## 1. Where StatMap sits in the landscape

The daily sports-game space is crowded but structurally uniform. Nearly every
successful entry is a **discrete identification game**: guess the name, fill the
square, pick from a set.

| Game | Core mechanic | Its retention hook |
|---|---|---|
| Wordle | 6 guesses, letter feedback | Spoiler-free emoji grid + puzzle number |
| Immaculate Grid | Fill 9 team×team squares | **Rarity score** — how uncommon your answer was |
| Poeltl | Guess the mystery NBA player | Color-coded attribute feedback columns |
| Weddle / HoopGrids | NFL/NBA variants of the above | Same, per-league |
| MLB/NBA Pickle | Daily trivia, several modes | Multiple modes = longer sessions |
| GeoGuessr | Drop a pin on a map | Distance line + animated score bar |

**StatMap's actual differentiation:** it is the only one doing *continuous
2D spatial estimation*. You're not identifying a player, you're estimating a
position — which means partial credit, which means every single player gets a
different score on the same question. That's genuinely novel in this space and
it's the moat.

The closest structural cousin isn't a sports game at all — it's **GeoGuessr**.
Same shape: place a marker, reveal the truth, draw a line between them, score by
proximity. Worth stealing from deliberately.

**The corresponding weakness, stated plainly:** identification games are *easy to
talk about*. "I got Bobby Abreu on the Angels/300-HR square" is a story you can
tell in a group chat. "I clicked slightly above and left of Draymond Green" is
not. Estimation games are harder to make social, and right now StatMap does
almost nothing to compensate for that. Most of the recommendations below are
about making outcomes **legible and tellable**.

**The thing this game has that none of the others do:** the `fact` payload on
every reveal. Wordle teaches you nothing. Immaculate Grid teaches you nothing.
StatMap ends every round with "huh, I didn't know that." That is the real
product and it's currently buried below the fold in a 13.5px paragraph.

---

## 2. Fix first: the axis bounds leak the answer

**This is a correctness bug, not a feature request, and it should be fixed
before the game is shown to anyone who might care enough to reverse-engineer it.**

`showQuestion()` computes the plot bounds from *all* points including the hidden
answer:

```js
const allX = [r.targetX, ...r.referencePlayers.map(p=>p.x)];
const xMin = Math.min(...allX)*0.7, xMax = Math.max(...allX)*1.15;
const yMin = Math.min(...allY)*0.5, yMax = Math.max(...allY)*1.2;
```

So whenever the target is the extreme value on an axis — which is *the entire
premise of the content*, since a "sneaky stud" question is by construction a
player at an extreme — the axis is a pure function of the answer. The leftmost
printed tick label is literally `targetX * 0.7`.

Verified against the current pool: **8 of 10 questions leak at least one axis;
2 leak both.**

```
nba-mpg-ppg-williams   leftmost tick 16.9  ÷ 0.7  = 24.14   (actual 24.1)
nba-ppg-stuff-green    leftmost tick  6.1  ÷ 0.7  =  8.71   (actual  8.7)
nba-fga-ts-jordan     rightmost tick 26.3  ÷ 1.15 = 22.87   (actual 22.9)
nfl-int-td-winston    rightmost tick  4.0  ÷ 1.15 =  3.48   (actual  3.5)
mlb-as-hr-abreu         bottom tick  144   ÷ 0.5  = 288.00  (actual 288)
nfl-pb-recyds-boldin    bottom tick 6890   ÷ 0.5  = 13780   (actual 13779)
```

For one-decimal rate stats it's exact. For integer-step stats the tick display
rounds and blurs it, but only slightly.

And you don't even need the arithmetic. The visual tell is free: when the target
is the axis minimum, there is a conspicuous empty band between the left edge of
the plot and the leftmost reference dot — and the only thing that can be in that
band is the answer. A player notices that pattern in about three days without
trying. Daily-game communities reverse-engineer this stuff *fast*.

**Fix:** derive the domain from the reference players only, plus a fixed margin,
and clamp so the target is guaranteed inside without influencing the bounds.
Better still, add optional explicit `xDomain`/`yDomain` to the question schema
for hand-tuned questions — same pattern as the `xStep`/`yStep` fix, where the
per-question override solved the general case. Then re-verify every existing
question still frames sensibly.

---

## 3. The share loop is the growth engine, and it's the weakest part

The entire distribution model is "paste a link into iMessage." Three concrete
gaps, all cheap:

### 3.1 The share text is a number, not an artifact
Currently: `StatMap — I scored 350/500. Think you can beat me? <url>`

Wordle's emoji grid is not decoration — it *is* the growth engine. It's
spoiler-free, instantly parseable, visually distinctive in a message thread, and
it invites a reply. A bare number invites nothing.

StatMap already computes everything needed. `scoreTier()` already returns an
emoji per round, and `daysSince(TODAY, BAG_EPOCH)` already yields a puzzle
number. This is nearly free:

```
StatMap #218
🟢🟡🟢🔴🟢  412/500
statmap.app
```

The puzzle number matters more than it looks — it's what makes the artifact feel
like a shared event rather than a personal score, and it creates the "wait, I
haven't done today's" reflex.

### 3.2 A challenge link doesn't challenge you on the same puzzle
`CHALLENGE` carries only `from` and `score`. `ROUNDS` is always computed from
*today*. So if you play Friday and your friend opens the link Saturday, the
banner says "Drew scored 350 — think you can beat them?" while serving an
entirely different set of five questions. The comparison is incoherent.

**Fix:** put the date in the challenge URL and, when present, serve that day's
puzzle as a challenge round that doesn't touch the streak.

### 3.3 The link preview is a prototype title and no image
`<title>StatMap — Scatter Prototype</title>`, no `og:*` tags, no favicon, no
meta description. iMessage renders a rich card from Open Graph tags — for a game
distributed by pasted links, **that card is the landing page**, and right now it
says "Scatter Prototype" with a blank thumbnail.

Cheapest high-leverage fix on this entire list: real title, `og:title` /
`og:description` / `og:image` (a static 1200×630), `twitter:card`, favicon.

---

## 4. Feature add-ons, ranked

1. **Emoji-strip share + puzzle number** (§3.1). Highest leverage per hour, uses
   machinery that already exists.
2. **OG tags / title / favicon** (§3.3). An hour of work; it's the first
   impression for every user who ever arrives.
3. **Date-anchored challenge links** (§3.2). Finishes a feature that's currently
   half-built.
4. **Reference-player value legend under the chart.** Right now you see a dot and
   a name and have to eyeball its coordinates against gridlines. A short list —
   `Kobe Bryant · 36.1 MPG · 25.0 PPG` — turns the guess from eyeballing into
   *reasoning*, which is the difference between a toy and a game. Note the
   reference circles deliberately have `pointer-events:none` so they don't eat
   drag events, so a static legend beats a hover tooltip — and hover doesn't
   exist on touch anyway.
5. **Stats modal.** Wordle and Immaculate Grid both have one. Played, average
   score, tier distribution ("you're a 🟢 62% player"), current/best streak.
   Pure `localStorage` aggregate, no backend.
6. **Archive / practice mode. BUILT, THEN REMOVED — read this before rebuilding
   it.** A practice mode drawing from outside today's set shipped and was pulled
   back out. The reason is the pool size: at 16 questions the rotation cycles in
   3.2 days, so "questions outside today's set" is mostly *tomorrow's* set, and
   an unlimited mode both spoils the daily puzzle and competes with the habit
   loop the whole game is built on. The feature isn't wrong, the pool is too
   small for it. It becomes the main session-length lever at 100+ questions,
   which is where the content push is aimed — rebuild it then, server-side, and
   note the endpoint that did exactly this is in the git history.
7. **First-run worked example.** Every new user arrives cold from a text message
   with no idea what they're looking at. A one-time ghost animation showing a pin
   being dragged, or a throwaway tutorial round, is standard in this genre and
   directly attacks bounce rate.
8. **Rarity / percentile** — the Immaculate Grid killer feature — is the one
   genuinely great idea here that needs a backend. Correctly gated to v2 in
   ACTION_PLAN.md. Don't pull it forward.

---

## 5. UX/UI enhancements, ranked

1. **Kill the stale copy.** The note under every screen still reads *"All five
   data points (four references + LeBron's real career line) are verified NBA
   career averages."* The LeBron questions were removed and most questions aren't
   NBA. It's wrong on every single round. Same for `GUESSTIMATE — SCATTER` and
   "Scatter Prototype" in the topline and title — internal naming leaking to
   players.
2. **Label collision handling** (known gap, still `const above = i%2===0`).
   Low-risk at 10 sparse questions; it will start producing overlapping text the
   moment two reference players cluster, which is common in tightly-scaled stats.
3. **Steal GeoGuessr's reveal.** The target-drop animation is in and good. What's
   missing is the score *counting up* and the distance being narrated — GeoGuessr
   says "you were 412 km away" and that framing is most of the emotional payload.
   The connector line is already drawn; label it with the actual miss ("2.3 PPG
   high, 1.1 RPG low").
4. **Promote the `fact`.** It's the best thing in the product and it's rendered at
   13.5px in `--ink-soft` below a fold. Give it real typographic weight — it's the
   reason anyone comes back.
5. **Visual identity per question.** Every chart looks identical: same paper, same
   axes, same three hollow dots. Immaculate Grid gets enormous visual variety free
   from team logos. StatMap has a league tag and nothing else. Even
   league-tinted accents (NBA / NFL / MLB) would make the five daily rounds feel
   like five different things instead of one thing five times.
6. **Self-host the fonts.** Three Google Fonts families are render-blocking
   third-party requests, in a project whose stated posture is "no dependencies,
   minimal attack surface." Self-hosting the woff2s kills the swap flash, removes
   an external dependency, and lets the CSP drop its `googleapis`/`gstatic`
   allowances entirely.

---

## 6. Explicitly not now

- Accounts, leaderboards, live data API — correctly gated in ACTION_PLAN.md §6
  behind real usage. Nothing here changes that.
- More leagues before the axis bug (§2) is fixed. Every new question written
  against the current bounds logic inherits the leak.
