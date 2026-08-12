# Deploying Guesstimate

The game is a static site with no backend, no build toolchain, and no npm
dependencies. Deploying it is genuinely a 20-minute job. This is the runbook.

## What gets deployed

`site/` at the repo root, produced by `handoff/pipeline/build_site.py` from the
canonical sources:

```
handoff/reference/guesstimate-scatter.html   the game (source of truth)
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

# 2. Sanity-check it locally before pushing
cd site && python3 -m http.server 8900     # then open http://localhost:8900/

# 3. Optional but recommended: run the regression suite against the built site
#    (edit BASE in reference/verify.mjs to http://localhost:8900/)
node handoff/reference/verify.mjs
```

Then point a host at it:

- **Netlify / Cloudflare Pages** — publish directory `site`, no build command.
  `_headers` is picked up automatically.
- **Vercel** — root directory `site`, framework preset "Other", no build command.
  `vercel.json` is picked up automatically.

All three free tiers cover this comfortably, and all three give HTTPS and basic DDoS
protection without configuration — which is the whole reason ACTION_PLAN §3 says not
to build custom hosting.

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
- [ ] **Confirm `data/questions.json` is served with a short cache.** `_headers` sets
      300s. If a CDN overrides it, shipping new content won't reach players.

## After deploying

Two things from LAUNCH_CHECKLIST.md are worth doing in the same session, while you
still have the host's dashboard open:

1. **Analytics** (B3) — **the code side is done**, so this is now just an account.
   Seven events are already instrumented: `round_start`, `question_submit`,
   `round_complete`, `share_click`, `challenge_open`, `restore_export`,
   `restore_import`. They no-op until a provider is installed, and the provider is a
   build flag, so no vendor snippet is ever pasted into the game:

   ```bash
   # Plausible — custom events supported, ~$9/mo
   --analytics plausible --analytics-domain your-domain.com
   # Cloudflare Web Analytics — free, cookieless, pageviews only (no custom events)
   --analytics cloudflare --analytics-domain <beacon-token>
   ```

   The build extends the CSP for exactly that provider's hosts rather than loosening
   it globally. Building without `--analytics` produces a site with **no third-party
   requests at all** — verify with `grep -oE 'https?://[a-z0-9.-]+' site/index.html`,
   which should show only your own domain.

   The events carry a puzzle number, a score band and a mode. No names, no free text,
   nothing a player typed. The site collects no PII today; keep it that way.

2. **A stats restore code** — **done.** The stats modal now exports a `GT1-…` code and
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
```

`verify_questions.py` re-derives every number in `questions.json` straight from the
raw datasets, on a separate code path from the generator. Treat a non-zero exit as
blocking — it exists because the generator has already shipped a plausible-looking
number that never happened (see its docstring).

## Rollback

The site is static and the build is deterministic, so rollback is `git revert` plus a
rebuild, or the host's own "redeploy previous build" button. There is no database to
migrate and no state on the server — the only persistent state is in each player's
`localStorage`, which is why the stats key is versioned (`guesstimate_stats_v2`).
