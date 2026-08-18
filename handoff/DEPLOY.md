# Deploying StatMap

Two pieces, both on Cloudflare, both free at this scale:

| piece | what it serves | where |
|---|---|---|
| the site | the game, fonts, OG image | Cloudflare Pages, publish dir `site/` |
| `statmap` | one day's questions | Cloudflare Workers, routed at `/api/*` on the same domain |

**They must share a domain.** The page's CSP is `connect-src 'self'`, so the game can
only call an API on its own origin. That's deliberate: no CORS, no third-party origin
in the policy, and a preflight can never be the reason the game fails to load. If the
Worker ends up on a `*.workers.dev` host instead, that origin has to be added to
**both** the `CSP` constant in `pipeline/build_site.py` **and** the `<meta
http-equiv>` CSP in the reference file — otherwise every request the game makes is
blocked, with nothing useful in the console.

**The game does not start without the Worker.** There is no static fallback, on
purpose — a fallback would mean shipping the pool again, which is the leak the Worker
exists to close.

## What gets deployed

`site/` at the repo root, produced by `handoff/pipeline/build_site.py` from the
canonical sources:

```
handoff/reference/statmap.html   the game (source of truth)
handoff/data/questions.json                  the content
handoff/assets/                              fonts + OG image
                    |
                    v
site/index.html, site/data/, site/assets/, site/_headers, site/vercel.json,
site/robots.txt, site/sitemap.xml
```

**Never hand-edit `site/`.** It is regenerated wholesale on every build. Edit the
reference file or the data and rebuild. The build exists specifically so there is no
second copy of the game to drift out of sync.

What the build changes, and why each one matters:

| change | why |
|---|---|
| `fetch('../data/…')` → `fetch('data/…')` | at a web root the data is a sibling, not a parent |
| `url('../assets/fonts/…')` → `url('assets/fonts/…')` | same |
| `og:image` → absolute URL | **relative `og:image` is the most common cause of a blank link card**, and iMessage will not resolve one. For a game distributed by pasted links, that card is the landing page |
| adds `og:url` + `<link rel="canonical">` | so shares of `?challenge=…` URLs still resolve to the canonical page |
| `_headers` / `vercel.json` | CSP as a real header, plus caching |

## Deploy

```bash
# 1. Build for your real domain (must be an https origin, no path)
python3 handoff/pipeline/build_site.py --url https://your-domain.com

#    ...or with analytics installed in the same step (see below)
python3 handoff/pipeline/build_site.py --url https://your-domain.com \
    --analytics plausible --analytics-domain your-domain.com

# THE COMMAND THIS PROJECT ACTUALLY DEPLOYS WITH. CI runs exactly this and then
# fails if committed site/ differs, so build with these flags or the check trips.
python3 handoff/pipeline/build_site.py --url https://statmap.app \
    --analytics umami --analytics-domain 3acb4aa9-ff47-4133-8bad-a14e592a0ebb

# AFTER CHANGING ANALYTICS, OPEN THE DEPLOYED SITE AND CHECK THE BROWSER CONSOLE.
# This cannot be automated from the build. An analytics script is served from one
# host and sends to another, and only the first is knowable statically — so a CSP
# that names the script host and not the send host produces a site that loads the
# tag, logs nothing anywhere, and collects nothing. That shipped, and the only
# symptom was an empty dashboard, which looks exactly like having no visitors.
# You are looking for the absence of lines reading "violates the following Content
# Security Policy directive".

# 2. Sanity-check it locally before pushing
cd site && python3 -m http.server 8900     # then open http://localhost:8900/

# 3. Optional but recommended: run the regression suite against the built site
#    (edit BASE in reference/verify.mjs to http://localhost:8900/)
node handoff/reference/verify.mjs
```

Then point a host at it:

- **Cloudflare Pages** — publish directory `site`, no build command. `_headers` is
  picked up automatically from the root of that directory.
- **Netlify** — same: publish directory `site`, no build command.
- **Vercel** — root directory `site`, framework preset "Other", no build command.
  `vercel.json` is picked up automatically.

All three free tiers cover this comfortably, and all give HTTPS and basic DDoS
protection without configuration — which is the whole reason ACTION_PLAN §3 says not
to build custom hosting.

## Deploying the Worker

The API deploys separately from the site. Two ways to do it, and **the choice matters
for how content ships later**, so pick deliberately.

**How it deploys now — from GitHub Actions, gated on the tests.** `.github/workflows/checks.yml`
runs the gates and then, on a push to `main` only, deploys the Worker and verifies
that the live API is serving this commit's pool. Two things follow from that:

1. **Cloudflare's own Workers Builds should be disconnected** for this Worker
   (Settings → Build → Disconnect). Two deployers pointed at one Worker race, and the
   loser silently wins about half the time.
2. **The repo needs a `CLOUDFLARE_API_TOKEN` secret.** Create it with Cloudflare's
   "Edit Cloudflare Workers" template, then add it under Settings → Secrets and
   variables → Actions. Add `CLOUDFLARE_ACCOUNT_ID` too if the token can see more
   than one account.

Why this rather than the dashboard builder: Cloudflare's builder triggers on push and
never consults the test workflow, so every gate in this repo could fail and the API
would deploy anyway. `needs: gates` makes them load-bearing. It also puts the deploy
configuration under review in a pull request, instead of in a settings page nobody
reads until something breaks.

**Legacy — Workers Builds (the dashboard builder).** If you reconnect it: Workers &
Pages → Create → Import a repository → pick this repo, then set the deploy and
version commands to carry the config path (see the box below — the root directory
field will not do this for you). From then on every push to the default branch
redeploys the Worker automatically, which means a content change reaches players by
pushing, with nothing to remember. That matters more than it sounds: the pool is
bundled into the Worker, so a forgotten manual deploy is a silent failure — the site
updates, the questions don't, and nothing anywhere says so.

> **The "Root directory" setting does not move the deploy step.** This cost an
> evening, so it is written down in full.
>
> With root directory set to `handoff/worker`, the build still failed with
> `Missing entry-point to Worker script or to assets directory` — the identical
> error, to the byte, that it produced with the setting unset. That error is what
> wrangler says when it finds no config **at all**, not when it finds a broken one:
> it ran in the repository root, where there is deliberately no `wrangler.toml`, and
> reported the absence as a missing entry point. So the setting appears to govern
> dependency caching and tool detection, and not the working directory the deploy
> command runs in.
>
> **The fix is to put the path in the command, where it cannot be misread:**
>
> ```
> Deploy command:   npx wrangler deploy -c handoff/worker/wrangler.toml
> Version command:  npx wrangler versions upload -c handoff/worker/wrangler.toml
> Root directory:   (empty)
> ```
>
> `main = "src/index.js"` resolves relative to the config file rather than the
> working directory, so this builds byte-identically to running wrangler from inside
> `handoff/worker` — 183.58 KiB either way. Verify with
> `npx wrangler deploy --dry-run -c handoff/worker/wrangler.toml` from the repo root.
>
> Do NOT fix this by adding a `wrangler.toml` at the repository root. Pages reads a
> root-level `wrangler.toml` as *its* configuration, so that trades a broken API
> build for a broken site build.
>
> Two commands appear in these logs and they do different things. `wrangler deploy`
> releases to production; `wrangler versions upload` uploads a version without
> releasing it, and is correct for non-production branches only. A production branch
> configured with `versions upload` builds green forever and never changes what
> players get — the same silent failure as a forgotten manual deploy, wearing a
> passing check mark.

**Manual.** Needs an interactive Cloudflare login, so it can't be done from a
terminal-only session:

```bash
cd handoff/worker
wrangler login          # opens a browser
wrangler deploy         # first deploy lands on *.workers.dev, which is fine for testing
```

Either way, once the Pages project has its custom domain:

1. Uncomment the `routes` block in `worker/wrangler.toml` and set the real domain.
2. Push (Workers Builds) or `wrangler deploy` again, so `/api/*` resolves on the
   site's own origin.

The question pool is **bundled into the Worker** at build time via a JSON import of
`data/questions.json` — the same canonical file the content workflow edits. There is
no second copy to keep in sync, which also means **shipping new content requires
redeploying the Worker**, not just pushing the site. On Workers Builds that happens on
push; on the manual path it is a step you have to remember. The same is true of
`data/schedule.json`.

The Worker has no KV, no D1, no Durable Objects, no secrets, and no bindings. If that
ever changes, the "stateless pure function" property that makes it free and hard to
abuse is gone, and ACTION_PLAN §3 needs rereading first.

## The leak this is all protecting against

`site/` is published wholesale by Pages, so **anything inside it is downloadable**.
The question pool must never be in there — if `data/questions.json` were served, every
future day's answers would be one URL away and the Worker would be pointless, the
exact hole it was built to close, reopened by a directory layout.

`pipeline/build_site.py` asserts the built HTML never fetches the pool and that the
client calls `/api/daily`, so re-introducing the leak fails the build rather than
shipping. Verify on the live site anyway after any restructure:

```sh
curl -sI https://<site>/data/questions.json     # must be 404
```

**`pipeline/build_demo.py` is the deliberate exception, and must never be deployed.**
It produces a single self-contained HTML file that carries the whole pool, because a
demo has no Worker to ask. That re-opens exactly the leak described above, which is
why it is a separate script from `build_site.py`, stamps a visible banner on the page
saying the answers are readable, and is only ever handed to a few people directly:

```bash
python3 handoff/pipeline/build_demo.py -o demo.html   # sharing only, never hosting
```

Worth being precise about what this does *not* fix: today's five questions still
travel to the browser with their answers attached, because scoring and the reveal
happen client-side. A determined player can read today's answers from the network tab.
They cannot read tomorrow's, and they cannot move their system clock to farm a streak.
Hiding today's too would mean posting guesses to the server for scoring — a real
backend with real abuse surface, out of scope per ACTION_PLAN §6.

## Before you point the domain at it

- [ ] **Rebuild with the final URL.** The OG tags bake the domain in. If you build
      with a placeholder and then buy a different domain, the link card breaks and
      you won't notice, because it renders fine for you.
- [ ] **Regenerate the OG image** if the design changed — `handoff/assets/og-source.html`
      is the source, 1200×630.
- [ ] **Test the link card for real.** Paste the URL into iMessage and Slack, not just
      a validator. This is the first impression for essentially every player.
- [ ] **Open it on an actual phone.** The layout is tested at 390×664 in a headless
      browser, which is not the same as a thumb.
- [ ] **Check the CSP didn't break anything** — open the console and confirm no
      violations. The policy allows `'unsafe-inline'` for scripts and styles because
      the game is a single self-contained file; that's a deliberate trade, not an
      oversight.
- [ ] **Confirm the Worker is routed on the site's domain**, not `*.workers.dev` —
      otherwise the CSP blocks every API call. `curl -s https://<site>/api/daily`
      should return JSON, not a 404 from Pages.
- [ ] **Confirm `/api/*` is served with a short cache.** `_headers` sets 300s. If a
      CDN overrides it, shipping new content won't reach players.

## After deploying

Two things from LAUNCH_CHECKLIST.md are worth doing in the same session, while you
still have the host's dashboard open:

1. **Analytics** (B3) — **the code side is done**, so this is now just an account.
   Seven events are already instrumented: `round_start`, `question_submit`,
   `round_complete`, `share_click`, `challenge_open`, `restore_export`,
   `restore_import`. They no-op until a provider is installed, and the provider is a
   build flag, so no vendor snippet is ever pasted into the game:

   ```bash
   # Umami Cloud — free to 100k events/mo, ~2KB, custom events supported. Recommended.
   --analytics umami --analytics-domain <website-id-uuid>
   # Plausible — custom events, lightest script, ~$9/mo (no free tier)
   --analytics plausible --analytics-domain your-domain.com
   # Cloudflare Web Analytics — free and unlimited, but PAGEVIEWS ONLY.
   # The seven events above will not fire. Fine as a second, parallel tracker.
   --analytics cloudflare --analytics-domain <beacon-token>
   ```

   **On Cloudflare Pages, run two:** turn on Cloudflare Web Analytics in the dashboard
   (free, unlimited, zero config, nothing in this repo) for traffic and referrers, and
   build with `--analytics umami` for the funnel. Cloudflare's own analytics cannot
   answer "did they finish all five", which is the question that decides what to build
   next.

   The build extends the CSP for exactly that provider's hosts rather than loosening
   it globally. Building without `--analytics` produces a site with **no third-party
   requests at all** — verify with `grep -oE 'https?://[a-z0-9.-]+' site/index.html`,
   which should show only your own domain.

   The events carry a puzzle number, a score band and a mode. No names, no free text,
   nothing a player typed. The site collects no PII today; keep it that way.

2. **A stats restore code** — **done.** The stats modal now exports an `SM1-…` code and
   accepts one, with a checksum so a truncated paste is rejected rather than silently
   importing garbage. Restoring merges rather than overwrites, and a restored
   `lastPlayed` still blocks a second completion the same day, so a code can't be used
   to farm streak credit.

## Shipping new content later

```bash
python3 handoff/pipeline/build_questions.py --fetch          # refresh datasets
python3 handoff/pipeline/build_questions.py --league mlb --top 20
# pick candidates, write the fact copy, add to handoff/data/questions.json
python3 handoff/pipeline/verify_questions.py                 # must report 0 mismatches
python3 handoff/pipeline/build_site.py --url https://your-domain.com
git commit -am 'content: …' && git push       # Workers Builds redeploys the API
# ...or, on the manual path:
cd handoff/worker && wrangler deploy           # the pool is bundled INTO the Worker
```

Pushing the site alone is not enough on the manual path — the Worker holds the
questions, so a content change that isn't followed by `wrangler deploy` reaches
nobody. This is the single easiest thing to get wrong here, and it is the reason
Workers Builds is the recommended setup: it removes the step entirely.

`verify_questions.py` re-derives every number in `questions.json` straight from the
raw datasets, on a separate code path from the generator. Treat a non-zero exit as
blocking — it exists because the generator has already shipped a plausible-looking
number that never happened (see its docstring).

## Verify after deploying

```sh
curl -sI https://<site>/ | grep -i content-security-policy    # header present
curl -s  https://<site>/api/daily | jq '.questions | length'  # 5, never the whole pool
curl -sI https://<site>/data/questions.json                   # 404
```

Then open dev tools on the live site and confirm the Network tab shows a request to
`/api/daily` returning five questions, and **no** request for the pool.

## Rollback

The site is static and the build is deterministic, so rollback is `git revert` plus a
rebuild, or the host's own "redeploy previous build" button. There is no database to
migrate and no state on the server — the only persistent state is in each player's
`localStorage`, which is why the stats key is versioned (`statmap_stats_v1`).
