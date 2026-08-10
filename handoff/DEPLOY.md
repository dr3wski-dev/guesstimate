# Deploying Guesstimate

Two pieces, both on Cloudflare, both free at this project's scale:

| Piece | What | Where |
|---|---|---|
| Static site | the game itself | Cloudflare Pages |
| `guesstimate-api` | today's questions | Cloudflare Workers, routed at `/api/*` on the same domain |

**They must share a domain.** The page's CSP is `connect-src 'self'`, so the game
can only call an API on its own origin. That's deliberate — it means no CORS, no
third-party origin in the policy, and a preflight can never be the reason the
game fails to load. If the Worker ends up on a `*.workers.dev` host instead, the
origin has to be added to *both* `_headers` and the `<meta http-equiv>` CSP in
`site/index.html`, or every request the game makes is blocked
with nothing useful in the console.

---

## What has to be done by a human, in a browser

None of this can happen from a terminal session — it all needs an interactive
Cloudflare login.

1. **Connect the repo to Cloudflare Pages.** Dashboard → Workers & Pages → Create
   → Pages → Connect to Git → pick `dr3wski-dev/guesstimate`.
   - Build command: none (there is no build step)
   - Build output directory: `handoff/site`
   - `_headers` sits at `handoff/site/_headers`, i.e. the root of that output
     directory, which is the only place Pages will read it from. If the output
     directory is ever changed, move `_headers` with it — a misplaced `_headers`
     fails silently, with no warning and no headers.

   **`handoff/site/` contains the entire published site and nothing else. That
   separation is load-bearing, not tidiness.** Pages serves every file in the
   output directory, so if `data/questions.json` lived inside it, the full
   question pool would be downloadable at `/data/questions.json` and the Worker
   would be pointless — the exact leak it was built to close, reopened by a
   directory layout. `data/` and `worker/` sit outside `site/` deliberately.
   Verify after any restructure: `curl -sI https://<site>/data/questions.json`
   must be a 404.
2. **Deploy the Worker.** From `handoff/worker/`: `wrangler login` (opens a
   browser), then `wrangler deploy`. The dashboard's "create Worker" flow works
   too — paste `src/index.js` and `src/selection.js`.
3. **Add the custom domain** to the Pages project, then uncomment the `routes`
   block in `worker/wrangler.toml`, set the real domain, and redeploy the Worker
   so `/api/*` resolves on it.
4. **Make the OG tags absolute.** `og:image` and `og:url` in the HTML are
   relative. iMessage and most crawlers won't resolve a relative `og:image`, so
   the link preview — which for this game *is* the landing page — will be blank
   until these are absolute URLs on the real domain.

## Verify after deploying

```sh
curl -sI https://<site>/ | grep -i content-security-policy   # header present
curl -s  https://<site>/api/daily | jq '.questions | length'  # 5, never 16
curl -sI https://<site>/api/daily | grep -i x-cache           # MISS then HIT
```

Then open dev tools on the live site and confirm the Network tab shows a request
to `/api/daily` returning five questions, and **no** request to
`data/questions.json`. That file is still in the repo — it's the canonical
content source and the Worker bundles it at build time — but the browser must
never fetch it.

---

## Why the API exists at all

Both reasons are things a client holding the whole pool cannot fix:

- **The pool was public.** The page used to fetch `data/questions.json`, so every
  future day's answers were one dev-tools panel away.
- **The date was the player's to choose.** "Today" came from the device clock, so
  setting the system clock back replayed old puzzles and padded streaks.

Now the Worker decides both. The client sends no date except a challenge link's,
and the Worker refuses any date that isn't already in the past.

**What this does *not* fix, stated plainly so it isn't over-read:** the five
questions being played still reach the browser with their answers attached
(`targetX`, `targetY`, `fact`), because scoring and the reveal happen
client-side. Today's five answers remain readable in the network tab. Closing
that would mean posting guesses to the server to be scored — a real backend with
real abuse surface, gated to v2 in ACTION_PLAN.md section 6, and not what either
of the above gaps was about.

## Cost and limits

Free tier: 100,000 Worker requests/day. Every visitor triggers at most one
`/daily` call, and the response is cached at the edge per date, so the selection
logic runs roughly once per day per edge location no matter how many people
play. Nothing here approaches a paid tier. There is no database, no KV, no
Durable Object, and no secret — if any of those ever get added, the "free and
stateless" property is gone and ACTION_PLAN.md section 3 needs rereading first.

## Adding questions after launch

Edit `data/questions.json`, then **redeploy the Worker** — the pool is bundled
into it at build time. Pushing a content change alone will update the Pages site
but not the questions the API serves.
