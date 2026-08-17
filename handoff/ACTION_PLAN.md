# StatMap — 0→1 Action Plan
For handoff to Claude Code. This is the current source of truth for scope, architecture,
security, and cost — supersedes prior planning docs (ROADMAP.md, CURRENT_SPEC.md) where
they conflict. Working reference implementation: site/index.html (formerly
reference/statmap.html).

## 0. What this project actually is, in one paragraph
A sports stats guessing game. Five questions a day, same for every player, no login
required. Each question shows real reference players plotted on a 2D chart (two related
stats at once — PPG vs RPG, rushing yards vs touchdowns, etc.) and the player clicks
where they think a named player falls. Score is based on how close the click is, using
an exponential decay curve. Streaks and challenge-links, no backend required for v1.

**Scope, stated plainly because this went through several pivots to get here:** this is
the *only* game. The anonymized-chart guessing concept (caption multiple-choice, themed
days across sports/survey/geography/random categories, the hot dog/AKC dog breed/
pineapple pizza content) is scrapped entirely, not a parallel product and not a fallback.
site/index.html is the sole reference implementation. Any doc or file describing
the anonymized-chart version (GUESS_THE_CHART_SPEC.md, CATEGORY_CLARITY_GUIDELINES.md,
guess-the-chart.html, the original data-drawer.html portfolio site and its starter kit)
is historical context only — nothing in them describes what's being built now. Don't
resurrect content or mechanics from them without an explicit decision to do so.

---

## 1. Data sources — the actual decision, not just options
**Recommendation: don't pay for a live sports data API yet.** Here's the reasoning,
not just the conclusion:

This game doesn't need live data. A question about Wilt Chamberlain's career average or
Derrick Henry's 2020 season doesn't change — those numbers are frozen in history. Even
an active player's career average only ticks up marginally after each game they play,
and even that can be handled with periodic (not real-time) re-verification. Paying
$40-160/month for a live-polling sports API (the realistic cost for a tier that
includes player stats, per the research below) buys capability this project doesn't use.

**What I checked:** BallDontLie's free tier doesn't include the `/stats` endpoint at all
— it requires the $9.99/mo tier at minimum, and full multi-sport access is $159.99/mo.
Highlightly and API-NBA both offer 100 requests/day free with no credit card, which is
more than enough for periodic content curation (you're looking up a handful of stats per
research session, not polling live games).

**The actual plan:**
- **Now:** keep doing what's worked this whole conversation — manual, verified research
  (this chat or Cowork), cross-checked against a named source, cited per question. Zero
  marginal cost, and the accuracy bar has been high throughout.
- **Worth adding: a Stathead subscription (the "All Sports" bundle — Baseball,
  Basketball, Football, Hockey, FBref/soccer — starting around $9/month) as the primary
  curation tool.** Checked their actual terms before recommending this: Stathead's
  terms of use explicitly prohibit reselling or redistributing their data, using it to
  "create a competing statistical database," or copying a "materially significant
  portion" of their data — and their bot-traffic policy caps even permitted automated
  access at 10-20 requests/minute, which signals plainly that this is built for human
  research sessions, not backend API access. **Don't scrape it or wire it into the app
  programmatically.** What it's genuinely excellent for, and explicitly fine under
  their terms ("we encourage the sharing and reuse of data and statistics our users
  find on our Site"), is exactly the curation workflow this project already runs on:
  a human (or Claude, working interactively) using Stathead's filterable queries to
  find good reference-player sets — "players with X rebounds and Y points, spanning
  this range" is a native Stathead query, not something to assemble from one search
  per player the way this session's NBA/NFL data was gathered. Faster curation, same
  citation discipline, same "verify before it goes in the pool" rule.
- **If research volume becomes the bottleneck beyond what Stathead speeds up:** add
  Highlightly or API-NBA's free tier for quick programmatic lookups during curation —
  still a human-in-the-loop research aid, not app infrastructure, same distinction as
  above.
- **Content strategy that reduces staleness for free:** prefer completed single-season
  stats (Jonathan Taylor's 2021 season will never change) and retired players' career
  numbers (Wilt Chamberlain's are frozen) over active players' current career averages,
  which drift every game. Not a hard rule — LeBron-style "generational, recognizable
  active player" questions are worth the occasional re-verification — but weight the
  content mix toward the stats that don't need maintenance.
- **Only revisit a paid API if/when this needs real accounts and a live leaderboard**
  (see section 6) — at that scale, the cost is easier to justify against real usage.

## 2. Midnight auto-refresh — simpler than it sounds
**The key fact: nothing needs to "run" at midnight at all.** The daily selection is a
pure function — `selectDailyQuestions(date, pool)` — already built and tested in the
prototypes. Given a date, it deterministically returns the same 5 questions every time,
for everyone. There's no batch job, no cron, no scheduled task computing "today's
puzzle" in advance and storing it somewhere. Every page load just computes today's date
and derives the answer on the spot.

**What actually needs deciding:**
- **Fixed reference timezone.** Already designed — `America/New_York`, matching
  GeoSports' choice. Every player gets the same puzzle regardless of their own
  timezone; the "day" changes at midnight Eastern for everyone simultaneously.
- **Client-side clock trust — BUILT, ahead of the v1.5 trigger below.** Computing
  "today" from the player's own device clock was spoofable: set the system clock back,
  replay an old puzzle, pad a streak. This is now decided server-side by the Worker in
  `worker/`, which went in earlier than this plan plotted it because it was the same
  change as closing the pool leak (below) — one Worker fixes both, so splitting them
  across releases would have meant doing the work twice. It's still no database and no
  cron, just a stateless function. Verified by shifting a real browser's clock 45 days
  and confirming the served questions don't move. See DEPLOY.md.

## 3. Security — concrete findings, not a generic checklist
I audited the existing prototypes rather than writing hypothetical guidance, and found
one real, exploitable bug:

**Found and fixed: reflected XSS in a challenge-link feature.** In an earlier prototype
that's since been scrapped (see section 0 below), the `from` name in a challenge URL
(`?challenge=1&from=...`) was interpolated directly into `innerHTML` unescaped. Since
challenge links are *designed* to be shared and clicked by other people, a malicious
link crafted to look like a normal invite — `?from=<img src=x
onerror=alert(document.cookie)>` — would have executed arbitrary script in the
recipient's browser the moment they opened it. Confirmed exploitable, then confirmed
fixed, by actually building and firing the payload against both versions of the code.
That specific file is gone now, but the bug pattern isn't specific to it — the moment
challenge links were added to site/index.html, the exact
same fix went in from the start: sanitize untrusted URL params at the point of
parsing, not case-by-case at each usage site downstream.

**General rule this bug illustrates:** anything that arrives via a URL parameter,
`localStorage`, or any other player-controllable channel is untrusted input the moment
it's going to touch the DOM. Sanitize at the parsing boundary, not case-by-case at each
usage site — that's what let this bug exist in the first place (some usages might have
been escaped correctly while others weren't).

**Rest of the security posture, realistic for what this app actually is:**
- **No accounts, no backend, no PII collected in v1** — genuinely small attack surface.
  `localStorage` only holds a streak counter and last-played date, nothing sensitive.
- **No secrets to leak yet** — there's no API key in the client because there's no paid
  API. If Highlightly's free key gets added for curation tooling, that's a
  research-time tool, not something the shipped site calls — never put it in
  client-side JS if that ever changes.
- **HTTPS and basic DDoS protection come free** with any reputable static host (Vercel,
  Netlify, Cloudflare Pages all provide both by default) — this isn't something to
  build, just something to not build custom insecure hosting instead of.
- **Content Security Policy header** — worth adding even for a simple static site,
  costs nothing, and would have provided defense-in-depth against the XSS bug above
  even before the code fix. A basic policy restricting script sources to `'self'` is a
  reasonable default for a site with no third-party scripts beyond Google Fonts.
- **No npm dependencies currently** (vanilla JS/SVG throughout) — keep it that way as
  long as reasonably possible. Every dependency is attack surface and a supply-chain
  risk; this project doesn't need a framework to do what it does. If Claude Code does
  introduce a build step or dependencies, add `npm audit` to whatever CI runs.
- **Rate limiting** isn't needed yet (no backend endpoints to abuse) but becomes
  relevant the moment any server-side function exists (the time-authority edge
  function in section 2, or a future leaderboard API) — flag as a requirement at that
  point, not before.

## 4. Realistic costs
- **Hosting:** $0. Vercel, Netlify, or Cloudflare Pages free tiers comfortably cover a
  static site with occasional edge-function calls at any traffic level this project is
  likely to see pre-launch and for a good while after.
- **Domain:** ~$10-15/year — the one real, unavoidable cost.
- **Data:** $0 (manual research) or up to ~$15/month if Highlightly's Pro tier gets
  added later for curation convenience — optional, not required.
- **Total realistic v1 cost: roughly the price of a domain name, nothing more.**
- **What would actually add cost later:** a database and auth system for real accounts
  and a public leaderboard (v2, see below) — even then, Supabase or Neon's free tiers
  handle meaningful traffic before any payment is required. Budget for this only once
  v1 has real usage data justifying it.

## 5. Scope for v1 — the actual 0→1 bar
**Current state, precisely:** site/index.html has the click-to-plot mechanic,
the scoring engine, and a working multi-round loop with real NBA/NFL data. It does
*not* yet have the daily-selection function or the streak/challenge-link system —
those were built and tested in the older guesstimate.html (the numeric-slider version,
now itself superseded by the scatter mechanic). They need to be **ported into**
site/index.html, not assumed already present there.

- [x] 15-20 real, sourced questions across at least NBA and NFL (verified data, not
      placeholders) — **done: 16 questions, 7 NBA / 5 NFL / 4 MLB**, every number
      verified against a named source
- [x] Port `selectDailyQuestions` — done, and then moved again: it now lives in
      `worker/src/selection.js` and runs server-side. Never rewritten, just relocated
- [x] Port the streak/localStorage system the same way
- [x] Build challenge-links for the scatter version fresh, with the XSS-safe escaping
      pattern from section 3 included from the start
- [x] Label-collision handling for the scatter chart — replaced the `i%2` alternation
      with geometry-based placement
- [ ] Deployed to a real URL on a static host, custom domain — **config is ready and
      tested locally (see DEPLOY.md); the remaining steps need an interactive
      Cloudflare login and a domain purchase, so they're a human's to run**
- [ ] Played end-to-end by people who aren't you or me — the last real gap

## 6. Future features, in order — and what triggers each one
Each phase has a concrete trigger condition, not just "do this next":
- **v1.1** — shuffled-bag anti-repeat rotation (spec already written, not yet built),
  once the question pool is large enough that repeats would actually be noticeable.
- **v1.2** — server-authoritative time via a lightweight edge function, if/when
  clock-spoofing becomes a real complaint rather than a theoretical one (see section 2).
- **v1.3** — more leagues and stat combos (MLB, NFL passing/receiving, NHL) — ongoing,
  gated by research pace, not a single milestone.
- **v2** — real accounts and a public daily leaderboard, once v1 has enough organic
  usage to justify the jump from "no backend" to "database + auth." This is the point
  where the security posture needs real revisiting — auth security, rate limiting on
  real endpoints, and a live-data API subscription (section 1) might finally earn its
  cost.
- **v2.x** — social features (groups, friend leaderboards, GeoSports has these),
  difficulty tiers, a stats/history page for past rounds.
- **v3** — native app wrapper and push notifications for the daily-reminder habit loop,
  once the web version has proven the core loop is sticky enough to be worth it.

Don't build v2+ features speculatively — every phase above is written with its trigger
condition specifically so "future features" doesn't quietly become "things built before
anyone asked for them."
