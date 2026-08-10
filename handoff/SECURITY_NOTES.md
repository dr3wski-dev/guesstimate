# Security Notes
Concrete findings from an actual audit, not a generic checklist. Read this before
adding any feature that touches a URL parameter, localStorage, or user-supplied text.

## Found and fixed: reflected XSS in a challenge-link feature
In an earlier prototype (since scrapped — see 0_TO_1_ACTION_PLAN.md section 0), a
challenge-link's sender name (`?challenge=1&from=...`) was pulled from the URL and
interpolated directly into `innerHTML` with no escaping. Since challenge links are
*designed* to be shared and clicked by other people, this was fully exploitable: a link
crafted to look like a normal invite —
```
?challenge=1&from=<img src=x onerror=alert(document.cookie)>&score=4
```
— would execute arbitrary script in the browser of whoever clicked it, no different
from clicking a link from a friend. This was confirmed two ways, not just reasoned
about: built the actual payload, loaded it, watched the alert fire; then applied the
fix and watched the same payload render as inert text instead.

**The fix, and the pattern to repeat:**
```js
function escapeHtml(str){
  const div = document.createElement('div');
  div.textContent = str;   // browser escapes for us
  return div.innerHTML;
}
```
Applied at the point of *parsing* untrusted input (reading the URL param), not at each
downstream usage site. That matters: escaping case-by-case at every place a value gets
used is exactly how a bug like this slips through — some usages get escaped, one
doesn't, and that one is the vulnerability. Escape once, at the boundary where
untrusted data enters the program, and everything downstream is already safe.

Also worth doing alongside escaping, applied in the same fix:
- **Clamp numeric params to valid ranges** — a score param should be rejected or
  clamped if it's not a real number 0-5, not trusted as-is.
- **Whitelist-filter structured params** — a win/loss pattern string should have every
  character that isn't an expected value (e.g. `G`/`R`) stripped, not passed through.
- **Cap string length** — a 30-character cap on a "name" field costs nothing and closes
  off a class of abuse (absurdly long strings breaking layout, or just being obnoxious).

**Guesstimate-scatter.html does not have challenge links yet, so it does not have this
specific bug yet — but the moment they're added, build them with this pattern from the
start, not as a retrofit.**

## General security posture for this project specifically
This is a static site with no accounts and no PII collected in v1 — the attack
surface is small by design, and the plan should keep it that way as long as possible
rather than adding infrastructure speculatively.

The one piece of server-side code is `worker/` — a stateless Cloudflare Worker that
returns today's five questions. It takes no input except an optional date (refused
unless it's already in the past), stores nothing, holds no secret, and has no
binding to any database or KV namespace. It exists because two problems were
unfixable in a client that holds the whole question pool: the pool was public, so
future days' answers were one dev-tools panel away, and "today" came from the device
clock, so it was trivially spoofable. **What it does not fix, worth being explicit
about: the five questions actually in play still reach the browser with their
answers attached, because scoring happens client-side.** Anyone can read today's
answers out of the network tab. Fixing that means server-side scoring, which is a
real backend with real abuse surface — v2, not now.

- **No secrets in client-side code.** There's currently no paid API key anywhere in
  this project. If a Stathead or Highlightly API key ever gets used, it's a
  human-curation tool (see 0_TO_1_ACTION_PLAN.md section 1) — it should never end up
  in code that ships to a browser.
- **HTTPS and basic DDoS protection are free** with any reputable static host (Vercel,
  Netlify, Cloudflare Pages) — use one of these rather than custom hosting, and this is
  handled without extra work.
- **Content-Security-Policy — DONE, in two places.** `_headers` (read by Cloudflare
  Pages from the publish root) and a matching `<meta http-equiv>` in the HTML. The
  duplication is intentional: the meta tag keeps the protection when the file is
  opened with no server setting headers, and the file covers what a meta tag can't
  express (`frame-ancestors`). Change one, change both. One honest caveat:
  `script-src` still allows `'unsafe-inline'`, because the whole game is one inline
  `<script>` in a single self-contained file and a strict policy would stop it from
  running at all. The fix is extracting the script to its own `.js`, not editing the
  policy. Until then the escaping at the URL-parameter parsing boundary — the rule at
  the bottom of this document — is what's actually carrying the weight here, and the
  CSP is genuine defense-in-depth rather than the primary control.
- **Keep the zero-dependency approach as long as reasonably possible.** Every npm
  package is both attack surface and a supply-chain risk. This project doesn't
  currently need a framework to do what it does — vanilla JS/SVG has worked for
  everything built so far. If a build step or dependencies do get introduced, add
  `npm audit` (or equivalent) to whatever CI runs, and check it, don't just have it.
- **Rate limiting — now worth a second look, though still not urgent.** A server-side
  endpoint does exist as of the questions Worker, which is the trigger this line used
  to point at. It's a weak trigger in practice: the endpoint is a pure function with
  no writes, nothing to exhaust, and the same response for everybody, and it's cached
  at the edge per date so hammering it mostly hits cache rather than the Worker. The
  realistic worst case is burning through the 100k/day free tier, which Cloudflare's
  own protections largely absorb. Revisit properly — as a real requirement, not a
  note — the moment any endpoint *writes* anything (a v2 leaderboard submit).
- **Any future accounts/leaderboard (v2) needs a full re-audit at that time** — proper
  auth security, session handling, and rate limiting on real endpoints are a different
  risk category than anything in v1, and deserve dedicated attention when that phase
  actually starts, not a checkbox in this document written before any of it exists.

## The one-line rule worth remembering
**Anything that arrives via a URL parameter, localStorage, or any other
player-controllable channel is untrusted the moment it's going to touch the DOM.**
Every bug in this document is a variation on forgetting that.
