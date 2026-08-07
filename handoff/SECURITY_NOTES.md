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
This is a static site with no accounts, no backend, and no PII collected in v1 — the
attack surface is small by design, and the plan should keep it that way as long as
possible rather than adding infrastructure speculatively.

- **No secrets in client-side code.** There's currently no paid API key anywhere in
  this project. If a Stathead or Highlightly API key ever gets used, it's a
  human-curation tool (see 0_TO_1_ACTION_PLAN.md section 1) — it should never end up
  in code that ships to a browser.
- **HTTPS and basic DDoS protection are free** with any reputable static host (Vercel,
  Netlify, Cloudflare Pages) — use one of these rather than custom hosting, and this is
  handled without extra work.
- **Add a Content-Security-Policy header** even though the site is simple — costs
  nothing, and a policy restricting script sources to `'self'` would have provided
  defense-in-depth against the XSS bug above even before the code-level fix existed.
  Belt and suspenders, not an either/or.
- **Keep the zero-dependency approach as long as reasonably possible.** Every npm
  package is both attack surface and a supply-chain risk. This project doesn't
  currently need a framework to do what it does — vanilla JS/SVG has worked for
  everything built so far. If a build step or dependencies do get introduced, add
  `npm audit` (or equivalent) to whatever CI runs, and check it, don't just have it.
- **Rate limiting isn't needed yet** — no server-side endpoints exist to abuse. It
  becomes a real requirement the moment any backend function exists (e.g. a future
  server-authoritative time check, or a v2 leaderboard API) — flag it at that point,
  not before.
- **Any future accounts/leaderboard (v2) needs a full re-audit at that time** — proper
  auth security, session handling, and rate limiting on real endpoints are a different
  risk category than anything in v1, and deserve dedicated attention when that phase
  actually starts, not a checkbox in this document written before any of it exists.

## The one-line rule worth remembering
**Anything that arrives via a URL parameter, localStorage, or any other
player-controllable channel is untrusted the moment it's going to touch the DOM.**
Every bug in this document is a variation on forgetting that.
