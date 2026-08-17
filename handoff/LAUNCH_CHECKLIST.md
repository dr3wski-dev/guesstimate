# StatMap — Go-Live Checklist

Where the project actually stands, what blocks launch, and an honest answer to
"is the backend the problem." Companion to USER_EXPERIENCE_REVIEW.md (which lists
defects) — this one lists *decisions and work remaining*.

---

## Where we are

**Live at https://statmap.app.** Cloudflare Pages serves the game, a Worker serves
the questions, and both redeploy from `main` on push.

| | |
|---|---|
| Questions | **104** (NBA 44 / NFL 37 / MLB 23) — 20 days before a repeat |
| Every number re-derived from raw datasets | 744 values, **0 mismatches** |
| Fairness gate | passing, and enforced by the build |
| Test suites | **4** — behaviour, polish, restore codes, security (31 checks) |
| Third-party requests | **zero** |
| Cold load | 60 ms to first paint, 93 KB, no long tasks |
| Puzzle numbering | starts at #1 on 2026-08-17, rolls at midnight ET |

---

## What is actually left

### L1. Analytics — the game is live and unmeasured
> **Status: instrumented, not installed.** Seven events exist and no-op until a
> provider is set at build time.

Top item, because "live and measuring nothing" is the worst state to sit in. There is
currently no way to answer the question that decides everything else early: do people
finish all five?

- **Cloudflare Web Analytics** — one dashboard toggle, free, but **pageviews only**
- **Umami Cloud** — free to 100k events/mo, gives the funnel. Sign up, copy the
  website ID, rebuild with `--analytics umami --analytics-domain <id>`, commit

### L2. Content runs out on day 21
104 questions at five a day means the first repeat lands three weeks from launch.
**118 screened candidates** are ready — they clear the fairness gate and introduce no
duplicate charts — but each still needs fact copy written from its own plotted
numbers, and each has to clear `verify_questions.py`.

Not urgent this week. Genuinely urgent inside three.

### L3. MLB is thin at 23
Against NBA 44 and NFL 37. The career-stat archetypes draw on a smaller eligible
pool. Fine to leave, but it is why MLB questions will start feeling repetitive first.

---

## Shipped before launch

| | item | status |
|---|---|---|
| ~~S1~~ | ~~Results recap~~ | **Done.** Each round listed — tier, player, score — expanding to your guess, the actual, and the fact. |
| ~~S2~~ | ~~How-it-works screen~~ | **Done.** A `?` in the topline and a link on the start screen open the same dialog. Its score bands are generated from `TIERS`, so the explanation cannot drift from the scoring. |
| ~~S3~~ | ~~Keyboard nudge scaling~~ | **Done.** ~1/100 of the axis, Shift for a tenth. Worst case fell from 16,000 presses to 100. |
| ~~S4~~ | ~~Content hygiene~~ | **Done, and then superseded.** Axis quality is now a build gate rather than a judgement call — see below. |
| S5 | Content past 104 | Ongoing — see L2 above. 118 candidates screened and waiting. |

---

## The thing that was actually wrong, and is now gated

Worth recording, because it was invisible to every check that existed.

Score is distance normalised by the **plotted axis**, and the axis was chosen by
`nice_domain()` for tick aesthetics. So difficulty was a side effect of where the
edges landed. Ten of 68 questions were handing out free points, and on two of them a
blind click at the centre of the chart **scored better than knowing the answer** —
75 versus 70 on the worst one.

Every stat in those questions was correct, which is why nothing caught it:
`import_questions.py` checks shape, `verify_questions.py` checks truth, and a
question can pass both while being a bad question.

`audit_fairness.mjs` measures two things per question — what a blind centre click
scores, and how much an informed guess beats it — and `build_site.py` refuses to
build when either fails. Worst centre-click went from 75 to 35; worst lift from −5
to 30.

Five questions could not be fixed by any readable axis. They are quarantined in
`data/quarantine.json` with the measurement and the reason rather than deleted — the
data is fine, the framing isn't, and a better framing could reuse them.

---

## "Is the backend the problem?"

No. It was, and it isn't now — the Worker closed the two real holes:

- **Future answers.** The client used to fetch the whole pool, so every future day's
  answers were one dev-tools panel away. Only the selected day is sent now.
- **Device clock.** "Today" came from the browser, so setting the clock back replayed
  old puzzles and inflated streaks. The date is decided server-side.

### 1. Percentile / rarity — the one genuinely good reason to build more
"You beat 64% of players today" needs a server that sees everyone's scores. It is the
most requested feature in every daily game of this shape, and it is a real reason to
build a backend — **later**. The number is meaningless until there are players. When
it earns its place, Supabase is the right size: one table of (puzzle number, score),
no PII, no auth needed for the percentile itself.

### 2. Server-authoritative time
**Done.** The Worker decides the date.

### 3. Accounts and cross-device streaks
**Solved without accounts.** The stats modal exports and accepts an `SM1-…` restore
code — checksummed so a truncated paste is rejected, merged rather than overwritten,
and unable to buy streak credit because the one-completion-per-day rule still applies
to the restored `lastPlayed`. That covers the actual user need with no login, no
password reset, no email deliverability, and no GDPR surface.

---

## Known and accepted

**Today's five answers are readable in the network tab.** Scoring and the reveal
happen client-side, so the day's questions travel with their answers attached. Nobody
can read *tomorrow's*, and nobody can move their clock to farm a streak. Hiding
today's too would mean posting every guess to the server for scoring — a real backend
with real abuse surface, and a slower game. For a game with no prizes, cheating only
costs the cheater.

**MLB is the thinnest league at 23.** The generator's career-stat archetypes reuse
reference players more than the season-stat ones do. Reference selection is now
jittered and penalises reuse, which fixed the duplicate-chart collapse, but MLB's
eligible career pool is genuinely smaller.

---

## Suggested order

1. **Analytics** — live and unmeasured is the worst state to sit in
2. **Content past 104**, from the 118 screened candidates, before day 21
3. **Percentile backend**, once there is traffic to aggregate
