# Guesstimate — Go-Live Checklist

Where the project actually stands, what blocks launch, and an honest answer to
"is the backend the problem." Companion to USER_EXPERIENCE_REVIEW.md (which lists
defects) — this one lists *decisions and work remaining*.

---

## Where we are

**The game is done, and so is everything around it except the hosting account.**

| | |
|---|---|
| Questions | **104** (NBA 44 / NFL 37 / MLB 23) — 20 days before a repeat |
| Every number re-derived from raw datasets | 744 values, **0 mismatches** |
| Fairness gate | passing — every question rewards knowing the answer |
| Test suites | **4** — behaviour, polish, restore codes, security (31 checks) |
| Third-party requests | **zero** |
| Cold load | 56 ms to first paint, 93 KB, no long tasks |

What remains is a domain and two Cloudflare projects. See **DEPLOY.md** for the
reference, or the hosting runbook for click-by-click.

---

## Launch blockers

### B1. It isn't deployed
> **Status: everything on this side is done; needs an account.**
> `pipeline/build_site.py` produces a deployable `site/`, committed to the repo, with
> absolute OG URLs and CSP/caching headers. All four suites pass against it served
> from a web root, under the real CSP, with the real Worker answering `/api/*`.

Remaining, all of it yours:

- Merge the working branch into `main` — **Cloudflare deploys from `main`**
- Buy a domain (~$10-12/yr, the only unavoidable cost)
- Cloudflare Pages, output directory `site`, no build command
- Cloudflare Workers, root directory `handoff/worker`, **connected to the repo**
  rather than deployed by hand — the questions are bundled *into* the Worker, so a
  forgotten manual deploy ships a site whose questions never changed, silently
- Rebuild with the real URL **and commit it** — Pages serves `site/` as committed,
  so a local-only rebuild changes nothing anyone can see

### B2. Content depth
> **Status: cleared for launch, still growing.** 104 questions is 20 days. The bar
> below was 50; the target was 100.

A further **118 screened candidates** are ready — they pass the fairness gate and
introduce no duplicate charts. They are not questions yet: each needs fact copy
written from its own plotted numbers, and each has to clear `verify_questions.py`.
That is the long pole, and it is no longer blocking anything.

### B3. No analytics — you'd launch blind
> **Status: code done, needs an account.** Seven events are instrumented
> (`round_start`, `question_submit`, `round_complete`, `share_click`,
> `challenge_open`, `restore_export`, `restore_import`) and no-op until a provider is
> installed. The provider is a build flag, so no vendor snippet is ever pasted into
> the game, and the build extends the CSP for exactly that provider.

Run two: Cloudflare Web Analytics (free, unlimited, dashboard toggle) for traffic,
and Umami (free to 100k events/mo) for the funnel. Cloudflare's free tier is
pageviews only — it cannot tell you whether people finish all five, which is the
number that decides what to build next.

---

## Worth doing before launch

| | item | status |
|---|---|---|
| ~~S1~~ | ~~Results recap~~ | **Done.** Each round listed — tier, player, score — expanding to your guess, the actual, and the fact. |
| ~~S2~~ | ~~How-it-works screen~~ | **Done.** A `?` in the topline and a link on the start screen open the same dialog. Its score bands are generated from `TIERS`, so the explanation cannot drift from the scoring. |
| ~~S3~~ | ~~Keyboard nudge scaling~~ | **Done.** ~1/100 of the axis, Shift for a tenth. Worst case fell from 16,000 presses to 100. |
| ~~S4~~ | ~~Content hygiene~~ | **Done, and then superseded.** Axis quality is now a build gate rather than a judgement call — see below. |
| S5 | Content past 104 | Ongoing, not blocking. 118 candidates screened and waiting. |

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
**Solved without accounts.** The stats modal exports and accepts a `GT1-…` restore
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

1. **Merge to `main`** — nothing else works until this is done
2. **Buy the domain**
3. **Pages + Workers**, rebuild with the real URL, commit, verify the pool 404s
4. **Analytics** — same session, while the dashboard is open
5. *Launch*
6. **Content past 104**, from the 118 screened candidates
7. **Percentile backend**, once there is traffic to aggregate
