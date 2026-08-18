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
| Questions | **204** (NBA 84 / NFL 72 / MLB 48) — ~40 days before a repeat |
| Chart types | **48**, up from 17 |
| Every number re-derived from raw datasets | 1,552 values, **0 mismatches** |
| Fairness gate | passing, and enforced by the build |
| Test suites | **5** — behaviour, polish, restore codes, security (31 checks), orientation |
| CI | green, and now builds with the same flags we deploy with |
| Third-party requests | Umami only |
| Cold load | 60 ms to first paint, 93 KB, no long tasks |
| Puzzle numbering | starts at #1 on 2026-08-17, rolls at midnight ET |

---

## What is actually left

### L1. The Worker build is failing on Cloudflare
> **Status: blocking. Nothing else on this list matters until it clears.**

Pages is green and the Worker is red, which is the worst possible split: the site
looks updated while the API keeps serving the old pool. The Worker is what sends the
questions, so until it deploys, none of the 100 new ones exist as far as a player is
concerned.

It is not the code. `wrangler deploy --dry-run` builds clean at 183 KiB (25 KiB
gzipped, against a 1 MiB limit), and the build fails instantly on Cloudflare's side
rather than after a compile — which points at build configuration, most likely the
project's root directory, since `wrangler.toml` lives at `handoff/worker/` and not at
the repository root. Read the build log before acting on that guess.

### L2. Analytics are installed and unread
Umami has been collecting since 2026-08-17. The seven events are live. Nobody has
looked at them yet, and they answer the question that decides most of what follows:
**do people finish all five?**

- Completion rate (start → round 5) is the number that matters
- Round-by-round drop-off says whether five is the right number
- Share-button rate says whether the game spreads on its own

### L3. The written fact is switched off
Two attempts at the copy failed — the first restated the plotted numbers, the second
invented reasons for them. `SHOW_FACT` is false and the strings are retained in
`questions.json`. The reveal is 335 characters, of which 139 is the source citation.

Reinstating it needs a register that survives being read twice. That is an editorial
session, not a generation job.

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

**Every answer is public, and that is fine.** Scoring and the reveal happen
client-side, so the day's questions travel with their answers attached. The repo is
public, so questions.json and schedule.json together spell out which questions land
on which date. An earlier version of this note claimed tomorrow's were safe. That was
never true — the pool was public and the selection deterministic, so any day was
always computable; the calendar only made it easier to read. Nobody can move their
clock to farm a streak, which is the part that matters. Hiding
today's too would mean posting every guess to the server for scoring — a real backend
with real abuse surface, and a slower game. For a game with no prizes, cheating only
costs the cheater.

**MLB is still the thinnest league, at 48 against NBA 84 and NFL 72.** The eligible
career pool is genuinely smaller, and career questions cannot carry a season label the
way "Derrick Henry, 2020" can. Adding pitching archetypes — ERA, strikeouts, saves,
complete games — is where the next MLB depth comes from, and it needs a Pitching.csv
the pipeline does not currently download.

**Career questions show no year on their dots.** Season questions do. That asymmetry
is correct — a career has no one year — but it means MLB charts carry less context
than NBA and NFL ones.

---

## Suggested order

1. **Unblock the Worker build.** Everything below is invisible to players until the
   API redeploys.
2. **Read the analytics.** Completion rate decides whether the next work is content,
   difficulty, or retention.
3. **Percentile / rarity backend**, once there is traffic to aggregate. Still the one
   feature with a genuine reason to add a server.
4. **The fact copy**, as an editorial session rather than a generation job.
5. **A fourth sport or a difficulty split** — both are content-pipeline projects, and
   both should wait for the completion numbers before either gets built.
